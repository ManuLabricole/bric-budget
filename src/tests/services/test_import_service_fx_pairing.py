"""
tests/services/test_import_service_fx_pairing.py

Tests DB pour la résolution intelligente des conversions de devise (Yuh) :

A. amount_chf DOIT utiliser la devise de la TRANSACTION, pas celle du compte
   (bug réel : un compte Yuh "CHF" recevant des lignes EUR/USD/GBP ressortait
   avec amount_chf == amount, aucune conversion appliquée).

B. paired_leg_key (voir CONTRACT dans connectors/base.py) relie les 2 jambes
   d'une conversion via Transaction.paired_transaction, et force
   is_internal_transfer=True / is_ignored=True indépendamment de toute règle
   de catégorisation par mot-clé — robuste à un changement de libellé banque.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.services.conftest import make_file_hash, make_tx
from transactions.models import Transaction
from transactions.services import ImportService

# =============================================================================
# A. amount_chf — devise de la transaction, pas du compte
# =============================================================================


@pytest.mark.django_db
def test_amount_chf_uses_transaction_currency_not_account_currency(
    chf_account, user, unknown_category, income_category
):
    """
    Bug réel (Yuh multi-devises, compte 226 en prod) : un compte CHF recevant
    une ligne EUR doit convertir au taux EUR→CHF de CETTE ligne, pas traiter
    la ligne comme identité sous prétexte que account.currency == "CHF".

    Avant le fix : to_chf(amount, account.currency, date) → identité pour
    TOUTE ligne d'un compte CHF, quelle que soit sa devise réelle. Un débit
    de -100 EUR ressortait à amount_chf=-100.00 au lieu de ~-93.00.
    """
    tx = make_tx("chf_account_eur_line", amount=-100.0, currency="EUR")

    rate = Decimal("0.93")
    with patch("services.exchange_rates.get_exchange_rate", return_value=rate):
        result = ImportService().run(
            [tx], chf_account, user, "f.csv", make_file_hash("mixedcur1")
        )

    assert result.count_errors == 0, f"Errors: {result.error_detail}"
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.currency == "EUR"
    assert saved.amount == Decimal("-100.00")
    assert saved.amount_chf == Decimal("-93.00")  # PAS -100.00 (identité, l'ancien bug)


@pytest.mark.django_db
def test_amount_chf_still_identity_when_transaction_currency_is_chf(
    chf_account, user, unknown_category, income_category
):
    """Non-régression : une ligne CHF sur un compte CHF reste en identité (pas d'appel réseau)."""
    tx = make_tx("chf_account_chf_line", amount=-50.0, currency="CHF")

    with patch("services.exchange_rates.get_exchange_rate") as mock_rate:
        result = ImportService().run(
            [tx], chf_account, user, "f.csv", make_file_hash("mixedcur2")
        )

    assert result.count_errors == 0
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.amount_chf == Decimal("-50.00")
    mock_rate.assert_not_called()  # identité CHF→CHF ne doit jamais taper l'API/DB taux


# =============================================================================
# B. paired_leg_key — appariement + flags virement interne
# =============================================================================


@pytest.mark.django_db
def test_paired_leg_key_links_transactions_and_flags_internal_transfer(
    chf_account, user, unknown_category, income_category
):
    """
    2 TransactionDict partageant paired_leg_key (2 jambes d'UNE conversion
    Yuh) → reliées via Transaction.paired_transaction, et is_internal_transfer
    + is_ignored forcés à True sur les DEUX, sans dépendre d'une catégorie
    matchée par mot-clé.
    """
    debit_leg = make_tx(
        "fx_debit", amount=-8.30, currency="CHF", paired_leg_key="grp-eur-1"
    )
    credit_leg = make_tx(
        "fx_credit", amount=8.90, currency="EUR", paired_leg_key="grp-eur-1"
    )

    with patch(
        "services.exchange_rates.get_exchange_rate", return_value=Decimal("0.93")
    ):
        result = ImportService().run(
            [debit_leg, credit_leg],
            chf_account,
            user,
            "f.csv",
            make_file_hash("pair1"),
        )

    assert result.count_errors == 0, f"Errors: {result.error_detail}"
    assert result.count_created == 2

    debit_saved = Transaction.objects.get(import_hash=debit_leg["import_hash"])
    credit_saved = Transaction.objects.get(import_hash=credit_leg["import_hash"])

    assert debit_saved.is_internal_transfer is True
    assert debit_saved.is_ignored is True
    assert credit_saved.is_internal_transfer is True
    assert credit_saved.is_ignored is True
    assert debit_saved.paired_transaction_id == credit_saved.pk
    assert credit_saved.paired_transaction_id == debit_saved.pk


@pytest.mark.django_db
def test_unrelated_paired_leg_keys_are_not_cross_linked(
    chf_account, user, unknown_category, income_category
):
    """2 groupes distincts dans le même import → chaque paire reliée à SA jumelle, jamais croisée."""
    grp1_debit = make_tx("g1d", amount=-8.30, currency="CHF", paired_leg_key="grp1")
    grp1_credit = make_tx("g1c", amount=8.90, currency="EUR", paired_leg_key="grp1")
    grp2_debit = make_tx("g2d", amount=-11.82, currency="CHF", paired_leg_key="grp2")
    grp2_credit = make_tx("g2c", amount=14.99, currency="USD", paired_leg_key="grp2")

    with patch(
        "services.exchange_rates.get_exchange_rate", return_value=Decimal("1.0")
    ):
        result = ImportService().run(
            [grp1_debit, grp1_credit, grp2_debit, grp2_credit],
            chf_account,
            user,
            "f.csv",
            make_file_hash("pair3"),
        )

    assert result.count_errors == 0
    assert result.count_created == 4

    g1d = Transaction.objects.get(import_hash=grp1_debit["import_hash"])
    g1c = Transaction.objects.get(import_hash=grp1_credit["import_hash"])
    g2d = Transaction.objects.get(import_hash=grp2_debit["import_hash"])
    g2c = Transaction.objects.get(import_hash=grp2_credit["import_hash"])

    assert g1d.paired_transaction_id == g1c.pk
    assert g2d.paired_transaction_id == g2c.pk
    assert g1d.paired_transaction_id != g2d.pk
    assert g1d.paired_transaction_id != g2c.pk


@pytest.mark.django_db
def test_orphan_paired_leg_key_does_not_crash_import(
    chf_account, user, unknown_category, income_category
):
    """
    Une seule jambe porte une paired_leg_key donnée (l'autre a déjà été
    importée précédemment, ou dédupliquée) → l'import ne plante PAS, la
    transaction reste créée seule, sans paired_transaction.

    Le flag is_internal_transfer reste True : une jambe SAIT déjà qu'elle
    n'est pas une dépense réelle, même sans jumelle trouvée en DB.
    """
    lone_leg = make_tx(
        "fx_lone", amount=-8.30, currency="CHF", paired_leg_key="grp-orphan"
    )

    with patch(
        "services.exchange_rates.get_exchange_rate", return_value=Decimal("1.0")
    ):
        result = ImportService().run(
            [lone_leg], chf_account, user, "f.csv", make_file_hash("pair2")
        )

    assert result.count_errors == 0
    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=lone_leg["import_hash"])
    assert saved.paired_transaction is None
    assert saved.is_internal_transfer is True
    assert saved.is_ignored is True


@pytest.mark.django_db
def test_normal_transaction_without_paired_leg_key_is_untouched(
    chf_account, user, unknown_category, income_category
):
    """Non-régression : une transaction sans paired_leg_key garde son comportement normal."""
    tx = make_tx("normal_tx", amount=-25.40, currency="CHF")

    result = ImportService().run(
        [tx], chf_account, user, "f.csv", make_file_hash("normal1")
    )

    assert result.count_errors == 0
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.paired_transaction is None
    assert saved.is_internal_transfer is False
    assert saved.is_ignored is False
