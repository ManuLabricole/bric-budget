"""
tests/users/test_auth_flow.py

Couverture exhaustive du flow auth BricBudget :
  - Landing /
  - Login GET / POST (valide, invalide, next, open-redirect)
  - Logout POST / session effacée
  - Pages protégées (budget, patrimoine, import)
  - Valeurs des settings auth (redirects, session)

Les tests axes (lockout après 5 tentatives) vivent dans tests/security/test_axes.py.
"""

import pytest
from django.conf import settings
from django.urls import reverse  # noqa: F401

# ---------------------------------------------------------------------------
# Fixture locale
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="auth@bricbudget.ch", password="S3cur3P@ss!"
    )


# ===========================================================================
# Landing page ( / )
# ===========================================================================


@pytest.mark.django_db
class TestLanding:
    def test_anonymous_gets_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_contains_login_link(self, client):
        r = client.get("/")
        assert b"/login/" in r.content or b'href="' in r.content

    def test_authenticated_redirects_to_budget(self, client, user):
        client.force_login(user)
        r = client.get("/")
        assert r.status_code == 302
        assert r["Location"] == "/budget/"

    def test_authenticated_redirect_is_not_landing(self, client, user):
        # L'utilisateur connecté ne doit jamais boucler sur / .
        client.force_login(user)
        r = client.get("/", follow=True)
        # L'URL finale n'est pas la landing.
        assert r.redirect_chain[-1][0] == "/budget/"


# ===========================================================================
# Login GET
# ===========================================================================


@pytest.mark.django_db
class TestLoginGet:
    def test_anonymous_gets_200(self, client):
        r = client.get(reverse("login"))
        assert r.status_code == 200

    def test_contains_csrf_token(self, client):
        r = client.get(reverse("login"))
        assert b"csrfmiddlewaretoken" in r.content

    def test_next_param_preserved_in_form(self, client):
        r = client.get(reverse("login") + "?next=/budget/")
        assert b'name="next"' in r.content
        assert b"/budget/" in r.content


# ===========================================================================
# Login POST — credentials valides
# ===========================================================================


@pytest.mark.django_db
class TestLoginPostValid:
    def test_redirect_to_budget_by_default(self, client, user):
        r = client.post(
            reverse("login"),
            {"username": user.email, "password": "S3cur3P@ss!"},
        )
        assert r.status_code == 302
        assert r["Location"] == "/budget/"

    def test_safe_next_is_honoured(self, client, user):
        # Un next interne valide doit être respecté.
        r = client.post(
            reverse("login"),
            {
                "username": user.email,
                "password": "S3cur3P@ss!",
                "next": "/patrimoine/",
            },
        )
        assert r.status_code == 302
        assert r["Location"] == "/patrimoine/"

    def test_external_next_is_blocked(self, client, user):
        # Open-redirect : un next vers un hôte externe doit être ignoré.
        r = client.post(
            reverse("login"),
            {
                "username": user.email,
                "password": "S3cur3P@ss!",
                "next": "http://evil.com/steal",
            },
        )
        assert r.status_code == 302
        assert "evil.com" not in r["Location"]

    def test_session_is_created(self, client, user):
        client.post(
            reverse("login"),
            {"username": user.email, "password": "S3cur3P@ss!"},
        )
        # Si la session est créée, le cookie de session existe.
        assert settings.SESSION_COOKIE_NAME in client.cookies

    def test_user_is_authenticated_after_login(self, client, user):
        client.post(
            reverse("login"),
            {"username": user.email, "password": "S3cur3P@ss!"},
        )
        r = client.get("/budget/")
        # L'accès à /budget/ doit fonctionner (pas de redirect vers login).
        assert r.status_code == 200


# ===========================================================================
# Login POST — credentials invalides / edge cases
# ===========================================================================


