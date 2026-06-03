"""
tests/integration/test_import_integration.py — Chaîne complète : fichier → DB.

Pourquoi des tests d'intégration en plus des tests unitaires ?
--------------------------------------------------------------
Les tests unitaires vérifient que le parser retourne les bons dicts,
et que l'ImportService écrit les bons objets. Mais ils ne testent pas
la COMBINAISON des deux : une régression à la frontière (ex: ImportService
attend un champ que le parser n'envoie plus) serait invisible avec des tests
unitaires seuls.

Ces tests font tourner la vraie chaîne :
    fichier fixture CSV/Excel → YuhConnector.parse() → ImportService.run() → DB

On utilise les mêmes fixtures CSV que les tests connecteurs.
On ne mocke rien sauf get_exchange_rate (pour éviter les appels réseau).

Comportements testés :
    1. Import Yuh complet      : 4 transactions en DB, balance snapshot créé
    2. Import UBS complet      : 3 transactions en DB, balance snapshot créé
    3. Import CIC complet      : 5 transactions en DB (2 sheets × 3+2)
    4. Double import Yuh       : 2ème import → 0 créé, 4 skipped (dédup row-level)
    5. Double import même file : même file_hash → count_errors=1 (dédup file-level)
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from accounts.models import Account, BalanceSnapshot, Institution
from connectors.cic.parser import CICConnector
from connectors.ubs.parser import UBSConnector
from connectors.yuh.parser import YuhConnector
from transactions.models import Transaction
from transactions.services import ImportService, compute_file_hash

FIXTURES_DIR = Path(__file__).parent.parent / "connectors" / "fixtures"
YUH_CSV = FIXTURES_DIR / "yuh_sample.csv"
UBS_CSV = FIXTURES_DIR / "ubs_sample.csv"


# =============================================================================
# Fixtures DB — comptes adaptés aux fichiers de test
# =============================================================================


@pytest.fixture
def yuh_account(db):
    """Compte Yuh CHF — correspond au format de yuh_sample.csv."""
    bank = Institution.objects.create(
        name="Yuh Integration",
        slug="yuh-integration",
        country="CH",
        default_currency="CHF",
    )
    return Account.objects.create(
        institution=bank,
        name="Yuh CHF",
        account_type="checking",
        currency="CHF",
    )


@pytest.fixture
def ubs_account(db):
    """
    Compte UBS CHF — contract_number = IBAN normalisé de ubs_sample.csv.
    L'IBAN du fixture est "CH00 0000 0000 0000 0000 0" → normalisé = "CH0000000000000000000".
    """
    bank = Institution.objects.create(
        name="UBS Integration",
        slug="ubs-integration",
        country="CH",
        default_currency="CHF",
    )
    return Account.objects.create(
        institution=bank,
        name="UBS CHF",
        account_type="checking",
        currency="CHF",
        contract_number="CH0000000000000000000",
    )


@pytest.fixture
def cic_account_cc(db):
    """Compte CIC C/C EUR — pour la feuille 'Cpt CC'."""
    bank = Institution.objects.create(
        name="CIC Integration",
        slug="cic-integration",
        country="FR",
        default_currency="EUR",
    )
    return Account.objects.create(
        institution=bank,
        name="CIC C/C EUR",
        account_type="checking",
        currency="EUR",
    )


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email="integ@bricbudget.ch", password="test")


# =============================================================================
# 1. Import Yuh complet
# =============================================================================


@pytest.mark.django_db
def test_yuh_full_import_creates_correct_transaction_count(yuh_account, user):
    """
    Chaîne complète : yuh_sample.csv → 4 transactions en DB.

    Le fixture a 5 lignes dont 1 REWARD_RECEIVED skippée par le parser.
    4 transactions attendues.
    """
    connector = YuhConnector()
    transactions = connector.parse(YUH_CSV)
    file_hash = compute_file_hash(YUH_CSV)

    result = ImportService().run(
        transactions=transactions,
        account=yuh_account,
        imported_by=user,
        filename=YUH_CSV.name,
        file_hash=file_hash,
        balance=connector.extract_balance(YUH_CSV),
    )

    assert result.count_created == 4
    assert result.count_errors == 0
    assert Transaction.objects.filter(account=yuh_account).count() == 4


@pytest.mark.django_db
def test_yuh_full_import_transactions_have_amount_chf(yuh_account, user):
    """Toutes les transactions Yuh (CHF) ont amount_chf == amount."""
    connector = YuhConnector()
    transactions = connector.parse(YUH_CSV)
    file_hash = compute_file_hash(YUH_CSV)
    ImportService().run(
        transactions,
        yuh_account,
        user,
        YUH_CSV.name,
        file_hash,
    )

    for tx in Transaction.objects.filter(account=yuh_account):
        assert tx.amount_chf is not None, f"amount_chf is None for {tx.description_raw}"
        assert tx.amount_chf == tx.amount


@pytest.mark.django_db
def test_yuh_reimport_same_file_is_blocked(yuh_account, user):
    """
    Même fichier importé 2× → 2ème import bloqué au niveau file_hash.

    L'ImportLog stocke le file_hash (unique=True). La garde en début de run()
    détecte le doublon et retourne count_errors=1 sans rien écrire.
    """
    connector = YuhConnector()
    transactions = connector.parse(YUH_CSV)
    file_hash = compute_file_hash(YUH_CSV)

    ImportService().run(transactions, yuh_account, user, YUH_CSV.name, file_hash)
    result2 = ImportService().run(
        transactions, yuh_account, user, YUH_CSV.name, file_hash
    )

    assert result2.count_errors == 1
    assert result2.count_created == 0
    assert Transaction.objects.count() == 4  # pas de doublon


@pytest.mark.django_db
def test_yuh_reimport_different_file_skips_duplicate_rows(yuh_account, user):
    """
    Même transactions, file_hash différent (fichier re-exporté) → rows skippées.

    Scénario réel : on ré-exporte Yuh sur une période qui chevauche un import passé.
    Les import_hash identiques sont détectés → count_skipped=4.
    """
    connector = YuhConnector()
    transactions = connector.parse(YUH_CSV)

    # Premier import : crée 4 transactions
    ImportService().run(transactions, yuh_account, user, "file1.csv", "hash_aaa")

    # Deuxième import : même transactions, file_hash différent
    result2 = ImportService().run(
        transactions, yuh_account, user, "file2.csv", "hash_bbb"
    )

    assert result2.count_skipped == 4
    assert result2.count_created == 0
    assert Transaction.objects.count() == 4


# =============================================================================
# 2. Import UBS complet
# =============================================================================


@pytest.mark.django_db
def test_ubs_full_import_creates_correct_transaction_count(ubs_account, user):
    """Chaîne complète : ubs_sample.csv → 3 transactions en DB."""
    connector = UBSConnector()
    transactions = connector.parse(UBS_CSV)
    file_hash = compute_file_hash(UBS_CSV)

    result = ImportService().run(
        transactions=transactions,
        account=ubs_account,
        imported_by=user,
        filename=UBS_CSV.name,
        file_hash=file_hash,
        balance=connector.extract_balance(UBS_CSV),
    )

    assert result.count_created == 3
    assert result.count_errors == 0
    assert Transaction.objects.filter(account=ubs_account).count() == 3


@pytest.mark.django_db
def test_ubs_full_import_creates_balance_snapshot(ubs_account, user):
    """
    L'import UBS avec balance=12000.0 crée un BalanceSnapshot.

    Le solde est extrait du bloc metadata (ligne 6 du CSV UBS).
    BalanceSnapshot permet de tracer l'évolution du solde compte au fil des imports.
    """
    connector = UBSConnector()
    transactions = connector.parse(UBS_CSV)
    balance = connector.extract_balance(UBS_CSV)  # 12000.0 dans le fixture
    file_hash = compute_file_hash(UBS_CSV)

    ImportService().run(
        transactions, ubs_account, user, UBS_CSV.name, file_hash, balance=balance
    )

    snapshots = BalanceSnapshot.objects.filter(account=ubs_account)
    assert snapshots.count() == 1
    snap = snapshots.first()
    assert snap is not None
    assert snap.balance == Decimal("12000.0")


# =============================================================================
# 3. Import CIC complet (2 feuilles)
# =============================================================================


@pytest.mark.django_db
def test_cic_full_import_creates_correct_transaction_count(
    cic_file, cic_account_cc, user
):
    """
    Chaîne complète CIC : xlsx → 5 transactions en DB (3 CC + 2 Livret A via parse()).

    On utilise parse() qui agrège toutes les feuilles. En production on utilise
    parse_sheet() par feuille pour affecter chaque transaction au bon compte.
    Ici on simplifie en tout mettant sur cic_account_cc.
    """
    # get_exchange_rate mocké : évite appels réseau pour les tx EUR
    with patch(
        "transactions.services.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        connector = CICConnector()
        transactions = connector.parse(cic_file)
        file_hash = compute_file_hash(cic_file)

        result = ImportService().run(
            transactions=transactions,
            account=cic_account_cc,
            imported_by=user,
            filename="cic_export.xlsx",
            file_hash=file_hash,
        )

    assert result.count_created == 5
    assert result.count_errors == 0
    assert Transaction.objects.filter(account=cic_account_cc).count() == 5


@pytest.mark.django_db
def test_cic_transactions_have_amount_chf_from_exchange_rate(
    cic_file, cic_account_cc, user
):
    """
    Transactions EUR → amount_chf = amount × taux.
    On mocke le taux à 0.93 → amount_chf = amount × 0.93.
    """
    with patch(
        "transactions.services.get_exchange_rate",
        return_value=Decimal("0.93"),
    ):
        connector = CICConnector()
        transactions = connector.parse(cic_file)
        file_hash = compute_file_hash(cic_file)
        ImportService().run(
            transactions,
            cic_account_cc,
            user,
            "cic.xlsx",
            file_hash,
        )

    for tx in Transaction.objects.filter(account=cic_account_cc):
        assert tx.amount_chf is not None
        expected = (tx.amount * Decimal("0.93")).quantize(Decimal("0.01"))
        assert tx.amount_chf == expected
