"""
tests/test_budget_category_counts_idor.py

Tests : protection IDOR sur les comptages de transactions dans les vues
de gestion des catégories (budget/views.py).

Pourquoi ces tests sont critiques :
    Trois vues annotaient ou comptaient Transaction.objects sans scope user :

    1. budget_panel_category_manage (GET /budget/panel/category-manage/)
       Count("transactions") → comptait TOUTES les transactions toutes banques.
       Un user pouvait voir "150 transactions" dans "Alimentation" alors qu'il
       n'en a que 50 — révélant l'activité financière d'autres utilisateurs.

    2. budget_panel_category_manage_detail (GET /budget/panel/category-manage/<slug>/)
       Même problème sur les sous-catégories.

    3. budget_panel_category_delete_confirm (GET /budget/category/<type>/<slug>/delete-confirm/)
       Transaction.objects.filter(category=obj).count() sans for_user() →
       affichait "Vous avez 300 transactions à recatégoriser" même si user
       n'en possède que 50.

Fix appliqué :
    1 & 2 : Count("transactions", filter=Q(transactions__account__members=request.user))
    3 :     Transaction.objects.for_user(request.user).filter(category=obj).count()

    Django supporte Count(filter=Q(...)) depuis 2.0 — agrégat conditionnel SQL FILTER.
    Plus efficace qu'un Subquery et lisible directement dans le queryset.

Scénarios testés :
    A. budget_panel_category_manage
        1. tx_count reflète UNIQUEMENT les transactions de l'user connecté
        2. tx_count n'inclut PAS les transactions d'un autre user

    B. budget_panel_category_manage_detail
        3. tx_count des sous-catégories scopé à l'user connecté
        4. tx_count ne révèle pas les transactions d'un autre user

    C. budget_panel_category_delete_confirm (category)
        5. tx_count dans le HTML = nb transactions de l'user
        6. tx_count n'inclut pas les transactions d'un autre user

    D. budget_panel_category_delete_confirm (subcategory)
        7. tx_count scoped pour les sous-catégories

    E. Finding #8 — budget_rule_edit_submit (ValueError → 500)
        8. category_id non numérique → retourne la règle inchangée (pas 500)
        9. category_id vide avec keyword renseigné → règle inchangée

    F. Finding #9 — settings IMPORT_ENCRYPTION_KEY
       10. Démarrage Django sans IMPORT_ENCRYPTION_KEY → pas d'exception
       11. storage._get_key() sans clé → ImproperlyConfigured
"""

from decimal import Decimal

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from transactions.models import CategorizationRule, Category, SubCategory, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@cat-counts-idor.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@cat-counts-idor.ch", password="pass"
    )


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.login(email="usera@cat-counts-idor.ch", password="pass")
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Cat Counts IDOR Bank",
        slug="cat-counts-idor-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Account A Cat Counts",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Account B Cat Counts",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def category(db):
    return Category.objects.create(
        name="Cat Counts Test Cat",
        slug="cat-counts-test-cat",
        colour_hex="#abc",
        order=99,
        is_system=False,
    )


@pytest.fixture
def subcat(db, category):
    return SubCategory.objects.create(
        category=category,
        name="Cat Counts Test Subcat",
        slug="cat-counts-test-subcat",
        is_system=False,
    )


def _make_tx(account, category, subcat=None, n=1):
    """Crée n transactions pour un compte/catégorie donnés."""
    txs = []
    from datetime import date

    for i in range(n):
        txs.append(
            Transaction(
                account=account,
                category=category,
                subcategory=subcat,
                amount=Decimal("-10.00"),
                date=date(2026, 1, 1),
                description_raw=f"tx-{i}",
                import_hash=f"hash-{account.pk}-{category.pk}-{i}-subcat{subcat.pk if subcat else 'none'}",
            )
        )
    Transaction.objects.bulk_create(txs)


# =============================================================================
# A. budget_panel_category_manage — tx_count scopé
# =============================================================================


