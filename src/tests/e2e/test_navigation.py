"""
tests/e2e/test_navigation.py — Smoke E2E : navigation entre écrans clés (#159).

Une fois connecté, l'utilisateur navigue dans la sidebar entre Budget et
Patrimoine. On vérifie qu'un élément propre à chaque écran est bien rendu
(vrai DOM, vrais static), pas seulement que l'URL change.
"""

from tests.e2e.conftest import login


def test_navigate_budget_to_patrimoine(page, live_server, e2e_user):
    """Connecté → clic « Patrimoine » dans la sidebar → page bilan rendue."""
    login(page, live_server)

    # Le lien « Patrimoine » de la sidebar pointe vers /patrimoine/ (overview).
    # get_by_role cible le <a> par son texte accessible → robuste au markup.
    page.get_by_role("link", name="Patrimoine").click()
    page.wait_for_url(f"{live_server.url}/patrimoine/")

    # <h2>Actifs</h2> est rendu par _overview_body.html → preuve que la page bilan
    # s'est affichée (pas un redirect ni une 500).
    assert page.get_by_role("heading", name="Actifs").is_visible()


def test_navigate_patrimoine_back_to_budget(page, live_server, e2e_user):
    """Depuis Patrimoine → clic « Budget » → retour au dashboard budget."""
    login(page, live_server)

    # Aller sur Patrimoine d'abord.
    page.get_by_role("link", name="Patrimoine").click()
    page.wait_for_url(f"{live_server.url}/patrimoine/")

    # Puis revenir sur Budget via la sidebar.
    page.get_by_role("link", name="Budget").click()
    page.wait_for_url(f"{live_server.url}/budget/")

    assert page.get_by_text("Distribution").is_visible()
