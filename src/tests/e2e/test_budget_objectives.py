"""
tests/e2e/test_budget_objectives.py — E2E objectifs budget (#24).

Deux parcours navigateur réels :
  1. Les badges objectifs apparaissent dans la topbar (sur toute page) et le NOM
     de la catégorie s'affiche au survol (tooltip group-hover).
  2. Le titre de la page catégorie porte un dropdown permettant de SAUTER à une
     autre catégorie.

Données créées via l'ORM (committées — `live_server` voit un autre thread), sans
factories (cf. conftest e2e). Le marker `e2e` est appliqué automatiquement.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from tests.e2e.conftest import login


@pytest.fixture
def e2e_objectives(transactional_db, e2e_user):
    """Compte + 2 catégories perso + objectifs (BudgetTarget) + une dépense.

    Retourne les deux catégories (courante, autre) pour les assertions de navigation.
    """
    from accounts.models import Account, Institution
    from transactions.models import BudgetTarget, Category, Transaction

    inst = Institution.objects.create(
        name="E2E Bank", slug="e2e-bank", country="CH", default_currency="CHF"
    )
    account = Account.objects.create(
        institution=inst,
        name="E2E Compte",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_active=True,
    )
    account.members.add(e2e_user)

    current = Category.objects.create(
        name="Alimentation E2E",
        slug="alimentation-e2e",
        owner=e2e_user,
        is_system=False,
        colour_hex="#e88c45",
        order=10,
    )
    other = Category.objects.create(
        name="Transport E2E",
        slug="transport-e2e",
        owner=e2e_user,
        is_system=False,
        colour_hex="#4dbf93",
        order=11,
    )
    for cat, amount in ((current, "500"), (other, "300")):
        BudgetTarget.objects.create(
            category=cat, owner=e2e_user, amount=Decimal(amount)
        )

    Transaction.objects.create(
        account=account,
        category=current,
        date=timezone.localdate(),
        amount=Decimal("-200"),
        currency="CHF",
        description_raw="E2E COURSES",
        import_hash="e2e-obj-tx-1",
    )
    return current, other


def test_topbar_objective_badge_shows_name_on_hover(page, live_server, e2e_objectives):
    """Badge objectif visible dans la topbar ; survol → nom de la catégorie affiché."""
    login(page, live_server)

    # Cibler LE badge de cette catégorie (aria-label) — le nom « Alimentation E2E »
    # apparaît aussi dans la liste catégories, donc on scope le tooltip AU badge.
    badge = page.locator('a[aria-label^="Objectif Alimentation E2E"]')
    assert badge.is_visible()

    tooltip_name = badge.get_by_text("Alimentation E2E")
    assert not tooltip_name.is_visible()  # caché tant qu'on ne survole pas

    badge.hover()
    tooltip_name.wait_for(state="visible", timeout=3000)
    assert tooltip_name.is_visible()


def test_category_switch_dropdown_navigates(page, live_server, e2e_objectives):
    """Sur la page catégorie, le dropdown du titre permet de changer de catégorie."""
    current, other = e2e_objectives
    login(page, live_server)

    page.goto(f"{live_server.url}/budget/categorie/{current.slug}/")
    assert page.get_by_role("heading", name="Alimentation E2E").is_visible()

    # Ouvre le dropdown (clic sur le titre = summary du <details>) puis change de cat.
    # exact=True : sinon le badge topbar « Objectif Transport E2E … » matche aussi.
    page.get_by_role("heading", name="Alimentation E2E").click()
    page.get_by_role("link", name="Transport E2E", exact=True).click()

    page.wait_for_url(f"{live_server.url}/budget/categorie/{other.slug}/")
    assert page.get_by_role("heading", name="Transport E2E").is_visible()
