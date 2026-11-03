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
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.factories import (
    AccountFactory,
    SubCategoryFactory,
    SystemCategoryFactory,
    TransactionFactory,
    UserFactory,
)
from transactions.models import Category, Transaction
from transactions.services import tx_overrides

MANUAL = Transaction.CategorizationSource.MANUAL

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    return UserFactory(email="ovr@t.ch")


@pytest.fixture
def account(db, user):
    return AccountFactory(name="Ovr Courant", members=[user])


@pytest.fixture
def categories(db):
    """
    Catégories SYSTÈME (owner NULL) — le cas nominal issu du seed.
    Le scope par utilisateur est couvert à part, avec des PERSO homonymes.
    """
    courses = SystemCategoryFactory(name="Courses", slug="courses-ovr", order=10)
    sub = SubCategoryFactory(
        category=courses, name="Supermarché", slug="supermarche-ovr"
    )
    autre = SystemCategoryFactory(name="Autre", slug="autre-ovr", order=20)
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
    """
    Transaction de test via TransactionFactory — seuls les champs que les tests font
    varier sont passés, le reste vient des defaults de la factory.

    `import_hash` reste dérivé de `seed` plutôt que de la Sequence de la factory :
    plusieurs tests vérifient précisément qu'il ne sert PAS de clé de réappariement,
    donc ils doivent pouvoir le contrôler.
    """
    return TransactionFactory(
        account=account,
        date=date,
        amount=amount,
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
    make_tx(account, "a", category=courses, categorization_source=MANUAL)
    make_tx(
        account,
        "b",
        description_raw="COOP",
        category=courses,
        categorization_source=MANUAL,
    )

    payload = tx_overrides.export_overrides(account)

    assert payload["account_id"] == account.pk
    assert len(payload["overrides"]) == 2


@pytest.mark.django_db
def test_identical_rows_get_distinct_occurrence_ranks(user, account, categories):
    """3 lignes strictement identiques → rangs 0/1/2, sinon elles s'écrasent au retour."""
    courses, _, _ = categories
    for seed in ("x1", "x2", "x3"):
        make_tx(account, seed, category=courses, categorization_source=MANUAL)

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
    tx = make_tx(
        account,
        "d",
        display_name="ANCIEN LIBELLE",
        category=courses,
        categorization_source=MANUAL,
    )
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
        categorization_source=MANUAL,
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
    make_tx(
        account,
        "gone",
        description_raw="DISPARUE",
        category=courses,
        categorization_source=MANUAL,
    )
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
    make_tx(account, "known", category=courses, categorization_source=MANUAL)
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
    make_tx(
        account,
        "i",
        category=courses,
        subcategory=sub,
        categorization_source=MANUAL,
        is_reconciled=True,
    )
    payload = tx_overrides.export_overrides(account)

    first = tx_overrides.import_overrides(payload, user=user)
    second = tx_overrides.import_overrides(payload, user=user)

    assert first.applied == second.applied == 1
    tx = Transaction.objects.get(account=account)
    assert tx.category_id == courses.pk and tx.is_reconciled is True


@pytest.mark.django_db
def test_dry_run_writes_nothing(user, account, categories):
    courses, _, autre = categories
    make_tx(
        account,
        "dr",
        category=courses,
        categorization_source=MANUAL,
        is_reconciled=True,
    )
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    tx = make_tx(account, "dr2", category=autre, categorization_source=MANUAL)

    report = tx_overrides.import_overrides(payload, user=user, dry_run=True)

    tx.refresh_from_db()
    assert report.applied == 1  # ce qui SERAIT appliqué
    assert tx.category_id == autre.pk  # mais rien n'a bougé
    assert tx.is_reconciled is False


@pytest.mark.django_db
def test_rule_assigned_category_is_not_exported(user, account, categories):
    """
    Une catégorie posée par une RÈGLE ne fait pas partie de la couche manuelle : au
    réimport les règles retournent, éventuellement améliorées depuis. La restaurer
    figerait un ancien verdict par-dessus un meilleur.
    """
    courses, _, _ = categories
    make_tx(
        account,
        "byrule",
        category=courses,
        categorization_source=Transaction.CategorizationSource.RULE,
    )

    payload = tx_overrides.export_overrides(account)

    assert payload["overrides"] == []


@pytest.mark.django_db
def test_restoring_a_category_marks_it_manual_and_clears_rule_provenance(
    user, account, categories
):
    """Sans ça, la ligne resterait marquée « rule » en pointant une règle qui ne l'a pas produite."""
    courses, _, autre = categories
    make_tx(account, "prov", category=courses, categorization_source=MANUAL)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    make_tx(
        account,
        "prov2",
        category=autre,
        categorization_source=Transaction.CategorizationSource.RULE,
    )

    tx_overrides.import_overrides(payload, user=user)

    tx = Transaction.objects.get(account=account)
    assert tx.category_id == courses.pk
    assert tx.categorization_source == MANUAL
    assert tx.categorization_rule_id is None


@pytest.mark.django_db
def test_system_and_personal_slugs_do_not_collide(user, account, categories):
    """
    Un slug système (owner NULL, unique global) et un slug perso (unique par user)
    coexistent légitimement, et for_user renvoie LES DEUX. Indexer par slug seul en
    écrasait un : la mauvaise catégorie était restaurée.
    """
    _, _, _ = categories
    systeme = Category.objects.create(
        name="Homonyme système", slug="homonyme", colour_hex="#111111", order=1
    )
    perso = Category.objects.create(
        name="Homonyme perso",
        slug="homonyme",
        colour_hex="#222222",
        order=2,
        owner=user,
    )
    assert systeme.pk != perso.pk

    make_tx(account, "coll", category=perso, categorization_source=MANUAL)
    payload = tx_overrides.export_overrides(account)
    assert payload["overrides"][0]["category"] == {"slug": "homonyme", "system": False}

    Transaction.objects.filter(account=account).delete()
    make_tx(account, "coll2")

    tx_overrides.import_overrides(payload, user=user)

    assert Transaction.objects.get(account=account).category_id == perso.pk


@pytest.mark.django_db
def test_category_resolution_is_scoped_to_the_calling_user(user, account, categories):
    """
    SR-001 — deux PERSO homonymes appartenant à des users différents.

    Un slug perso n'est unique QUE par owner, donc le même slug peut exister chez un
    autre utilisateur. `_index` clé par (slug, système) : deux perso homonymes
    produisent la MÊME clé (slug, False) et s'écrasent. Seul le scope `for_user`
    garantit que celle d'un autre user n'entre jamais dans l'index.

    L'autre catégorie trie APRÈS (order plus grand) pour qu'avec `unscoped()` elle
    gagne l'écrasement — sans quoi le test passerait par chance.
    """
    _, _, _ = categories
    # get_user_model() plutôt que UserFactory : factory_boy n'est pas typé, mypy voit
    # un UserFactory et refuse owner=... (idiome déjà utilisé dans test_import_rule_scoping).
    other = get_user_model().objects.create_user(email="other-ovr@t.ch", password="p")
    mine = Category.objects.create(
        name="Restaurants",
        slug="restaurants-ovr",
        colour_hex="#333333",
        order=10,
        owner=user,
    )
    theirs = Category.objects.create(
        name="Restaurants",
        slug="restaurants-ovr",
        colour_hex="#444444",
        order=20,
        owner=other,
    )
    assert mine.pk != theirs.pk

    make_tx(account, "scope", category=mine, categorization_source=MANUAL)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    make_tx(account, "scope2")

    report = tx_overrides.import_overrides(payload, user=user)

    assert report.is_clean
    assert Transaction.objects.get(account=account).category_id == mine.pk


@pytest.mark.django_db
def test_unresolvable_category_is_reported_and_field_left_untouched(
    user, account, categories
):
    """Une catégorie supprimée depuis l'export ne doit pas VIDER le champ en silence."""
    courses, _, autre = categories
    make_tx(account, "del", category=courses, categorization_source=MANUAL)
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    courses.delete()
    make_tx(
        account,
        "del2",
        category=autre,
        categorization_source=Transaction.CategorizationSource.RULE,
    )

    report = tx_overrides.import_overrides(payload, user=user)

    tx = Transaction.objects.get(account=account)
    assert tx.category_id == autre.pk  # pas écrasé, pas vidé
    assert len(report.unresolved) == 1
    assert "courses-ovr" in report.unresolved[0]
    assert report.is_clean is False


@pytest.mark.django_db
def test_merchant_name_prefilled_by_the_parser_is_not_exported(
    user, account, categories
):
    """
    Les connecteurs préremplissent merchant_name avec le libellé nettoyé. L'exporter
    comme s'il était manuel réécrirait l'ancien libellé par-dessus celui du parseur
    corrigé — exactement l'inverse du but d'un réimport.
    """
    make_tx(
        account,
        "pref",
        display_name="MIGROS LAUSANNE",
        merchant_name="MIGROS LAUSANNE",
        is_reconciled=True,
    )
    make_tx(
        account,
        "edit",
        description_raw="COOP",
        display_name="COOP",
        merchant_name="Coop du coin",
        is_reconciled=True,
    )

    overrides = {
        o["key"]["description_raw"]: o
        for o in tx_overrides.export_overrides(account)["overrides"]
    }

    assert overrides["MIGROS LAUSANNE"]["merchant_name"] == ""
    assert overrides["COOP"]["merchant_name"] == "Coop du coin"


@pytest.mark.django_db
def test_manual_nature_override_survives(user, account, categories):
    """15 `nature` surchargées à la main sur le compte Yuh réel — elles étaient perdues."""
    courses, sub, _ = categories
    make_tx(
        account,
        "nat",
        category=courses,
        subcategory=sub,
        categorization_source=MANUAL,
        nature="fixed",
    )
    payload = tx_overrides.export_overrides(account)

    Transaction.objects.filter(account=account).delete()
    make_tx(account, "nat2")

    tx_overrides.import_overrides(payload, user=user)

    assert Transaction.objects.get(account=account).nature == "fixed"


# =============================================================================
# Commande import_tx_overrides — entrées invalides
# =============================================================================
#
# La commande est le garde-fou joué JUSTE AVANT une purge destructive. Une stack
# trace brute y est inexploitable : l'opérateur doit lire une phrase et décider.


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{ pas du json", "n'est pas un JSON valide"),
        ('["une", "liste"]', "account_id"),
        ('{"version": 1, "overrides": []}', "account_id"),
    ],
)
def test_import_command_rejects_malformed_input(tmp_path, content, expected):
    path = tmp_path / "overrides.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CommandError) as exc:
        call_command("import_tx_overrides", f"--input={path}")

    assert expected in str(exc.value)


@pytest.mark.django_db
def test_import_command_rejects_unsupported_format_version(tmp_path, account):
    """Une version future ne doit pas remonter un ValueError nu."""
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps({"version": 99, "account_id": account.pk, "overrides": []}),
        encoding="utf-8",
    )

    with pytest.raises(CommandError) as exc:
        call_command("import_tx_overrides", f"--input={path}")

    assert "v99" in str(exc.value)