@pytest.mark.django_db
def test_category_manage_tx_count_includes_only_own_transactions(
    client_a, account_a, account_b, category, user_b
):
    """
    budget_panel_category_manage : tx_count reflète UNIQUEMENT les transactions
    appartenant aux comptes de l'user connecté.

    user_a a 3 tx, user_b a 5 tx dans la même catégorie.
    user_a doit voir tx_count=3, pas 8.
    """
    _make_tx(account_a, category, n=3)
    _make_tx(account_b, category, n=5)

    response = client_a.get(reverse("budget:panel_category_manage"))
    assert response.status_code == 200

    # La catégorie annotée doit avoir tx_count=3 (pas 8)
    cats = response.context["cats"]
    cat = next((c for c in cats if c.slug == category.slug), None)
    assert cat is not None, "La catégorie doit apparaître dans la liste"
    assert cat.tx_count == 3, (
        f"tx_count={cat.tx_count} : doit être 3 (user_a) et non 8 (tous les users)"
    )


@pytest.mark.django_db
def test_category_manage_tx_count_excludes_other_user_transactions(
    client_a, account_a, account_b, category
):
    """
    budget_panel_category_manage : les transactions de user_b ne doivent pas
    être comptabilisées pour user_a.

    Cas limite : user_a a 0 tx, user_b en a 10.
    Le tx_count vu par user_a doit être 0, pas 10.
    """
    _make_tx(account_b, category, n=10)

    response = client_a.get(reverse("budget:panel_category_manage"))
    assert response.status_code == 200

    cats = response.context["cats"]
    cat = next((c for c in cats if c.slug == category.slug), None)
    assert cat is not None
    assert cat.tx_count == 0, (
        f"tx_count={cat.tx_count} : user_a n'a aucune transaction, "
        "doit être 0 et non {cat.tx_count}"
    )


# =============================================================================
# B. budget_panel_category_manage_detail — subcat tx_count scopé
# =============================================================================


@pytest.mark.django_db
def test_category_manage_detail_subcat_tx_count_scoped_to_user(
    client_a, account_a, account_b, category, subcat
):
    """
    budget_panel_category_manage_detail : tx_count des sous-catégories
    doit être scopé à l'user connecté.

    user_a a 2 tx dans subcat, user_b en a 7.
    user_a doit voir tx_count=2, pas 9.
    """
    _make_tx(account_a, category, subcat=subcat, n=2)
    _make_tx(account_b, category, subcat=subcat, n=7)

    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category.slug])
    )
    assert response.status_code == 200

    subcats = response.context["subcats"]
    sc = next((s for s in subcats if s.slug == subcat.slug), None)
    assert sc is not None, "La sous-catégorie doit apparaître dans le détail"
    assert sc.tx_count == 2, (
        f"tx_count={sc.tx_count} : doit être 2 (user_a) et non 9 (tous les users)"
    )


@pytest.mark.django_db
def test_category_manage_detail_subcat_tx_count_zero_for_other_user(
    client_a, account_a, account_b, category, subcat
):
    """
    budget_panel_category_manage_detail : si user_a n'a aucune transaction
    dans la sous-catégorie, son tx_count doit être 0 même si user_b en a.
    """
    _make_tx(account_b, category, subcat=subcat, n=4)

    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category.slug])
    )
    assert response.status_code == 200

    subcats = response.context["subcats"]
    sc = next((s for s in subcats if s.slug == subcat.slug), None)
    assert sc is not None
    assert sc.tx_count == 0


# =============================================================================
# C. budget_panel_category_delete_confirm — category tx_count scopé
# =============================================================================


@pytest.mark.django_db
def test_category_delete_confirm_tx_count_scoped_to_user(
    client_a, account_a, account_b, category
):
    """
    budget_panel_category_delete_confirm : le tx_count affiché dans la page
    de confirmation de suppression doit être scopé à l'user connecté.

    user_a a 4 tx, user_b en a 6 dans la même catégorie.
    user_a doit voir "4 transactions" dans l'avertissement, pas 10.
    """
    _make_tx(account_a, category, n=4)
    _make_tx(account_b, category, n=6)

    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["category", category.slug])
    )
    assert response.status_code == 200
    assert response.context["tx_count"] == 4, (
        f"tx_count={response.context['tx_count']} : doit être 4 (user_a), pas 10"
    )


@pytest.mark.django_db
def test_category_delete_confirm_does_not_count_other_user_transactions(
    client_a, account_a, account_b, category
):
    """
    budget_panel_category_delete_confirm : les transactions de user_b ne doivent
    pas apparaître dans le count de user_a.
    """
    _make_tx(account_b, category, n=8)

    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["category", category.slug])
    )
    assert response.status_code == 200
    assert response.context["tx_count"] == 0


