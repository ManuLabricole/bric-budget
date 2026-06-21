"""
tests/services/test_import_decimal_precision.py

Ce qu'on teste : la précision des montants Decimal tout au long de l'import.

Risque métier : un arrondi silencieux ou une perte de précision fausserait
les totaux budgétaires. 0.01 CHF d'écart × 1000 transactions = 10 CHF de drift.

On vérifie que :
1. Les petits montants (0.01 CHF) sont conservés exactement
2. Les montants standards (deux décimales) ne sont pas altérés
3. amount_chf == amount pour un compte CHF (pas de conversion, pas d'arrondi)
4. amount_chf est calculé correctement pour un compte EUR avec taux connu
5. Un montant nul (0.00) est stocké sans planter

On passe par ImportService.run() — c'est le chemin réel, pas un raccourci.
Si le Decimal est corrompu quelque part entre TransactionDict et la DB, ce test le verra.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.services.conftest import make_file_hash, make_tx
from transactions.models import Transaction
from transactions.services import ImportService

# =============================================================================
# 1. Petit montant — 0.01 CHF conservé exactement
# =============================================================================


@pytest.mark.django_db
def test_tiny_amount_stored_exactly(chf_account, user):
    """
    amount=-0.01 (frais bancaires minimes, 1 centime).
    Après import, Transaction.amount doit être Decimal("-0.01"), pas 0 ni -0.009999...
    """
    tx = make_tx("tiny", amount=-0.01, currency="CHF")
    service = ImportService()
    result = service.run([tx], chf_account, user, "tiny.csv", make_file_hash("tiny"))

    assert result.count_created == 1
    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == Decimal("-0.01"), (
        f"Attendu Decimal('-0.01'), obtenu {stored.amount!r}"
    )


# =============================================================================
# 2. Montant standard — deux décimales conservées
# =============================================================================


@pytest.mark.django_db
def test_standard_amount_stored_exactly(chf_account, user):
    """
    amount=-1234.56 — montant typique, deux décimales.
    Aucun arrondi ne doit survenir.
    """
    tx = make_tx("standard", amount=-1234.56, currency="CHF")
    service = ImportService()
    result = service.run(
        [tx], chf_account, user, "standard.csv", make_file_hash("standard")
    )

    assert result.count_created == 1
    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == Decimal("-1234.56"), (
        f"Attendu Decimal('-1234.56'), obtenu {stored.amount!r}"
    )


# =============================================================================
# 3. Compte CHF — amount_chf == amount (pas de conversion)
# =============================================================================


@pytest.mark.django_db
def test_chf_account_amount_chf_equals_amount(chf_account, user):
    """
    Pour un compte CHF, aucune conversion n'est nécessaire.
    amount_chf doit être identique à amount.

    C'est un invariant fondamental : si amount_chf != amount pour CHF,
    tous les totaux budgétaires sont faux.
    """
    tx = make_tx("chf-eq", amount=-99.99, currency="CHF")
    service = ImportService()
    service.run([tx], chf_account, user, "chf-eq.csv", make_file_hash("chf-eq"))

    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == stored.amount_chf == Decimal("-99.99")


# =============================================================================
# 4. Compte EUR — amount_chf = amount × taux
# =============================================================================


@pytest.mark.django_db
def test_eur_account_amount_chf_uses_exchange_rate(eur_account, user):
    """
    Pour un compte EUR, amount_chf = amount × taux EUR→CHF.

    On mock get_exchange_rate pour contrôler le taux et éviter les appels API.
    Taux fictif : 1 EUR = 1.05 CHF.
    Transaction : -100.00 EUR → amount_chf doit être Decimal("-105.00").

    Pourquoi Decimal et pas float ?
    Decimal("-100.00") × Decimal("1.05") = Decimal("-105.0000") → arrondi à 2 décimales
    en DB (champ DecimalField(max_digits=12, decimal_places=2)).
    """
    tx = make_tx("eur-conv", amount=-100.00, currency="EUR")
    service = ImportService()

    with patch(
        "transactions.services.import_service.get_exchange_rate",
        return_value=Decimal("1.05"),
    ):
        service.run([tx], eur_account, user, "eur-conv.csv", make_file_hash("eur-conv"))

    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == Decimal("-100.00")
    assert stored.amount_chf == Decimal("-105.00"), (
        f"Attendu -105.00 (= -100 × 1.05), obtenu {stored.amount_chf!r}"
    )


# =============================================================================
# 5. Taux indisponible — amount_chf=None, import ne plante pas
# =============================================================================


@pytest.mark.django_db
def test_eur_account_amount_chf_none_when_rate_unavailable(eur_account, user):
    """
    Si l'API de taux de change est down, get_exchange_rate retourne None.
    L'import doit continuer normalement — la transaction est créée avec amount_chf=None.
    Aucune exception ne doit être levée.
    """
    tx = make_tx("eur-noconv", amount=-50.00, currency="EUR")
    service = ImportService()

    with patch(
        "transactions.services.import_service.get_exchange_rate",
        return_value=None,
    ):
        result = service.run(
            [tx], eur_account, user, "eur-noconv.csv", make_file_hash("eur-noconv")
        )

    assert result.count_created == 1
    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == Decimal("-50.00")
    assert stored.amount_chf is None


# =============================================================================
# 6. Montant zéro — stocké sans crash
# =============================================================================


@pytest.mark.django_db
def test_zero_amount_stored_without_error(chf_account, user):
    """
    amount=0.00 — peut arriver pour des écritures d'équilibre ou des corrections.
    L'import doit fonctionner, le montant doit être Decimal("0.00").

    Note : amount >= 0 → catégorie par défaut "revenus" (ou None si absente).
    """
    tx = make_tx("zero", amount=0.00, currency="CHF")
    service = ImportService()
    result = service.run([tx], chf_account, user, "zero.csv", make_file_hash("zero"))

    assert result.count_created == 1
    stored = Transaction.objects.get(import_hash=tx["import_hash"])
    assert stored.amount == Decimal("0.00")
    assert stored.amount_chf == Decimal("0.00")
