"""
accounts/seed_config.py — lecture et validation du fichier de seed des comptes.

Rôle
----
Transformer le JSON de `assets/private/accounts.json` en objets typés et validés,
SANS toucher à la base. Séparé de la commande de management pour être testable
sans DB — même découpage que `connectors/` (parsing pur d'un côté, orchestration
et écriture de l'autre).

Pourquoi un fichier plutôt que le wizard interactif d'avant
-----------------------------------------------------------
L'ancien `seed_accounts` posait ses questions en `getpass` : rien sur le disque,
mais rien de REJOUABLE non plus. Reseeder après un `make restore` imposait de
ressaisir chaque IBAN à la main. Le fichier rend l'opération idempotente et
reproductible — c'est ce qu'on attend d'un seed.

⛔ SR-008 — le fichier porte des IBAN/RIB réels
-----------------------------------------------
Il vit sous `assets/private/`, couvert par `.gitignore`, et son chemin passe par
`settings.SEED_ACCOUNTS_FILE` (donc `config()`/.env) : AUCUN identifiant, ni même
un nom de fichier personnel, n'apparaît dans le code. Le schéma est documenté par
`assets/accounts.example.json`, committé avec des valeurs bidon.

Clés inconnues = erreur
-----------------------
Une clé mal orthographiée (« ibna ») silencieusement ignorée produirait un compte
sans identité d'import, découvert des semaines plus tard devant un import qui
échoue. On refuse net, en nommant la clé fautive et les clés attendues.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Types de comptes acceptés par ce seed. Volontairement restreint à ce que les
# connecteurs savent importer aujourd'hui : ouvrir aux pensions/assurances sans
# parser derrière créerait des comptes que rien ne peut alimenter.
SUPPORTED_TYPES = ("checking", "savings")

SUPPORTED_CURRENCIES = ("CHF", "EUR", "GBP", "USD")

# Clés reconnues dans une entrée de compte. Les clés commençant par "_" sont des
# commentaires libres (convention du fichier) et sont ignorées silencieusement.
ACCOUNT_KEYS = frozenset(
    {
        "institution",
        "name",
        "type",
        "currency",
        "iban",
        "contract_number",
        "bic",
        "interest_rate",
        "account_reference",
        "is_active",
    }
)

TOP_LEVEL_KEYS = frozenset({"user_email", "accounts"})


class SeedConfigError(ValueError):
    """Fichier de seed invalide. Le message est destiné à l'utilisateur final."""


@dataclass(frozen=True)
class AccountSpec:
    """
    Un compte à seeder, validé et casté. Immuable (aucune mutation en aval).

    `iban` vaut None (pas "") quand il est absent : `Account.iban` est unique et
    nullable — deux comptes à chaîne vide violeraient la contrainte, alors que
    deux NULL cohabitent.
    """

    institution: str
    name: str
    account_type: str
    currency: str
    iban: str | None
    contract_number: str
    bic: str
    interest_rate: Decimal | None
    account_reference: str
    is_active: bool

    @property
    def has_identity(self) -> bool:
        """
        Un compte sans IBAN ni n° de contrat ne pourra JAMAIS recevoir d'import.

        `create_account()` refuse déjà ce cas ; on l'expose ici pour que la
        commande puisse IGNORER une entrée encore vide (le fichier se remplit au
        fil des banques) plutôt que de faire échouer tout le seed.
        """
        return bool(self.iban or self.contract_number)


@dataclass(frozen=True)
class SeedConfig:
    """Contenu validé du fichier de seed."""

    user_email: str
    accounts: tuple[AccountSpec, ...]


