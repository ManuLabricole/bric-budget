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
2. Créer la spécialisation : CheckingAccount (iban + bic) ou SavingsAccount
3. Renseigner Account.contract_number avec l'identifiant que le connecteur utilise :
   - UBS  → IBAN sans espaces (stocker via config() dans .env — jamais en clair)
   - CIC  → RIB sans espaces (stocker via config() dans .env — jamais en clair)
   - Yuh  → rien (convention : exactement 1 compte Yuh actif en DB)

Ajouter une nouvelle carte
--------------------------
1. Créer Card en DB — checking_account, user, last_four, card_type, is_active=True
2. C'est tout — le connecteur lit card_last_four et le service fait le matching
   automatiquement via un dict {last_four: Card} chargé en 1 seule query.
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
        contract_number : identifiant extrait du fichier (RIB/IBAN normalisé)
        contract_number_raw : identifiant brut tel qu'il apparaît dans le fichier
        bank_slug : slug de la banque détectée (ex: "cic", "ubs")
        sheet_name : nom de la feuille CIC, ou None pour les autres banques
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
        # Suggestion de nom pré-remplie dans le formulaire de création inline.
        # Peut être None si le connecteur ne peut pas l'extraire.
        self.account_name_hint = account_name_hint
        super().__init__(
            f"Aucun compte trouvé pour le RIB/IBAN '{contract_number_raw}' "
            f"(banque : {bank_slug}). Configurez ce compte dans l'admin Django."
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


def resolve_accounts(connector: BaseConnector, filepath: Path) -> list[AccountMatch]:
    """
    Retourne la liste des comptes DB associés au fichier.

    Lève Account.DoesNotExist ou Account.MultipleObjectsReturned si le compte
    n'est pas trouvé ou ambigu — le caller (commande ou vue) attrape et affiche.

    Yuh  → 1 AccountMatch (convention : 1 seul compte Yuh checking actif)
    UBS  → 1 AccountMatch (IBAN extrait du fichier → Account.contract_number)
    CIC  → N AccountMatch (1 par feuille, RIB dans header de chaque sheet)
    """
    if isinstance(connector, YuhConnector):
        # Yuh n'expose aucun identifiant dans le fichier.
        # Convention : prendre le premier compte Yuh checking actif en DB.
        # (S'il y en a plusieurs, on prend le plus récent — à affiner via admin.)
        account = (
            Account.objects.filter(
                bank__slug="yuh",
                account_type=Account.AccountType.CHECKING,
                is_active=True,
            )
            .order_by("-id")
            .first()
        )
        if account is None:
            raise AccountNotFound(
                contract_number="",
                contract_number_raw="",
                bank_slug="yuh",
            )
        return [AccountMatch(account=account)]

    elif isinstance(connector, UBSConnector):
        # UBS encode l'IBAN en ligne 2 du fichier.
        # Matching par CheckingAccount.iban (normalisé sans espaces).
        identifier = connector.extract_account_identifier(filepath)
        if not identifier:
            raise ValueError(
                "Impossible d'extraire l'IBAN du fichier UBS (attendu en ligne 2). "
                "Le fichier est peut-être corrompu."
            )
        from accounts.models import CheckingAccount

        try:
            ca = CheckingAccount.objects.select_related("account").get(
                iban=identifier,
                account__is_active=True,
            )
            account = ca.account
        except CheckingAccount.DoesNotExist:
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
                account = Account.objects.get(
                    bank__slug="cic",
                    contract_number=rib,
                    is_active=True,
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
