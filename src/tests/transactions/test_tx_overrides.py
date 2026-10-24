"""
tests/transactions/test_tx_overrides.py — sauvegarde/restauration de la couche manuelle (#346).

Corriger un parseur impose souvent de purger puis réimporter un compte. L'opération
détruit tout le travail fait à la main sur les transactions : catégories posées sans
règle, transactions pointées, transactions ignorées. Mesuré sur le compte Yuh réel :
64 catégorisations manuelles + 172 lignes portant un flag manuel.

`import_hash` ne peut PAS servir de clé de réappariement : il change dès qu'un parseur
évolue — c'est précisément ce qui motive le réimport. La clé repose donc sur les champs
BRUTS, stables d'une version de parseur à l'autre, plus un rang d'occurrence pour les
lignes strictement identiques (même mécanique que `occurrence_index` côté parseurs).

⚠️ La clé utilise `description_raw` (texte banque), JAMAIS `display_name` : le nettoyage
de libellé peut changer, et c'est même souvent ce qu'on vient de corriger.
"""

import datetime
import hashlib

import pytest

from accounts.models import Account, Institution
from transactions.models import Category, SubCategory, Transaction
from transactions.services import tx_overrides

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="ovr@t.ch", password="p")


@pytest.fixture
def account(db, user):
    bank = Institution.objects.create(
        name="Ovr Bank", slug="ovr-bank", country="CH", default_currency="CHF"
    )
    acc = Account.objects.create(
        institution=bank, name="Ovr Courant", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def categories(db):
    courses = Category.objects.create(
        name="Courses", slug="courses-ovr", colour_hex="#5fae9f", order=10
    )
    sub = SubCategory.objects.create(
        category=courses, name="Supermarché", slug="supermarche-ovr"
    )
    autre = Category.objects.create(
        name="Autre", slug="autre-ovr", colour_hex="#888888", order=20
    )
    return courses, sub, autre


def make_tx(
    account,
    seed,
    *,
    description_raw="MIGROS LAUSANNE",
    amount="-10.00",
    date=datetime.date(2026, 3, 1),
    display_name=None,
    **kwargs,
):
    return Transaction.objects.create(
        account=account,
        date=date,
        amount=amount,
        currency="CHF",
        amount_chf=amount,
        description_raw=description_raw,
        display_name=display_name if display_name is not None else description_raw,
        import_hash=hashlib.sha256(f"ovr:{seed}".encode()).hexdigest(),
        **kwargs,
    )


# =============================================================================
# Clé de réappariement
# =============================================================================


@pytest.mark.django_db
def test_export_produces_one_entry_per_transaction(user, account, categories):
    courses, _, _ = categories
    make_tx(account, "a", category=courses)
    make_tx(account, "b", description_raw="COOP", category=courses)

    payload = tx_overrides.export_overrides(account)

    assert payload["account_id"] == account.pk
    assert len(payload["overrides"]) == 2


@pytest.mark.django_db
def test_identical_rows_get_distinct_occurrence_ranks(user, account, categories):
    """3 lignes strictement identiques → rangs 0/1/2, sinon elles s'écrasent au retour."""
    courses, _, _ = categories
    for seed in ("x1", "x2", "x3"):
        make_tx(account, seed, category=courses)

    payload = tx_overrides.export_overrides(account)
    ranks = sorted(o["key"]["occurrence"] for o in payload["overrides"])

    assert ranks == [0, 1, 2]


@pytest.mark.django_db
def test_key_ignores_display_name(user, account, categories):
    """
    Le nettoyage de libellé est justement ce qu'on corrige en réimportant : si la clé
    en dépendait, aucun override ne se réapparierait après un changement de parseur.
    """
    courses, _, _ = categories
    tx = make_tx(account, "d", display_name="ANCIEN LIBELLE", category=courses)
    before = tx_overrides.export_overrides(account)["overrides"][0]["key"]

    tx.display_name = "NOUVEAU LIBELLE NETTOYE"
    tx.save(update_fields=["display_name"])
    after = tx_overrides.export_overrides(account)["overrides"][0]["key"]

    assert before == after


# =============================================================================
# Aller-retour complet
# =============================================================================


@pytest.mark.django_db
def test_round_trip_restores_manual_layer(user, account, categories):
    """Le scénario réel : export → purge → réimport → restauration."""
    courses, sub, _ = categories
    make_tx(
        account,
        "r",
        category=courses,
        subcategory=sub,
        is_reconciled=True,
        is_ignored=True,
        note="loyer de mars",
        merchant_name="Migros Chailly",
    )
    payload = tx_overrides.export_overrides(account)

    # Purge + réimport : mêmes champs bruts, import_hash DIFFÉRENT (parseur corrigé),
    # aucune catégorie (les règles n'ont rien matché).
    Transaction.objects.filter(account=account).delete()
    make_tx(account, "rebuilt-different-hash")

    report = tx_overrides.import_overrides(payload, user=user)

    tx = Transaction.objects.get(account=account)
    assert tx.category_id == courses.pk
    assert tx.subcategory_id == sub.pk
    assert tx.is_reconciled is True
    assert tx.is_ignored is True
    assert tx.note == "loyer de mars"
    assert tx.merchant_name == "Migros Chailly"
    assert report.applied == 1
    assert report.unmatched == []


@pytest.mark.django_db
def test_unmatched_overrides_are_reported_by_name(user, account, categories):
    """Jamais d'échec silencieux : une ligne disparue doit être nommée."""
    courses, _, _ = categories
    make_tx(account, "gone", description_raw="DISPARUE", category=courses)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()

    report = tx_overrides.import_overrides(payload, user=user)

    assert report.applied == 0
    assert len(report.unmatched) == 1
    assert "DISPARUE" in report.unmatched[0]


@pytest.mark.django_db
def test_new_transaction_without_override_is_left_alone(user, account, categories):
    """
    Le correctif des conversions CRÉE des lignes qui n'existaient pas (jambes
    manquantes). Elles n'ont aucun override — il ne faut surtout pas les toucher.
    """
    courses, _, _ = categories
    make_tx(account, "known", category=courses)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    make_tx(account, "known2")
    nouvelle = make_tx(
        account, "leg", description_raw="JAMBE DE CHANGE", amount="2000.00"
    )

    tx_overrides.import_overrides(payload, user=user)

    nouvelle.refresh_from_db()
    assert nouvelle.category_id is None
    assert nouvelle.is_reconciled is False


@pytest.mark.django_db
def test_import_is_idempotent(user, account, categories):
    courses, sub, _ = categories
    make_tx(account, "i", category=courses, subcategory=sub, is_reconciled=True)
    payload = tx_overrides.export_overrides(account)

    first = tx_overrides.import_overrides(payload, user=user)
    second = tx_overrides.import_overrides(payload, user=user)

    assert first.applied == second.applied == 1
    tx = Transaction.objects.get(account=account)
    assert tx.category_id == courses.pk and tx.is_reconciled is True


@pytest.mark.django_db
def test_dry_run_writes_nothing(user, account, categories):
    courses, _, autre = categories
    make_tx(account, "dr", category=courses, is_reconciled=True)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    tx = make_tx(account, "dr2", category=autre)

    report = tx_overrides.import_overrides(payload, user=user, dry_run=True)

    tx.refresh_from_db()
    assert report.applied == 1  # ce qui SERAIT appliqué
    assert tx.category_id == autre.pk  # mais rien n'a bougé
    assert tx.is_reconciled is False


@pytest.mark.django_db
def test_report_counts_categories_the_rules_already_got_right(
    user, account, categories
):
    """
    Distinguer « restauré » de « déjà correct » : c'est ce qui révèle les divergences
    entre la catégorie manuelle sauvegardée et ce que les règles assignent aujourd'hui
    (15 cas sur le compte Yuh réel).
    """
    courses, _, autre = categories
    make_tx(account, "c1", category=courses)
    make_tx(account, "c2", description_raw="COOP", category=courses)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    make_tx(account, "c1b", category=courses)  # la règle a retrouvé la même
    make_tx(account, "c2b", description_raw="COOP", category=autre)  # divergence

    report = tx_overrides.import_overrides(payload, user=user)

    assert report.category_already_correct == 1
    assert report.category_changed == 1