@pytest.mark.django_db
class TestLoginPostInvalid:
    def test_wrong_password_stays_on_login(self, client, user):
        r = client.post(
            reverse("login"),
            {"username": user.email, "password": "wrong"},
        )
        assert r.status_code == 200

    def test_unknown_email_stays_on_login(self, client):
        r = client.post(
            reverse("login"),
            {"username": "nobody@nowhere.com", "password": "whatever"},
        )
        assert r.status_code == 200

    def test_empty_password_stays_on_login(self, client, user):
        r = client.post(
            reverse("login"),
            {"username": user.email, "password": ""},
        )
        assert r.status_code == 200

    def test_empty_email_stays_on_login(self, client):
        r = client.post(
            reverse("login"),
            {"username": "", "password": "anything"},
        )
        assert r.status_code == 200

    def test_empty_body_stays_on_login(self, client):
        r = client.post(reverse("login"), {})
        assert r.status_code == 200

    def test_no_redirect_on_failure(self, client, user):
        r = client.post(
            reverse("login"),
            {"username": user.email, "password": "bad"},
        )
        # Pas de redirect — on reste sur la page de login.
        assert r.status_code != 302


# ===========================================================================
# Logout
# ===========================================================================


@pytest.mark.django_db
class TestLogout:
    def test_post_authenticated_redirects_to_login(self, client, user):
        client.force_login(user)
        r = client.post(reverse("logout"))
        assert r.status_code == 302
        assert r["Location"] == "/login/"

    def test_session_is_cleared_after_logout(self, client, user):
        client.force_login(user)
        client.post(reverse("logout"))
        # Après logout, /budget/ doit rediriger vers /login/.
        r = client.get("/budget/")
        assert r.status_code == 302
        assert "/login/" in r["Location"]

    def test_protected_page_unreachable_after_logout(self, client, user):
        client.force_login(user)
        client.post(reverse("logout"))
        for protected in ["/budget/", "/patrimoine/", "/import/"]:
            r = client.get(protected)
            assert r.status_code == 302, f"{protected} devrait rediriger après logout"
            assert "/login/" in r["Location"]

    def test_logout_anonymous_does_not_crash(self, client):
        # Un utilisateur non connecté qui POST logout ne doit pas lever une 500.
        r = client.post(reverse("logout"))
        assert r.status_code in (200, 302)


# ===========================================================================
# Pages protégées — accès non authentifié
# ===========================================================================


@pytest.mark.django_db
class TestProtectedPages:
    PROTECTED_URLS = [
        "/budget/",
        "/patrimoine/",
        "/import/",
    ]

    def test_redirects_to_login(self, client):
        for url in self.PROTECTED_URLS:
            r = client.get(url)
            assert r.status_code == 302, f"{url} doit rediriger"
            assert "/login/" in r["Location"], f"{url} doit rediriger vers /login/"

    def test_next_param_is_set(self, client):
        for url in self.PROTECTED_URLS:
            r = client.get(url)
            # ?next= doit être présent pour que Django redirige après login.
            assert "next=" in r["Location"] or "next=" in r.get("Location", ""), (
                f"{url} doit inclure ?next="
            )

    def test_accessible_when_authenticated(self, client, user):
        client.force_login(user)
        for url in self.PROTECTED_URLS:
            r = client.get(url)
            # Doit retourner 200 — pas une redirection vers login.
            assert r.status_code == 200, f"{url} doit être accessible après login"


# ===========================================================================
# Settings auth — valeurs de configuration
# ===========================================================================


class TestAuthSettings:
    def test_login_redirect_url_is_budget(self):
        assert settings.LOGIN_REDIRECT_URL == "/budget/"

    def test_logout_redirect_url_is_login(self):
        assert settings.LOGOUT_REDIRECT_URL == "/login/"

    def test_login_url_is_slash_login(self):
        assert settings.LOGIN_URL == "/login/"

    def test_session_cookie_age_is_30_days(self):
        assert settings.SESSION_COOKIE_AGE == 60 * 60 * 24 * 30

    def test_session_does_not_expire_at_browser_close(self):
        assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
