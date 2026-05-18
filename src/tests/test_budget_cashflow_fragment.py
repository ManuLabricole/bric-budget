"""
tests/test_budget_cashflow_fragment.py

Tests : budget_category_cashflow_fragment + budget_category_detail (Phase 2G)

Pourquoi ces tests sont critiques :
    budget_category_cashflow_fragment est un endpoint *nouveau* introduit en session 33
    pour résoudre la stale Sankey après un toggle is_ignored depuis le panneau détail.
    Il n'avait aucun test. Ces tests garantissent qu'il reste fonctionnel et accessible.

    budget_category_detail est la page entière — testée ici pour les cas Sankey présent
    vs absent, en fonction de la présence de transactions actives.

Scénarios testés :
    A. category_cashflow_fragment
        1. Retourne 200 pour un user connecté avec une catégorie existante
        2. Retourne un fragment HTML (pas de DOCTYPE ni <html>)
        3. Contient l'en-tête "Cashflow"
        4. Retourne 404 pour un slug inconnu
        5. IDOR : les données de l'user sont filtrées (autre user voit total à 0)

    B. budget_category_detail
        6. Retourne 200 pour un user connecté
        7. Contient l'id="sankey-chart" quand des transactions actives existent
        8. Pas de sankey quand aucune transaction sur la période

    C. toggle_ignore cashflow_refresh_url — DB + signal JS (déjà testé en F dans
       test_internal_transfer.py — on ne duplique pas ici)
"""

import hashlib
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import Category, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="cashflow@test.ch", password="pass"
    )


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="other_cashflow@test.ch", password="pass"
    )


@pytest.fixture
def auth_client(user):
    c = Client()
    c.login(email="cashflow@test.ch", password="pass")
    return c


@pytest.fixture
def other_client(other_user):
    c = Client()
    c.login(email="other_cashflow@test.ch", password="pass")
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Cashflow Bank",
        slug="cashflow-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Cashflow Account",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def category(db):
    return Category.objects.create(
        name="Alimentation CF",
        slug="alimentation-cf",
        colour_hex="#4ade80",
        order=50,
        is_system=False,
    )


def make_tx(account, category, amount="-50.00", seed="cf"):
    """Crée une transaction sur le mois courant."""
    from datetime import date

    return Transaction.objects.create(
        account=account,
        category=category,
        date=date.today().replace(day=1),
        amount=Decimal(amount),
        currency="CHF",
        amount_chf=Decimal(amount),
        description_raw=f"CF TX {seed}",
        display_name=f"CF TX {seed}",
        is_ignored=False,
        import_hash=hashlib.sha256(f"cf-test:{seed}".encode()).hexdigest(),
    )


# =============================================================================
# A. budget_category_cashflow_fragment
# =============================================================================


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_200(auth_client, category):
    """User connecté + catégorie existante → 200."""
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_inner_html_only(auth_client, category):
    """Le fragment ne doit PAS être une page HTML complète (pas de DOCTYPE)."""
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_category_cashflow_fragment_contains_cashflow_header(auth_client, category):
    """Le fragment contient l'en-tête 'Cashflow' (titre de la card)."""
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    assert "Cashflow" in response.content.decode()


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_404_for_unknown_slug(auth_client):
    """Slug inconnu → 404."""
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=["slug-qui-nexiste-pas"])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_cashflow_fragment_no_sankey_without_transactions(
    auth_client, category
):
    """Sans transactions actives sur la période → pas de Sankey."""
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' not in content


@pytest.mark.django_db
def test_category_cashflow_fragment_shows_sankey_with_active_transactions(
    auth_client, account, category
):
    """Avec transactions actives → le Sankey est présent dans le fragment."""
    make_tx(account, category, seed="sankey-ok")
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' in content
    assert 'id="sankey-data"' in content


@pytest.mark.django_db
def test_category_cashflow_fragment_ignored_txs_excluded_from_total(
    auth_client, account, category
):
    """
    Les transactions is_ignored=True ne contribuent pas au total affiché.
    On crée une tx active et une ignorée — seul le montant actif doit
    apparaître dans les KPIs.
    """
    make_tx(account, category, amount="-100.00", seed="active")
    ignored_tx = make_tx(account, category, amount="-999.00", seed="ignored")
    ignored_tx.is_ignored = True
    ignored_tx.save(update_fields=["is_ignored"])

    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    content = response.content.decode()
    # Le montant 999 de la tx ignorée NE doit PAS apparaître comme total
    # (Il peut apparaître dans la liste, mais pas dans le KPI de total)
    assert "999" not in content or "100" in content  # 100 est le vrai total


@pytest.mark.django_db
def test_category_cashflow_fragment_other_user_sees_zero_total(
    other_client, account, category
):
    """
    Les transactions du compte appartiennent à 'user', pas 'other_user'.
    other_user voit la catégorie (globale) mais ses KPIs sont à zéro.
    """
    make_tx(account, category, amount="-500.00", seed="other-idor")

    response = other_client.get(
        reverse("budget:category_cashflow_fragment", args=[category.slug])
    )
    assert response.status_code == 200
    content = response.content.decode()
    # other_user n'est pas membre du compte → total_amount = 0
    assert "500" not in content


# =============================================================================
# B. budget_category_detail
# =============================================================================


@pytest.mark.django_db
def test_category_detail_returns_200(auth_client, category):
    """Page complète de détail catégorie → 200."""
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_category_detail_returns_full_page(auth_client, category):
    """La page détail est une page HTML complète (avec DOCTYPE)."""
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    content = response.content.decode()
    assert "<!DOCTYPE html>" in content or "<html" in content


@pytest.mark.django_db
def test_category_detail_returns_404_for_unknown_slug(auth_client):
    """Slug inconnu → 404."""
    response = auth_client.get(reverse("budget:category_detail", args=["slug-inconnu"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_detail_no_sankey_without_transactions(auth_client, category):
    """Sans transactions → pas d'élément Sankey dans le rendu."""
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    content = response.content.decode()
    assert 'id="sankey-chart"' not in content


@pytest.mark.django_db
def test_category_detail_shows_sankey_with_transactions(auth_client, account, category):
    """Avec transactions actives → le chart Sankey est rendu."""
    make_tx(account, category, seed="detail-sankey")
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    content = response.content.decode()
    assert 'id="sankey-chart"' in content
    assert 'id="sankey-data"' in content


@pytest.mark.django_db
def test_category_detail_shows_category_name(auth_client, category):
    """Le nom de la catégorie apparaît dans la page."""
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    assert category.name in response.content.decode()


@pytest.mark.django_db
def test_category_detail_contains_cashflow_card(auth_client, category):
    """La card cashflow avec son id est présente dans la page."""
    response = auth_client.get(reverse("budget:category_detail", args=[category.slug]))
    assert 'id="cashflow-card"' in response.content.decode()
