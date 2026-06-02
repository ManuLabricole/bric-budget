"""
tests/services/test_import_service_new_features.py

Tests rigoureux pour les fonctionnalités ajoutées en Phase 2F :

A. CATÉGORIES PAR DÉFAUT
   1. Pas de règle + montant négatif  → catégorie "inconnu"
   2. Pas de règle + montant positif  → catégorie "revenus"
   3. Pas de règle + montant nul      → catégorie "revenus" (≥ 0)
   4. Règle correspondante            → la règle prime sur le défaut
   5. Catégorie "inconnu" absente     → category=None (pas d'erreur, import continue)
   6. Catégorie "revenus" absente     → category=None (pas d'erreur, import continue)
   7. Source DEFAULT vs RULE          → categorization_source correct dans la DB

B. SEEN_IN_BATCH — déduplication intra-fichier
   8. Deux tx avec le même hash dans le même appel → seule la première est créée
   9. seen_in_batch ne bloque PAS les tx à hash différent
  10. seen_in_batch + existing_hashes : les deux mécanismes coexistent
  11. seen_in_batch est réinitialisé entre deux appels run() distincts

C. EUR × DECIMAL — regression test
  12. Compte EUR + montant négatif sans règle → pas d'erreur float*Decimal
  13. Compte EUR + montant positif sans règle → catégorie "revenus" + amount_chf calculé

D. DRY_RUN avec catégories
  14. dry_run=True → count_created correct, aucune transaction en DB
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.services.conftest import make_file_hash, make_tx
from transactions.models import Category, Transaction
from transactions.services import ImportService

# =============================================================================
# Helpers — catégories de test
# =============================================================================


@pytest.fixture
def income_category(db):
    """Catégorie 'revenus' — slug utilisé par ImportService comme défaut positif."""
    return Category.objects.create(
        name="Revenus",
        slug="revenus",
        icon="",
        colour_hex="#00FF00",
        order=1,
        is_system=True,
    )


@pytest.fixture
def unknown_category(db):
    """Catégorie 'inconnu' — slug utilisé par ImportService comme défaut négatif."""
    return Category.objects.create(
        name="Inconnu",
        slug="inconnu",
        icon="",
        colour_hex="#888888",
        order=2,
        is_system=True,
    )


# =============================================================================
# A. Catégories par défaut
# =============================================================================


@pytest.mark.django_db
def test_default_category_negative_amount_assigns_inconnu(
    chf_account, user, income_category, unknown_category
):
    """
    Aucune règle + montant < 0 → category = "inconnu".

    C'est le cas le plus courant : une dépense non encore catégorisée.
    """
    tx = make_tx("neg", amount=-42.50)
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h1"))

    assert result.count_created == 1
    assert result.count_errors == 0
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == unknown_category
    assert saved.subcategory is None
    assert saved.categorization_source == Transaction.CategorizationSource.DEFAULT


@pytest.mark.django_db
def test_default_category_positive_amount_assigns_revenus(
    chf_account, user, income_category, unknown_category
):
    """
    Aucune règle + montant > 0 → category = "revenus".

    Cas typique : virement reçu (salaire, remboursement...).
    """
    tx = make_tx("pos", amount=3500.00)
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h2"))

    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == income_category
    assert saved.categorization_source == Transaction.CategorizationSource.DEFAULT


@pytest.mark.django_db
def test_default_category_zero_amount_assigns_revenus(
    chf_account, user, income_category, unknown_category
):
    """
    Aucune règle + montant = 0 → category = "revenus" (condition >= 0).

    Cas rare mais possible : intérêts nuls, frais annulés.
    """
    tx = make_tx("zero", amount=0.0)
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h3"))

    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == income_category


@pytest.mark.django_db
def test_matching_rule_overrides_default_category(
    chf_account, user, income_category, unknown_category, db
):
    """
    Une règle correspondante → la règle prime sur le défaut.

    Même si le montant est négatif, si une règle match → categorization_source=RULE.
    """
    from transactions.models import CategorizationRule

    rule_cat = Category.objects.create(
        name="Alimentation", slug="alimentation", colour_hex="#FF0000", order=3
    )
    CategorizationRule.objects.create(
        keyword="MIGROS",
        category=rule_cat,
        target_field="description_raw",
        priority=10,
        is_active=True,
    )

    tx = make_tx("rule", amount=-15.90, description_raw="MIGROS LAUSANNE 12345")
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h4"))

    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == rule_cat
    assert saved.categorization_source == Transaction.CategorizationSource.RULE


@pytest.mark.django_db
def test_default_category_unknown_missing_uses_none(chf_account, user, income_category):
    """
    Catégorie "inconnu" absente en DB → category=None, import continue sans erreur.

    Protection contre un DB mal seedé. Une transaction sans catégorie vaut mieux
    qu'un import bloqué.
    """
    tx = make_tx("no_unknown", amount=-10.0)
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h5"))

    assert result.count_created == 1
    assert result.count_errors == 0
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category is None
    assert saved.categorization_source == Transaction.CategorizationSource.DEFAULT


@pytest.mark.django_db
def test_default_category_revenus_missing_uses_none(
    chf_account, user, unknown_category
):
    """
    Catégorie "revenus" absente en DB → category=None, import continue sans erreur.
    """
    tx = make_tx("no_income", amount=100.0)
    result = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("h6"))

    assert result.count_created == 1
    assert result.count_errors == 0
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category is None


@pytest.mark.django_db
def test_categorization_source_default_vs_rule(
    chf_account, user, income_category, unknown_category
):
    """
    Deux transactions dans le même batch — une avec règle, une sans.
    Vérifie que categorization_source est correctement attribué à chacune.
    """
    from transactions.models import CategorizationRule

    rule_cat = Category.objects.create(
        name="Transport", slug="transport", colour_hex="#0000FF", order=4
    )
    CategorizationRule.objects.create(
        keyword="SBB",
        category=rule_cat,
        target_field="description_raw",
        priority=10,
        is_active=True,
    )

    tx_with_rule = make_tx("sbb", amount=-12.0, description_raw="SBB BILLET GENEVE")
    tx_no_rule = make_tx("unknown_shop", amount=-8.0, description_raw="SHOP INCONNU")

    result = ImportService().run(
        [tx_with_rule, tx_no_rule], chf_account, user, "f.csv", make_file_hash("h7")
    )

    assert result.count_created == 2
    saved_rule = Transaction.objects.get(import_hash=tx_with_rule["import_hash"])
    saved_default = Transaction.objects.get(import_hash=tx_no_rule["import_hash"])

    assert saved_rule.category == rule_cat
    assert saved_rule.categorization_source == Transaction.CategorizationSource.RULE
    assert saved_default.category == unknown_category
    assert (
        saved_default.categorization_source == Transaction.CategorizationSource.DEFAULT
    )


# =============================================================================
# B. seen_in_batch — déduplication intra-fichier
# =============================================================================


@pytest.mark.django_db
def test_seen_in_batch_deduplicates_within_same_run(chf_account, user):
    """
    Deux TransactionDict avec le même import_hash dans le même appel run() →
    seule la première est créée, la deuxième est comptée dans count_skipped.

    Scénario réel : deux virements UBS avec même montant + même libellé + même date.
    Sans seen_in_batch, bulk_create() lèverait une IntegrityError sur la contrainte
    unique import_hash.
    """
    tx = make_tx("dup", amount=-50.0)
    tx_copy = make_tx("dup", amount=-50.0)  # même seed → même import_hash

    result = ImportService().run(
        [tx, tx_copy],
        chf_account,
        user,
        "f.csv",
        make_file_hash("h8"),  # type: ignore[list-item]
    )

    assert result.count_created == 1
    assert result.count_skipped == 1
    assert result.count_errors == 0
    # Vérifier qu'une seule transaction a été insérée
    assert Transaction.objects.filter(import_hash=tx["import_hash"]).count() == 1


@pytest.mark.django_db
def test_seen_in_batch_does_not_block_different_hashes(chf_account, user):
    """
    Trois transactions avec des hashes différents dans le même appel → toutes créées.

    Vérifie que seen_in_batch n'a pas d'effet de bord sur les transactions distinctes.
    """
    tx1 = make_tx("a", amount=-10.0)
    tx2 = make_tx("b", amount=-20.0)
    tx3 = make_tx("c", amount=+100.0)

    result = ImportService().run(
        [tx1, tx2, tx3], chf_account, user, "f.csv", make_file_hash("h9")
    )

    assert result.count_created == 3
    assert result.count_skipped == 0


@pytest.mark.django_db
def test_seen_in_batch_and_existing_hashes_coexist(chf_account, user):
    """
    Cas combiné : tx_a déjà en DB (existing_hashes), tx_b doublon intra-batch
    (seen_in_batch), tx_c nouvelle.

    Tous les trois déclenchent count_skipped pour les deux premiers, count_created=1.
    """
    # Premier import : crée tx_a
    tx_a = make_tx("a_existing", amount=-5.0)
    ImportService().run([tx_a], chf_account, user, "f.csv", make_file_hash("file1"))

    # Deuxième import : tx_a déjà en DB, tx_b doublon intra-batch, tx_c nouvelle
    tx_b = make_tx("b_dup", amount=-30.0)
    tx_b_copy = dict(tx_b)
    tx_c = make_tx("c_new", amount=-15.0)

    result = ImportService().run(
        [tx_a, tx_b, tx_b_copy, tx_c],  # type: ignore[list-item]
        chf_account,
        user,
        "f.csv",
        make_file_hash("file2"),
    )

    assert result.count_created == 2  # tx_b + tx_c
    assert result.count_skipped == 2  # tx_a (DB) + tx_b_copy (batch)
    assert Transaction.objects.count() == 3  # tx_a + tx_b + tx_c


@pytest.mark.django_db
def test_seen_in_batch_resets_between_run_calls(chf_account, user):
    """
    seen_in_batch est local à chaque appel run() — pas d'état partagé entre appels.

    Si on importe le même fichier deux fois (file_hash différent pour contourner),
    la deuxième importation repart d'un seen_in_batch vide. La déduplication se
    fait via existing_hashes (DB), pas via seen_in_batch.
    """
    tx = make_tx("shared_hash", amount=-100.0)

    # Premier import
    r1 = ImportService().run([tx], chf_account, user, "f.csv", make_file_hash("run1"))
    assert r1.count_created == 1

    # Deuxième import (file_hash différent, mais même tx hash → skipped via existing_hashes)
    r2 = ImportService().run([tx], chf_account, user, "f2.csv", make_file_hash("run2"))
    assert r2.count_created == 0
    assert r2.count_skipped == 1  # bloqué par existing_hashes, pas seen_in_batch

    assert Transaction.objects.count() == 1


# =============================================================================
# C. EUR × Decimal — regression test
# =============================================================================


@pytest.mark.django_db
def test_eur_account_negative_default_category_no_float_decimal_error(
    eur_account, user, unknown_category, income_category
):
    """
    Régression : avant le fix, 'amount = float(...)' dans le fallback catégorie
    causait 'float * Decimal' lors du calcul amount_chf pour les comptes EUR.

    Ce test vérifie qu'un compte EUR avec une transaction négative sans règle
    s'importe sans erreur. Le bug aurait mis count_errors=1.
    """
    tx = make_tx("eur_neg", amount=-30.0, currency="EUR")

    rate = Decimal("0.93")
    with patch("transactions.services.get_exchange_rate", return_value=rate):
        result = ImportService().run(
            [tx], eur_account, user, "f.csv", make_file_hash("heur1")
        )

    assert result.count_errors == 0, f"Errors: {result.error_detail}"
    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == unknown_category
    # amount_chf = 30.0 × 0.93 = 27.90
    assert saved.amount_chf == Decimal("-27.90")


@pytest.mark.django_db
def test_eur_account_positive_default_category_assigns_revenus(
    eur_account, user, unknown_category, income_category
):
    """
    Compte EUR + montant positif + aucune règle → catégorie "revenus" + amount_chf calculé.
    """
    tx = make_tx("eur_pos", amount=1500.0, currency="EUR")

    rate = Decimal("0.95")
    with patch("transactions.services.get_exchange_rate", return_value=rate):
        result = ImportService().run(
            [tx], eur_account, user, "f.csv", make_file_hash("heur2")
        )

    assert result.count_errors == 0
    assert result.count_created == 1
    saved = Transaction.objects.get(import_hash=tx["import_hash"])
    assert saved.category == income_category
    assert saved.amount_chf == Decimal("1425.00")  # 1500 × 0.95


# =============================================================================
# D. dry_run avec catégories
# =============================================================================


@pytest.mark.django_db
def test_dry_run_counts_correct_with_default_categories(
    chf_account, user, income_category, unknown_category
):
    """
    dry_run=True → count_created reflète les catégories par défaut, rien en DB.

    Un batch mixte (revenus + dépenses) doit être compté correctement même
    sans écriture. Assure que le flow dry-run de la Phase 2F affiche les
    bons chiffres avant confirmation.
    """
    txs = [
        make_tx("d1", amount=-50.0),
        make_tx("d2", amount=+200.0),
        make_tx("d3", amount=-15.0),
    ]

    result = ImportService().run(
        txs, chf_account, user, "f.csv", make_file_hash("hdry"), dry_run=True
    )

    assert result.count_created == 3
    assert result.count_skipped == 0
    assert result.count_errors == 0
    # Rien en DB
    assert Transaction.objects.count() == 0
