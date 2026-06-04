"""
connectors/resolver.py — Détection de banque et résolution de compte.

Deux fonctions publiques :
    detect_connector(filepath)      → quel connecteur traite ce fichier ?
    resolve_accounts(connector, filepath) → quels comptes DB correspondent ?

Pourquoi ce module existe
-------------------------
Avant ce module, chaque commande de management (import_yuh, import_ubs, import_cic)
avait sa propre méthode _find_account() avec une logique différente.
La vue Phase 2F (upload web) ne peut pas appeler des management commands.
→ Cette logique est extraite ici pour être partagée par commandes ET vues.

Stratégie de résolution par banque
------------------------------------
    Yuh  : pas d'identifiant dans le fichier → matching par convention (1 seul compte
           Yuh actif en DB). Si plusieurs comptes → AccountAmbiguous levée → picker UI.
    UBS  : IBAN en ligne 2 du fichier → Account.iban (universel : checking + savings)
    CIC  : fichier multi-feuilles → 1 RIB par feuille → Account.contract_number

Identifiants de résolution
----------------------------
    Account.iban            : bancaires avec IBAN (UBS checking, UBS savings, futures cartes)
    Account.contract_number : tout le reste (CIC RIB, Finpension n° contrat, Swiss Life n° police...)

    Règle : on ne résout JAMAIS par Account.name (trop fragile si l'utilisateur renomme).
    On résout toujours par un identifiant présent dans le fichier exporté.

Ajouter une nouvelle banque
---------------------------
1. Créer le connecteur  connectors/<banque>/parser.py
   Implémenter : matches_file(), parse(), optionnellement extract_balance()
   et extract_account_identifier()
2. Ajouter l'instance dans CONNECTORS ci-dessous (une ligne)
3. Ajouter un elif dans resolve_accounts() avec la logique de matching DB

Ajouter un nouveau compte (banque existante)
--------------------------------------------
1. Créer Account en DB (admin ou seed) — bank, name, account_type, currency
2. Créer la spécialisation : CheckingAccount (IBAN + BIC) ou SavingsAccount
3. Renseigner l'identifiant de résolution :
   - UBS  → Account.iban (IBAN sans espaces — jamais en clair dans le code, via .env)
   - CIC  → Account.contract_number (RIB sans espaces)
   - Yuh  → rien (convention : 1 seul compte Yuh actif)
   - Finpension/assurance → Account.contract_number (n° de contrat/police)

Ajouter une nouvelle carte (Phase 6)
--------------------------------------
1. Créer Card en DB — checking_account, user, last_four, card_type, is_active=True
2. Le connecteur extrait card_last_four du relevé
3. Le service fait le matching automatiquement via un dict {last_four: Card}

Types futurs à anticiper (Phase 7+)
--------------------------------------
    INSURANCE  → résolution par Account.contract_number (n° police)
                 Connecteur : PDF ou CSV relevé de valeur
                 Pas de transactions bancaires — BalanceSnapshot seulement
    BROKERAGE  → résolution par Account.contract_number (n° courtier)
                 Connecteur : CSV mensuel Swissquote / IBKR
                 Transactions = achats/ventes de titres (même pattern ImportService)
    PENSION    → résolution par Account.contract_number (n° contrat Finpension)
                 Connecteur : CSV export Finpension
                 Transactions = cotisations, frais, gains/pertes
"""

from dataclasses import dataclass, field
from pathlib import Path

from accounts.models import Account
from connectors.base import BaseConnector
from connectors.cic.parser import CICConnector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector


class AccountNotFound(Exception):
    """
    Levée par resolve_accounts() quand un compte est introuvable en DB.

    Porte les métadonnées nécessaires pour construire un lien admin pré-rempli
    et afficher un message utile à l'utilisateur.

    Attributs :
        contract_number     : identifiant extrait du fichier (RIB/IBAN normalisé)
        contract_number_raw : identifiant brut tel qu'il apparaît dans le fichier
        bank_slug           : slug de la banque détectée (ex: "cic", "ubs")
        sheet_name          : nom de la feuille CIC, ou None pour les autres banques
        account_name_hint   : suggestion de nom pré-remplie dans le formulaire de création
    """

    def __init__(
        self,
        contract_number,
        contract_number_raw,
        bank_slug,
        sheet_name=None,
        account_name_hint=None,
    ):
        self.contract_number = contract_number
        self.contract_number_raw = contract_number_raw
        self.bank_slug = bank_slug
        self.sheet_name = sheet_name
        self.account_name_hint = account_name_hint
        super().__init__(
            f"Aucun compte trouvé pour le RIB/IBAN '{contract_number_raw}' "
            f"(banque : {bank_slug}). Configurez ce compte dans l'admin Django."
        )


class AccountAmbiguous(Exception):
    """
    Levée quand plusieurs comptes correspondent et qu'on ne peut pas trancher
    automatiquement (Yuh sans identifiant dans le fichier).

    La vue attrape cette exception et affiche un picker à l'utilisateur.

    Pourquoi Yuh déclenche ça ?
        Yuh n'expose aucun identifiant de compte dans ses exports CSV.
        Si l'utilisateur a un seul compte Yuh → on l'utilise directement (convention).
        Si l'utilisateur a plusieurs comptes Yuh → impossible de choisir sans lui.
        → AccountAmbiguous porte la liste de candidats pour le picker UI.

    Attributs :
        accounts  : liste des Account candidats (déjà filtrés bank + is_active)
        bank_slug : slug de la banque (ex: "yuh")
    """

    def __init__(self, accounts: list[Account], bank_slug: str):
        self.accounts = accounts
        self.bank_slug = bank_slug
        super().__init__(
            f"{len(accounts)} comptes trouvés pour la banque '{bank_slug}'. "
            "Sélection manuelle requise."
        )


# Ordre important : si un fichier peut matcher plusieurs connecteurs (peu probable),
# le premier gagne. Mettre les connecteurs les plus spécifiques en premier.
CONNECTORS: list[BaseConnector] = [
    YuhConnector(),
    UBSConnector(),
    CICConnector(),
]


@dataclass
class AccountMatch:
    """
    Un compte bancaire résolu pour un fichier source donné.

    Toujours retourné dans une liste par resolve_accounts() — même pour Yuh
    (1 seul élément). Le caller peut itérer uniformément sans cas particulier.

    parse_kwargs : arguments à passer à connector.parse() pour cibler la bonne
    feuille dans les fichiers multi-comptes (CIC). Vide pour Yuh/UBS.
    """

    account: Account
    sheet_name: str | None = None  # None pour Yuh/UBS, nom de feuille pour CIC
    parse_kwargs: dict = field(
        default_factory=dict
    )  # ex: {"sheet_name": "Compte courant"}


def detect_connector(filepath: Path) -> BaseConnector | None:
    """
    Retourne le premier connecteur qui reconnaît le fichier, ou None.

    Chaque connecteur implémente matches_file() qui inspecte extension,
    encodage, en-têtes de colonnes, ou structure Excel pour identifier le format.

    None = format non reconnu → afficher une erreur à l'utilisateur.
    """
    return next((c for c in CONNECTORS if c.matches_file(filepath)), None)


