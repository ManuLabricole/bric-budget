"""
tests/commands/test_account_resolution.py — Tests de résolution de compte.

Pourquoi tester resolve_accounts() ?
-------------------------------------
C'est la logique qui peut silencieusement retourner le mauvais compte — ou planter
avec un message obscur — si la DB n'est pas dans l'état attendu.

Avant le resolver (Phase 2E), cette logique était dans _find_account() de chaque
commande de management. Elle est maintenant centralisée dans connectors/resolver.py
et testée ici directement, sans passer par les commandes.

Comportements testés :
    Yuh  1. Aucun compte Yuh actif → AccountNotFound
    Yuh  2. 1 compte Yuh actif     → AccountMatch retourné
    Yuh  3. 2 comptes Yuh actifs   → AccountMatch du plus récent (first() — pas d'erreur)
    Yuh  4. Compte inactif         → AccountNotFound (ignoré par le filtre)
    UBS  5. IBAN absent du fichier → ValueError
    UBS  6. IBAN présent mais pas en DB → AccountNotFound
    UBS  7. IBAN présent et compte trouvé → AccountMatch retourné
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from accounts.models import Account, Bank, CheckingAccount
from connectors.resolver import AccountMatch, AccountNotFound, resolve_accounts
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector

FIXTURES_DIR = Path(__file__).parent.parent / "connectors" / "fixtures"
UBS_CSV = FIXTURES_DIR / "ubs_sample.csv"

# Fichier factice pour Yuh — resolve_accounts(YuhConnector) n'ouvre pas le fichier
YUH_DUMMY = Path("/dev/null")


# =============================================================================
# Helpers — création d'objets Bank + Account en DB
# =============================================================================


@pytest.fixture
def yuh_bank(db):
    """Banque Yuh — le slug 'yuh' est la clé utilisée par resolve_accounts()."""
    return Bank.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )


@pytest.fixture
def ubs_bank(db):
    """Banque UBS — le contract_number (IBAN normalisé) est la clé."""
    return Bank.objects.create(
        name="UBS", slug="ubs", country="CH", default_currency="CHF"
    )


def make_yuh_account(bank, name="Yuh CHF", is_active=True) -> Account:
    """Crée un compte Yuh checking, actif par défaut."""
    return Account.objects.create(
        bank=bank,
        name=name,
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_active=is_active,
    )


# =============================================================================
# 1–4. Yuh — résolution par convention bank slug
# =============================================================================


@pytest.mark.django_db
def test_yuh_raises_when_no_account(yuh_bank):
    """
    Aucun compte Yuh checking actif en DB → AccountNotFound.

    Scénario : première utilisation de l'app, make seed n'a pas encore été lancé.
    """
    connector = YuhConnector()
    with pytest.raises(AccountNotFound):
        resolve_accounts(connector, YUH_DUMMY)


@pytest.mark.django_db
def test_yuh_returns_single_active_account(yuh_bank):
    """
    1 compte Yuh actif en DB → AccountMatch avec le bon account.

    C'est le cas nominal : make seed crée exactement un compte Yuh.
    """
    account = make_yuh_account(yuh_bank)
    connector = YuhConnector()
    matches = resolve_accounts(connector, YUH_DUMMY)

    assert len(matches) == 1
    assert isinstance(matches[0], AccountMatch)
    assert matches[0].account.pk == account.pk
    assert matches[0].sheet_name is None
    assert matches[0].parse_kwargs == {}


@pytest.mark.django_db
def test_yuh_returns_most_recent_when_multiple_accounts(yuh_bank):
    """
    2+ comptes Yuh checking actifs → AccountMatch du plus récent (order_by -id).

    Scénario : doublon accidentel en DB. On prend silencieusement le plus récent
    au lieu de crasher — l'admin peut désactiver le doublon manuellement.
    """
    make_yuh_account(yuh_bank, name="Yuh CHF #1")
    account2 = make_yuh_account(yuh_bank, name="Yuh CHF #2")

    connector = YuhConnector()
    matches = resolve_accounts(connector, YUH_DUMMY)

    assert len(matches) == 1
    assert matches[0].account.pk == account2.pk


@pytest.mark.django_db
def test_yuh_ignores_inactive_account(yuh_bank):
    """
    Compte Yuh inactif (is_active=False) → ignoré → AccountNotFound.

    Scénario : compte fermé, marqué inactif dans l'admin.
    """
    make_yuh_account(yuh_bank, name="Yuh CHF Old", is_active=False)

    connector = YuhConnector()
    with pytest.raises(AccountNotFound):
        resolve_accounts(connector, YUH_DUMMY)


# =============================================================================
# 5–7. UBS — résolution par IBAN (contract_number)
# =============================================================================


@pytest.mark.django_db
def test_ubs_raises_when_no_iban_in_file(ubs_bank):
    """
    extract_account_identifier() retourne None → ValueError.

    Scénario : fichier CSV corrompu ou format non standard.
    """
    connector = UBSConnector()

    with patch.object(connector, "extract_account_identifier", return_value=None):
        with pytest.raises(ValueError, match="IBAN"):
            resolve_accounts(connector, UBS_CSV)


@pytest.mark.django_db
def test_ubs_raises_when_iban_not_in_db(ubs_bank):
    """
    IBAN extrait du fichier mais aucun CheckingAccount avec cet IBAN → AccountNotFound.

    Scénario d'onboarding : le compte a été créé en DB mais CheckingAccount.iban
    n'a pas été renseigné.
    """
    connector = UBSConnector()

    with pytest.raises(AccountNotFound):
        resolve_accounts(connector, UBS_CSV)


@pytest.mark.django_db
def test_ubs_returns_account_matching_iban(ubs_bank):
    """
    IBAN extrait + CheckingAccount avec cet IBAN en DB → AccountMatch retourné.

    L'IBAN dans ubs_sample.csv est 'CH00 0000 0000 0000 0000 0'.
    UBSConnector.extract_account_identifier() normalise → 'CH0000000000000000000'.
    Le resolver cherche dans CheckingAccount.iban (pas Account.contract_number).
    """
    account = Account.objects.create(
        bank=ubs_bank,
        name="UBS CHF",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_active=True,
    )
    CheckingAccount.objects.create(
        account=account,
        iban="CH0000000000000000000",  # IBAN normalisé du fixture
        bic="UBSWCHZH80A",
    )

    connector = UBSConnector()
    matches = resolve_accounts(connector, UBS_CSV)

    assert len(matches) == 1
    assert isinstance(matches[0], AccountMatch)
    assert matches[0].account.pk == account.pk
    assert matches[0].sheet_name is None
    assert matches[0].parse_kwargs == {}
