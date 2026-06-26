"""
tests/budget/test_objectives_kpi.py — Objectifs budget : badges topbar + bar chart (#24).

Deux surfaces :
  - context processor `budget_objectives` → `topbar_objectives` : une jauge par
    BudgetTarget, présente sur TOUTES les pages (topbar de base_app.html). On prouve
    le calcul (pct, dépassement) ET le rendu des badges (nom au hover).
  - page Budget : bar chart 12 mois agrégé (has_objective / objective_history).
  - page catégorie : titre repositionné (gros) + dropdown de changement de catégorie.
"""

from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from django.urls import reverse

from tests.factories import CategoryFactory, TransactionFactory
from transactions.models import BudgetTarget, Category, Transaction


def _cat(**kwargs: object) -> Category:
    return cast(Category, CategoryFactory(**kwargs))


def _tx(account, category, *, amount, on) -> Transaction:
    return cast(
        Transaction,
        TransactionFactory(
            account=account, category=category, amount=Decimal(amount), date=on
        ),
    )


@pytest.mark.django_db
def test_context_processor_lists_one_objective_per_target(client_a, account_a, user_a):
    """3 objectifs créés → 3 entrées dans topbar_objectives, états 40/100/150 %."""
    today = date.today()
    specs = [("c40", "-200", "500"), ("c100", "-300", "300"), ("over", "-300", "100")]
    for slug, spend, target in specs:
        cat = _cat(owner=user_a, slug=slug, name=slug.upper())
        BudgetTarget.objects.create(category=cat, owner=user_a, amount=Decimal(target))
        _tx(account_a, cat, amount=spend, on=today)

    resp = client_a.get(reverse("budget:index"))

    objs = resp.context["topbar_objectives"]
    assert len(objs) == 3
    by_pct = {o["raw_pct"]: o for o in objs}
    assert by_pct[40]["overspend"] is None
    assert by_pct[100]["overspend"] is None
    assert by_pct[300]["pct"] == 100  # cappé pour l'arc
    assert by_pct[300]["overspend"] == 200  # 300 - 100
    # Anneau ROUGE (token expense) si dépassement ; couleur catégorie sinon.
    assert by_pct[300]["ring_color"] == "#e5494a"
    assert by_pct[40]["ring_color"] != "#e5494a"


@pytest.mark.django_db
def test_context_processor_isolates_objectives_between_users(
    client_a, account_a, user_a, user_b
):
    """IDOR (SR-001) : les objectifs de user_b n'apparaissent JAMAIS dans la topbar
    de user_a (le context processor scope for_user)."""
    cat_b = _cat(owner=user_b, slug="b-obj", name="Objectif de B")
    BudgetTarget.objects.create(category=cat_b, owner=user_b, amount=Decimal("300"))
    cat_a = _cat(owner=user_a, slug="a-obj", name="Objectif de A")
    BudgetTarget.objects.create(category=cat_a, owner=user_a, amount=Decimal("500"))

    resp = client_a.get(reverse("budget:index"))

    slugs = [o["slug"] for o in resp.context["topbar_objectives"]]
    assert "a-obj" in slugs  # le sien
    assert "b-obj" not in slugs  # PAS celui de B
    assert b"Objectif de B" not in resp.content


@pytest.mark.django_db
def test_topbar_badges_render_with_category_name(client_a, account_a, user_a):
    """Le badge rend la jauge + le nom de la catégorie (visible au hover)."""
    cat = _cat(owner=user_a, slug="sante-obj", name="Santé Objectif")
    BudgetTarget.objects.create(category=cat, owner=user_a, amount=Decimal("400"))
    _tx(account_a, cat, amount="-100", on=date.today())

    resp = client_a.get(reverse("budget:index"))

    assert b"group/obj" in resp.content  # markup du badge
    assert "Santé Objectif".encode() in resp.content  # nom (tooltip hover)


@pytest.mark.django_db
def test_topbar_objectives_present_on_non_budget_page(client_a, account_a, user_a):
    """Les badges sont GLOBAUX : présents hors page budget (topbar partagée)."""
    cat = _cat(owner=user_a, slug="glob", name="Globale")
    BudgetTarget.objects.create(category=cat, owner=user_a, amount=Decimal("400"))

    resp = client_a.get(reverse("patrimoine:overview"))

    assert resp.status_code == 200
    assert resp.context["topbar_objectives"]  # liste non vide hors budget
    assert b"group/obj" in resp.content


@pytest.mark.django_db
def test_no_objective_means_empty_topbar(client_a, account_a, user_a):
    """Aucun objectif → topbar_objectives vide, aucun badge."""
    _tx(account_a, _cat(owner=user_a, slug="x"), amount="-50", on=date.today())

    resp = client_a.get(reverse("budget:index"))

    assert resp.context["topbar_objectives"] == []
    assert b"group/obj" not in resp.content


@pytest.mark.django_db
def test_budget_bar_chart_card_with_target(client_a, account_a, user_a):
    """Un objectif → bar chart 12 mois agrégé rendu dans le panel droit budget."""
    cat = _cat(owner=user_a, slug="hist", name="Hist")
    BudgetTarget.objects.create(category=cat, owner=user_a, amount=Decimal("500"))
    _tx(account_a, cat, amount="-200", on=date.today())

    resp = client_a.get(reverse("budget:index"))

    assert resp.context["has_objective"] is True
    assert resp.context["objective_history"] is not None
    assert b"objective-bar-chart" in resp.content


@pytest.mark.django_db
def test_category_detail_has_large_title_and_switch_dropdown(
    client_a, account_a, user_a
):
    """Page catégorie : titre repositionné (gros h1) + dropdown listant les autres
    catégories pour changer de catégorie (#24)."""
    current = _cat(owner=user_a, slug="courante", name="Courante")
    other = _cat(owner=user_a, slug="autre-cat", name="Autre Cat")
    _tx(account_a, current, amount="-50", on=date.today())

    resp = client_a.get(reverse("budget:category_detail", args=[current.slug]))

    assert resp.status_code == 200
    # Titre Finary : gros h1 (text-2xl) avec le nom de la catégorie courante.
    assert b"text-2xl font-semibold" in resp.content
    assert b"Courante" in resp.content
    # Dropdown : lien vers l'AUTRE catégorie.
    assert reverse("budget:category_detail", args=[other.slug]).encode() in resp.content
    assert b"group/catdd" in resp.content
