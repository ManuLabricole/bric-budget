"""
tests/e2e/test_login.py — Smoke E2E : parcours de connexion (#159).

Le parcours le plus critique : un utilisateur réel ouvre la page de login,
saisit ses identifiants dans le VRAI formulaire, et atterrit sur son dashboard
budget avec une session valide (son email apparaît dans la sidebar).

Ces tests tournent contre `live_server` (vrai serveur Django, vrais static via
StaticFilesHandler) dans un vrai chromium headless. Ils sont taggés `e2e`
automatiquement (voir conftest local) → exclus de la suite par défaut.
"""

from tests.e2e.conftest import E2E_EMAIL, E2E_PASSWORD, login


def test_login_redirects_to_budget_dashboard(page, live_server, e2e_user):
    """Login via le formulaire → redirigé sur /budget/, email visible (session OK)."""
    login(page, live_server)

    # On est bien sur le dashboard budget.
    assert page.url == f"{live_server.url}/budget/"

    # Preuve d'une session authentifiée réelle : la sidebar rend request.user.email.
    # Si la session n'était pas posée, @login_required aurait renvoyé vers /login/.
    expect(page.get_by_text(E2E_EMAIL)).to_be_visible()

    # Élément propre au dashboard budget — confirme que la page (et ses static)
    # se sont bien rendus, pas juste un redirect nu.
    expect(page.get_by_text("Distribution")).to_be_visible()


def test_login_wrong_password_shows_error(page, live_server, e2e_user):
    """Mauvais mot de passe → reste sur /login/, message d'erreur affiché."""
    page.goto(f"{live_server.url}/login/")
    page.fill("input[name='username']", E2E_EMAIL)
    page.fill("input[name='password']", "mauvais-mot-de-passe")
    page.click("button[type='submit']")

    # Pas de redirect : on reste sur la page de login (le POST re-rend le form).
    assert "/login/" in page.url
    # Le template login.html rend ce message exact quand form.errors est non vide.
    assert page.get_by_text("Email ou mot de passe incorrect.").is_visible()


def test_dashboard_requires_login(page, live_server):
    """Accès direct à /budget/ sans session → redirigé vers /login/ (@login_required)."""
    page.goto(f"{live_server.url}/budget/")
    # LOGIN_URL = /login/ ; @login_required ajoute ?next=/budget/.
    assert "/login/" in page.url


# Garde-fou : on n'importe E2E_PASSWORD que pour le documenter ici (cohérence des
# identifiants entre helper et tests). Référence explicite pour éviter un import mort.
_ = E2E_PASSWORD
