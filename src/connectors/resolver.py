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
2. Créer la spécialisation : CheckingAccount (BIC ; IBAN sur Account.iban) ou SavingsAccount
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
        institution_slug    : slug de l'institution détectée (ex: "cic", "ubs")
        sheet_name          : nom de la feuille CIC, ou None pour les autres institutions
        account_name_hint   : suggestion de nom pré-remplie dans le formulaire de création
    """

    def __init__(
        self,
        contract_number,
        contract_number_raw,
        institution_slug,
        sheet_name=None,
        account_name_hint=None,
    ):
        self.contract_number = contract_number
        self.contract_number_raw = contract_number_raw
        self.institution_slug = institution_slug
        self.sheet_name = sheet_name
        self.account_name_hint = account_name_hint
        super().__init__(
            f"Aucun compte trouvé pour le RIB/IBAN '{contract_number_raw}' "
            f"(institution : {institution_slug}). Configurez ce compte dans l'admin Django."
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
        accounts         : liste des Account candidats (déjà filtrés institution + is_active)
        institution_slug : slug de l'institution (ex: "yuh")
    """

    def __init__(self, accounts: list[Account], institution_slug: str):
        self.accounts = accounts
        self.institution_slug = institution_slug
        super().__init__(
            f"{len(accounts)} comptes trouvés pour l'institution '{institution_slug}'. "
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

    Résolution data-driven (plus de isinstance) — chaque connecteur déclare sa stratégie :
    Yuh  → IDENTITY_FIELD=None  → picker manuel obligatoire (AccountAmbiguous)
    UBS  → IDENTITY_FIELD=iban  → 1 identité → 1 AccountMatch
    CIC  → IDENTITY_FIELD=contract_number → N identités (feuilles) → N AccountMatch
    """
    # Scope de base : comptes actifs, filtrés par user si fourni.
    # Account.objects.for_user(None) retourne tous les comptes (usage CLI).
    # Account.objects.for_user(request.user) restreint aux comptes dont l'user est membre.
    base_qs = Account.objects.for_user(user).filter(is_active=True)
    slug = connector.INSTITUTION_SLUG
    field = connector.IDENTITY_FIELD

    # ── Soupape générique : compte choisi manuellement (picker Yuh, no-match, ou
    # correction d'un match) → court-circuite la résolution. Choix cross-institution
    # autorisé (picker groupé sur TOUS les comptes de l'user) → on ne filtre PAS par
    # slug. IDOR fermé par for_user : l'user ne peut forcer que SES propres comptes.
    if forced_account_id is not None:
        account = (
            base_qs.select_related("institution").filter(pk=forced_account_id).first()
        )
        if account is None:
            raise AccountNotFound(
                contract_number="", contract_number_raw="", institution_slug=slug
            )
        return [AccountMatch(account=account)]

    identities = connector.list_account_identities(filepath)

    # ── Pas d'identité dans le fichier (Yuh) → choix manuel OBLIGATOIRE.
    # Même avec un seul compte : on ne devine plus (plus d'auto-resolve à 1 compte).
    if not identities:
        accounts = list(
            base_qs.filter(institution__slug=slug)
            .select_related("institution")
            .order_by("name")
        )
        if not accounts:
            raise AccountNotFound(
                contract_number="", contract_number_raw="", institution_slug=slug
            )
        raise AccountAmbiguous(accounts=accounts, institution_slug=slug)

    # ── Identité(s) dans le fichier → match exact sur Account.<field>.
    # Une seule identité inconnue bloque TOUT le fichier (CIC multi-feuilles).
    # Des identités non vides impliquent un IDENTITY_FIELD défini (contrat connecteur).
    # Garde explicite (pas un assert : strippé sous -O en prod) contre un connecteur
    # mal déclaré (IDENTITY_FIELD=None mais list_account_identities() non vide).
    if field is None:
        raise ValueError(
            f"Connecteur {type(connector).__name__} : identités présentes mais "
            "IDENTITY_FIELD non défini (incohérence de déclaration)."
        )
    matches = []
    for ident in identities:
        account = (
            base_qs.select_related("institution")
            .filter(institution__slug=slug, **{field: ident.identifier})
            .first()
        )
        if account is None:
            raise AccountNotFound(
                contract_number=ident.identifier,
                contract_number_raw=ident.identifier_raw,
                institution_slug=slug,
                sheet_name=ident.sheet_name,
                account_name_hint=ident.name_hint,
            )
        matches.append(
            AccountMatch(
                account=account,
                sheet_name=ident.sheet_name,
                parse_kwargs=(
                    {"sheet_name": ident.sheet_name} if ident.sheet_name else {}
                ),
            )
        )
    return matches
