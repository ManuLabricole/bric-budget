"""
tests/commands/test_account_resolution.py — Tests de résolution de compte.

Pourquoi tester _find_account() séparément ?
--------------------------------------------
C'est la seule logique "métier" dans les management commands. Tout le reste
(parsing, dédup, ImportService) est déjà testé ailleurs. _find_account() est
le seul endroit qui peut silencieusement retourner le mauvais compte — ou
planter avec un message obscur — si la DB n'est pas dans l'état attendu.

Ces deux fonctions couvrent deux stratégies différentes :
    - import_yuh._find_account()  : résolution par bank__slug + account_type
                                    (Yuh n'a pas d'IBAN dans ses exports)
    - import_ubs._find_account()  : résolution par IBAN (extrait du fichier CSV)

On instancie Command() directement et on appelle _find_account() — pas besoin
de call_command() qui nécessiterait un vrai fichier et un superuser.

Comportements testés :
    Yuh  1. Aucun compte Yuh actif → CommandError explicite
    Yuh  2. 1 compte Yuh actif     → retourné sans erreur
    Yuh  3. 2 comptes Yuh actifs   → CommandError (ambiguïté)
    UBS  4. Aucun IBAN dans le CSV → CommandError
    UBS  5. IBAN présent mais absent de la DB → CommandError
    UBS  6. IBAN présent et compte trouvé    → retourné sans erreur
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError

from accounts.models import Account, Bank

FIXTURES_DIR = Path(__file__).parent.parent / "connectors" / "fixtures"
UBS_CSV = FIXTURES_DIR / "ubs_sample.csv"


# =============================================================================
# Helpers — création d'objets Bank + Account en DB
# =============================================================================


@pytest.fixture
def yuh_bank(db):
    """Banque Yuh — le slug 'yuh' est la clé utilisée par _find_account()."""
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
# 1–3. import_yuh._find_account()
# =============================================================================


@pytest.mark.django_db
def test_yuh_find_account_raises_when_no_account(yuh_bank):
    """
    Aucun compte Yuh checking actif en DB → CommandError.

    Scénario : première utilisation de l'app, make seed n'a pas encore été lancé.
    Sans cette garde, l'import s'exécuterait et créerait des transactions
    sans account_id → IntegrityError cryptique en fin de run.
    """
    from transactions.management.commands.import_yuh import Command

    cmd = Command()
    with pytest.raises(CommandError, match="No active Yuh checking account"):
        cmd._find_account()


@pytest.mark.django_db
def test_yuh_find_account_returns_single_active_account(yuh_bank):
    """
    1 compte Yuh actif en DB → retourné directement.

    C'est le cas nominal : make seed crée exactement un compte Yuh.
    """
    from transactions.management.commands.import_yuh import Command

    account = make_yuh_account(yuh_bank)
    cmd = Command()
    result = cmd._find_account()

    assert result.pk == account.pk


@pytest.mark.django_db
def test_yuh_find_account_raises_when_multiple_accounts(yuh_bank):
    """
    2+ comptes Yuh checking actifs → CommandError avec message explicite.

    Scénario : doublon accidentel en DB (make seed lancé deux fois, ou
    un compte recréé sans désactiver l'ancien). Sans cette garde, l'import
    affecterait les transactions au premier compte retourné par l'ORM —
    non déterministe selon l'ordre d'insertion.
    """
    from transactions.management.commands.import_yuh import Command

    make_yuh_account(yuh_bank, name="Yuh CHF #1")
    make_yuh_account(yuh_bank, name="Yuh CHF #2")

    cmd = Command()
    with pytest.raises(CommandError, match="Multiple active Yuh checking accounts"):
        cmd._find_account()


@pytest.mark.django_db
def test_yuh_find_account_ignores_inactive_account(yuh_bank):
    """
    Un compte Yuh inactif (is_active=False) ne doit pas être retourné.

    Scénario : compte fermé, marqué inactif dans l'admin. Il ne doit pas
    faire planter l'import ni y être affecté.
    """
    from transactions.management.commands.import_yuh import Command

    make_yuh_account(yuh_bank, name="Yuh CHF Old", is_active=False)

    cmd = Command()
    with pytest.raises(CommandError, match="No active Yuh checking account"):
        cmd._find_account()


# =============================================================================
# 4–6. import_ubs._find_account()
# =============================================================================


@pytest.mark.django_db
def test_ubs_find_account_raises_when_no_iban_in_file(ubs_bank):
    """
    extract_account_identifier() retourne None → CommandError.

    Scénario : fichier CSV corrompu ou format non standard (UBS modifie parfois
    le layout de leurs exports entre versions). Sans IBAN on ne peut pas
    identifier le compte — mieux vaut planter proprement que silencieusement.
    """
    from connectors.ubs.parser import UBSConnector
    from transactions.management.commands.import_ubs import Command

    cmd = Command()
    connector = UBSConnector()

    with patch.object(connector, "extract_account_identifier", return_value=None):
        with pytest.raises(CommandError, match="Could not extract account identifier"):
            cmd._find_account(connector, UBS_CSV)


@pytest.mark.django_db
def test_ubs_find_account_raises_when_iban_not_in_db(ubs_bank):
    """
    IBAN extrait du fichier mais aucun Account avec ce contract_number → CommandError.

    Scénario nominal d'erreur d'onboarding : le compte a été créé en DB mais
    Account.contract_number n'a pas été renseigné (champ optionnel dans le modèle).
    Le message d'erreur doit indiquer l'IBAN exact pour guider la correction.
    """
    from connectors.ubs.parser import UBSConnector
    from transactions.management.commands.import_ubs import Command

    # L'IBAN du fixture normalisé — aucun compte avec ce contract_number en DB
    cmd = Command()
    connector = UBSConnector()

    with pytest.raises(CommandError, match="No account with contract_number"):
        cmd._find_account(connector, UBS_CSV)


@pytest.mark.django_db
def test_ubs_find_account_returns_account_matching_iban(ubs_bank):
    """
    IBAN extrait + compte avec ce contract_number en DB → compte retourné.

    L'IBAN dans ubs_sample.csv est 'CH00 0000 0000 0000 0000 0'.
    UBSConnector.extract_account_identifier() normalise → 'CH0000000000000000000'.
    On crée un compte avec ce contract_number exact.
    """
    from connectors.ubs.parser import UBSConnector
    from transactions.management.commands.import_ubs import Command

    account = Account.objects.create(
        bank=ubs_bank,
        name="UBS CHF",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        contract_number="CH0000000000000000000",  # IBAN normalisé du fixture
    )

    cmd = Command()
    connector = UBSConnector()
    result = cmd._find_account(connector, UBS_CSV)

    assert result.pk == account.pk