def _require_str(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SeedConfigError(f"{where} : champ « {key} » manquant ou vide.")
    return value.strip()


def _optional_str(entry: dict, key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _parse_rate(entry: dict, where: str) -> Decimal | None:
    """
    Taux d'intérêt en Decimal — SR-002 : `Decimal(str(x))`, jamais `Decimal(float)`.

    `Decimal(3.0)` vaut 3.000000000000000444089209850062616169452667236328125 ;
    sur un taux ça se voit peu, mais la règle est absolue dans ce projet et les
    exceptions sont ce qui la fait mourir.
    """
    raw = entry.get("interest_rate")
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise SeedConfigError(
            f"{where} : « interest_rate » n'est pas un nombre ({raw!r})."
        ) from exc


def _parse_account(entry: dict, index: int) -> AccountSpec:
    where = f"Compte #{index + 1}"
    if not isinstance(entry, dict):
        raise SeedConfigError(f"{where} : attendu un objet JSON.")

    # Nommer le compte dès que possible rend tous les messages suivants utiles.
    name = _require_str(entry, "name", where)
    where = f"Compte « {name} »"

    unknown = {k for k in entry if not k.startswith("_")} - ACCOUNT_KEYS
    if unknown:
        raise SeedConfigError(
            f"{where} : clé(s) inconnue(s) {sorted(unknown)}. "
            f"Attendu : {sorted(ACCOUNT_KEYS)} (les clés « _… » sont des commentaires)."
        )

    account_type = _require_str(entry, "type", where)
    if account_type not in SUPPORTED_TYPES:
        raise SeedConfigError(
            f"{where} : type « {account_type} » non supporté. "
            f"Attendu : {list(SUPPORTED_TYPES)}."
        )

    currency = _require_str(entry, "currency", where).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise SeedConfigError(
            f"{where} : devise « {currency} » inconnue. "
            f"Attendu : {list(SUPPORTED_CURRENCIES)}."
        )

    is_active = entry.get("is_active", True)
    if not isinstance(is_active, bool):
        raise SeedConfigError(
            f"{where} : « is_active » doit être true ou false ({is_active!r})."
        )

    # Espaces retirés : les banques écrivent l'IBAN par groupes de 4 pour la
    # lisibilité ("CH00 0000 …"), les connecteurs le normalisent sans espaces
    # avant de matcher. Les deux côtés doivent employer la même forme.
    iban = _optional_str(entry, "iban").replace(" ", "").upper()
    contract_number = _optional_str(entry, "contract_number").replace(" ", "")

    return AccountSpec(
        institution=_require_str(entry, "institution", where),
        name=name,
        account_type=account_type,
        currency=currency,
        iban=iban or None,  # "" → None : Account.iban est unique ET nullable
        contract_number=contract_number,
        bic=_optional_str(entry, "bic").upper(),
        interest_rate=_parse_rate(entry, where),
        account_reference=_optional_str(entry, "account_reference"),
        is_active=is_active,
    )


def load_seed_config(path: Path) -> SeedConfig:
    """
    Lit et valide le fichier de seed. Lève SeedConfigError avec un message lisible.

    Tout est validé AVANT que la commande n'écrive quoi que ce soit : un fichier
    à moitié bon ne doit pas produire une base à moitié seedée.
    """
    if not path.exists():
        raise SeedConfigError(
            f"Fichier de seed introuvable : {path}\n"
            "Copie assets/accounts.example.json vers ce chemin et renseigne tes comptes "
            "(le dossier assets/private/ est gitignoré)."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedConfigError(
            f"{path} n'est pas un JSON valide — ligne {exc.lineno}, colonne "
            f"{exc.colno} : {exc.msg}"
        ) from exc

    if not isinstance(raw, dict):
        raise SeedConfigError(f"{path} : attendu un objet JSON à la racine.")

    unknown = {k for k in raw if not k.startswith("_")} - TOP_LEVEL_KEYS
    if unknown:
        raise SeedConfigError(
            f"{path} : clé(s) racine inconnue(s) {sorted(unknown)}. "
            f"Attendu : {sorted(TOP_LEVEL_KEYS)}."
        )

    user_email = _require_str(raw, "user_email", str(path))

    accounts = raw.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise SeedConfigError(f"{path} : « accounts » doit être une liste non vide.")

    specs = tuple(_parse_account(entry, i) for i, entry in enumerate(accounts))

    # Doublons d'identité DANS le fichier : deux entrées au même IBAN produiraient
    # une IntegrityError au milieu de l'écriture (Account.iban est unique). Mieux
    # vaut le dire ici, en nommant les deux comptes.
    _reject_duplicate_identities(specs, path)

    return SeedConfig(user_email=user_email, accounts=specs)


def _reject_duplicate_identities(specs: tuple[AccountSpec, ...], path: Path) -> None:
    """Refuse deux comptes partageant un IBAN, ou un (institution, n° de contrat)."""
    seen_iban: dict[str, str] = {}
    seen_contract: dict[tuple[str, str], str] = {}

    for spec in specs:
        if spec.iban:
            previous = seen_iban.get(spec.iban)
            if previous:
                raise SeedConfigError(
                    f"{path} : « {previous} » et « {spec.name} » ont le même IBAN. "
                    "Un IBAN identifie un seul compte."
                )
            seen_iban[spec.iban] = spec.name

        if spec.contract_number:
            key = (spec.institution, spec.contract_number)
            previous = seen_contract.get(key)
            if previous:
                raise SeedConfigError(
                    f"{path} : « {previous} » et « {spec.name} » ont le même n° de "
                    f"contrat chez « {spec.institution} »."
                )
            seen_contract[key] = spec.name
