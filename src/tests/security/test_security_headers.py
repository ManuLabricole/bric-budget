"""
tests/security/test_security_headers.py — non-régression en-têtes sécu (#164).

Pourquoi ce fichier ?
---------------------
Les tests existants vérifient des *valeurs de settings* (ex. SECURE_HSTS_SECONDS),
PAS la réponse HTTP réelle. Or `check --deploy` ne voit pas le middleware custom
`PermissionsPolicyMiddleware` : un refactor pourrait le retirer du MIDDLEWARE
silencieusement, sans qu'aucun test ne rougisse. Ici on inspecte une VRAIE
réponse HTTP prod-like et on asserte la présence/valeur de chaque header sécu
ET les flags des cookies session + CSRF.

Pourquoi @override_settings + secure=True ?
-------------------------------------------
Les protections HTTPS (HSTS, cookies Secure, Permissions-Policy) ne sont activées
qu'en prod, dans le bloc `if not DEBUG:` de settings.py. Ce bloc s'exécute UNE
fois au chargement du module : `override_settings(DEBUG=False)` seul ne le rejoue
pas. On reproduit donc explicitement les valeurs prod attendues via
@override_settings (les mêmes que settings.py lignes 67-78), et on émet la requête
en HTTPS (`secure=True`) pour que SecurityMiddleware pose le header HSTS.

`override_settings` émet le signal `setting_changed` → Django reconstruit le
handler WSGI du client de test, donc `PermissionsPolicyMiddleware.__init__` est
ré-exécuté et relit `settings.PERMISSIONS_POLICY` (qui mémoïse la policy à l'init).
"""

import pytest
from django.test import Client, override_settings

# Valeurs prod attendues — miroir de config/settings.py (bloc `if not DEBUG:`)
# et des défauts Django (X-Content-Type-Options, Referrer-Policy, X-Frame-Options).
EXPECTED_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"
EXPECTED_HSTS = "max-age=31536000; includeSubDomains; preload"

# Reproduit la config sécu prod sur la durée des tests de ce module.
# On NE met PAS SECURE_SSL_REDIRECT=True : avec secure=True la requête est déjà
# en HTTPS, mais le garder à False évite tout 301 parasite et garde le test focalisé
# sur les en-têtes de la réponse 200 finale.
prodlike_security = override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
    PERMISSIONS_POLICY=EXPECTED_PERMISSIONS_POLICY,
)


@pytest.fixture
def secure_response(db):
    """
    GET /login/ en HTTPS prod-like → réponse HTTP réelle (200) à inspecter.

    `/login/` est public (pas de @login_required) et pose le cookie CSRF
    (formulaire de connexion) → permet d'asserter les flags des deux cookies.
    `db` car SessionMiddleware/axes touchent la base au passage.
    """
    with prodlike_security:
        client = Client()
        response = client.get("/login/", secure=True)
    return response


@pytest.mark.django_db
def test_login_page_is_200(secure_response):
    # Garde-fou : si /login/ régresse en 30x/40x, les assertions d'en-têtes
    # ci-dessous testeraient une mauvaise réponse. On verrouille le 200 d'abord.
    assert secure_response.status_code == 200


@pytest.mark.django_db
def test_strict_transport_security_header(secure_response):
    # Émis par django.middleware.security.SecurityMiddleware quand la requête
    # est HTTPS et SECURE_HSTS_SECONDS > 0.
    assert secure_response["Strict-Transport-Security"] == EXPECTED_HSTS


@pytest.mark.django_db
def test_x_frame_options_header(secure_response):
    # Émis par XFrameOptionsMiddleware — défaut DENY (anti-clickjacking).
    assert secure_response["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
def test_x_content_type_options_header(secure_response):
    # SECURE_CONTENT_TYPE_NOSNIFF (défaut Django = True) → nosniff.
    assert secure_response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_referrer_policy_header(secure_response):
    # SECURE_REFERRER_POLICY (défaut Django = "same-origin").
    assert secure_response["Referrer-Policy"] == "same-origin"


@pytest.mark.django_db
def test_permissions_policy_header(secure_response):
    # ⚠️ Couverture CŒUR de #164 : header émis UNIQUEMENT par notre
    # PermissionsPolicyMiddleware custom (config/middleware.py), invisible à
    # `check --deploy`. Si quelqu'un le retire du MIDDLEWARE, ce test rougit.
    assert "Permissions-Policy" in secure_response
    assert secure_response["Permissions-Policy"] == EXPECTED_PERMISSIONS_POLICY


@pytest.mark.django_db
def test_session_cookie_flags():
    """
    Flags du cookie de session après login réussi : Secure + HttpOnly + SameSite.
    On se connecte réellement pour que Django pose le cookie `sessionid` avec ses
    flags (un GET seul ne le pose pas toujours).
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    with prodlike_security:
        User.objects.create_user(email="cookie@example.com", password="pw-Strong-123")
        client = Client()
        client.post(
            "/login/",
            {"username": "cookie@example.com", "password": "pw-Strong-123"},
            secure=True,
        )
        session_cookie = client.cookies.get("sessionid")

    assert session_cookie is not None, "le cookie sessionid doit être posé au login"
    assert session_cookie["secure"], "sessionid doit être Secure (HTTPS only)"
    assert session_cookie["httponly"], "sessionid doit être HttpOnly (anti-XSS)"
    # SESSION_COOKIE_SAMESITE défaut Django = "Lax".
    assert session_cookie["samesite"], "sessionid doit avoir un attribut SameSite"


@pytest.mark.django_db
def test_csrf_cookie_flags():
    """
    Flags du cookie CSRF posé par le formulaire /login/ : Secure + SameSite.
    Note : le cookie CSRF n'est PAS HttpOnly par design (le JS doit pouvoir le
    lire pour le renvoyer dans l'en-tête X-CSRFToken) → on ne l'asserte pas.
    """
    with prodlike_security:
        client = Client()
        client.get("/login/", secure=True)
        csrf_cookie = client.cookies.get("csrftoken")

    assert csrf_cookie is not None, "le cookie csrftoken doit être posé sur /login/"
    assert csrf_cookie["secure"], "csrftoken doit être Secure (HTTPS only)"
    assert csrf_cookie["samesite"], "csrftoken doit avoir un attribut SameSite"