def resolve_accounts(
    connector: BaseConnector,
    filepath: Path,
    forced_account_id: int | None = None,
    user=None,
) -> list[AccountMatch]:
    """
    Retourne la liste des comptes DB associés au fichier.

    Paramètre optionnel forced_account_id :
        Quand l'utilisateur a sélectionné manuellement un compte (via le picker
        AccountAmbiguous), la vue passe l'ID ici pour court-circuiter la résolution
        automatique. Utilisé par Yuh uniquement pour l'instant.

    Paramètre optionnel user :
        Si fourni, tous les lookups Account sont filtrés par members=user.
        Cela garantit qu'un user ne peut résoudre que ses propres comptes,
        même s'il connaît un account_id ou un IBAN appartenant à un autre user.
        Toujours passer request.user depuis les vues.

    Lève :
        AccountNotFound    : identifiant présent dans le fichier mais inconnu en DB
        AccountAmbiguous   : banque reconnue, pas d'identifiant dans le fichier,
                             plusieurs comptes actifs → picker requis
        ValueError         : format inattendu (IBAN introuvable dans le fichier UBS...)

    Yuh  → 1 AccountMatch (convention ou forced_account_id)
    UBS  → 1 AccountMatch (Account.iban extrait de la ligne 2 du fichier)
    CIC  → N AccountMatch (1 par feuille, RIB dans header de chaque sheet)
    """
    # Scope de base : comptes actifs, filtrés par user si fourni.
    # Account.objects.for_user(None) retourne tous les comptes (usage CLI).
    # Account.objects.for_user(request.user) restreint aux comptes dont l'user est membre.
    base_qs = Account.objects.for_user(user).filter(is_active=True)

    if isinstance(connector, YuhConnector):
        # Yuh n'expose aucun identifiant dans le fichier.
        # Si forced_account_id est fourni (l'utilisateur a choisi via le picker),
        # on retourne directement ce compte sans chercher en DB.
        if forced_account_id is not None:
            try:
                account = base_qs.get(
                    pk=forced_account_id,
                    institution__slug="yuh",
                )
                return [AccountMatch(account=account)]
            except Account.DoesNotExist:
                raise AccountNotFound(
                    contract_number="",
                    contract_number_raw="",
                    bank_slug="yuh",
                )

        # Sans forced_account_id : chercher les comptes Yuh actifs (scopés à l'user).
        accounts = list(
            base_qs.filter(institution__slug="yuh")
            .select_related("institution")
            .order_by("name")
        )
        if not accounts:
            raise AccountNotFound(
                contract_number="",
                contract_number_raw="",
                bank_slug="yuh",
            )
        if len(accounts) == 1:
            # Convention : un seul compte Yuh actif → résolution automatique
            return [AccountMatch(account=accounts[0])]
        # Plusieurs comptes Yuh → l'utilisateur doit choisir
        raise AccountAmbiguous(accounts=accounts, bank_slug="yuh")

    elif isinstance(connector, UBSConnector):
        # UBS encode l'IBAN en ligne 2 du fichier (checking ET savings).
        # Matching direct sur Account.iban — pas besoin de connaître le sous-type.
        # C'est pour ça que Account.iban existe : CheckingAccount.iban ne couvrait
        # pas les comptes épargne, qui ont aussi un IBAN dans leurs exports UBS.
        identifier = connector.extract_account_identifier(filepath)
        if not identifier:
            raise ValueError(
                "Impossible d'extraire l'IBAN du fichier UBS (attendu en ligne 2). "
                "Le fichier est peut-être corrompu."
            )
        try:
            account = base_qs.select_related("institution").get(
                iban=identifier,
                institution__slug="ubs",
            )
        except Account.DoesNotExist:
            raise AccountNotFound(
                contract_number=identifier,
                contract_number_raw=identifier,
                bank_slug="ubs",
                account_name_hint=connector.extract_account_name(filepath),
            )
        return [AccountMatch(account=account)]

    elif isinstance(connector, CICConnector):
        # CIC = fichier multi-feuilles, 1 feuille par compte.
        # get_account_sheets() retourne [{sheet_name, rib, rib_raw, balance}, ...]
        sheets = connector.get_account_sheets(filepath)
        matches = []
        for sheet in sheets:
            rib = sheet["rib"]  # RIB normalisé sans espaces
            try:
                account = base_qs.get(
                    institution__slug="cic",
                    contract_number=rib,
                )
            except Account.DoesNotExist:
                raise AccountNotFound(
                    contract_number=rib,
                    contract_number_raw=sheet["rib_raw"],
                    bank_slug="cic",
                    sheet_name=sheet["sheet_name"],
                )
            matches.append(
                AccountMatch(
                    account=account,
                    sheet_name=sheet["sheet_name"],
                    parse_kwargs={"sheet_name": sheet["sheet_name"]},
                )
            )
        return matches

    raise ValueError(
        f"Connecteur non supporté par resolve_accounts : {type(connector).__name__}"
    )