# =============================================================================
# D. budget_panel_category_delete_confirm — subcategory tx_count scopé
# =============================================================================


@pytest.mark.django_db
def test_subcategory_delete_confirm_tx_count_scoped_to_user(
    client_a, account_a, account_b, category, subcat
):
    """
    budget_panel_category_delete_confirm (type=subcategory) : tx_count scopé.
    """
    _make_tx(account_a, category, subcat=subcat, n=3)
    _make_tx(account_b, category, subcat=subcat, n=9)

    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["subcategory", subcat.slug])
    )
    assert response.status_code == 200
    assert response.context["tx_count"] == 3, (
        f"tx_count={response.context['tx_count']} : doit être 3 (user_a), pas 12"
    )


# =============================================================================
# E. Finding #8 — budget_rule_edit_submit : ValueError → 500 sur input non numérique
# =============================================================================


@pytest.fixture
def rule(db, category):
    return CategorizationRule.objects.create(
        keyword="SUPERMARCHE",
        category=category,
        priority=10,
    )


@pytest.mark.django_db
def test_rule_edit_non_numeric_category_id_returns_rule_unchanged(
    client_a, rule, category
):
    """
    budget_rule_edit_submit : category_id non numérique (ex: injection tamperée)
    doit retourner la règle inchangée avec HTTP 200, pas une 500.

    Avant le fix : int("not-a-number") levait ValueError → Django retournait 500.
    """
    client_a.login(email="usera@cat-counts-idor.ch", password="pass")
    response = client_a.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "NEWKW", "category_id": "not-a-number", "subcategory_id": ""},
    )
    assert response.status_code == 200, f"Attendu 200, reçu {response.status_code}"

    rule.refresh_from_db()
    assert rule.keyword == "SUPERMARCHE", "La règle ne doit pas avoir été modifiée"
    assert rule.category_id == category.pk, "La catégorie ne doit pas avoir changé"


@pytest.mark.django_db
def test_rule_edit_non_numeric_subcategory_id_returns_rule_unchanged(
    client_a, rule, category
):
    """
    budget_rule_edit_submit : subcategory_id non numérique → règle inchangée.
    """
    client_a.login(email="usera@cat-counts-idor.ch", password="pass")
    response = client_a.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {
            "keyword": "NEWKW",
            "category_id": str(category.pk),
            "subcategory_id": "not-a-number",
        },
    )
    assert response.status_code == 200

    rule.refresh_from_db()
    assert rule.keyword == "SUPERMARCHE", "La règle ne doit pas avoir été modifiée"


# =============================================================================
# F. Finding #9 — IMPORT_ENCRYPTION_KEY : démarrage sans la clé
# =============================================================================


def test_settings_without_import_encryption_key_does_not_crash():
    """
    settings.IMPORT_ENCRYPTION_KEY avec default="" → Django peut démarrer
    sans cette variable d'environnement.

    Avant le fix : config("IMPORT_ENCRYPTION_KEY") (sans default) levait
    UndefinedValueError au démarrage si la clé était absente du .env.
    """
    from django.conf import settings

    # Le simple fait d'accéder à IMPORT_ENCRYPTION_KEY ne doit pas lever d'exception.
    # La clé peut être vide ou renseignée selon l'environnement.
    key = getattr(settings, "IMPORT_ENCRYPTION_KEY", None)
    assert key is not None, (
        "IMPORT_ENCRYPTION_KEY doit exister dans settings (même vide)"
    )
    # En CI / test sans .env → doit être "" et non lever une exception
    assert isinstance(key, str)


def test_storage_get_key_raises_improperly_configured_when_empty():
    """
    imports/storage._get_key() : si la clé est vide, lève ImproperlyConfigured
    avec un message d'aide explicite (pas un KeyError ou AttributeError cryptique).
    """
    from django.core.exceptions import ImproperlyConfigured

    from imports.storage import _get_key

    with override_settings(IMPORT_ENCRYPTION_KEY=""):
        with pytest.raises(ImproperlyConfigured) as exc_info:
            _get_key()
        assert "IMPORT_ENCRYPTION_KEY" in str(exc_info.value)
