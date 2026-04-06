"""
config/settings.py — BricBudget Django configuration.

Reading guide:
    1. Paths & secrets    (BASE_DIR, SECRET_KEY, DEBUG)
    2. Apps & middleware  (INSTALLED_APPS, MIDDLEWARE)
    3. Auth               (AUTH_USER_MODEL, LOGIN_URL, redirects)
    4. Templates          (TEMPLATES, DIRS, APP_DIRS)
    5. Database           (DATABASES)
    6. Password policy    (AUTH_PASSWORD_VALIDATORS)
    7. Localisation       (LANGUAGE_CODE, TIME_ZONE, USE_I18N)
    8. Static files       (STATIC_URL, STATICFILES_DIRS)
    9. Misc               (DEFAULT_AUTO_FIELD)
"""

from pathlib import Path

from decouple import config  # reads variables from .env — never hardcode secrets here

# =============================================================================
# 1. Paths & secrets
# =============================================================================

# BASE_DIR = src/   (the folder that contains manage.py)
# Path(__file__) = src/config/settings.py
# .parent        = src/config/
# .parent.parent = src/
BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY: used by Django to sign sessions, CSRF tokens, password reset links...
# Must stay secret in production. Loaded from .env — never commit the real value.
SECRET_KEY = config("SECRET_KEY")

# DEBUG=True: Django shows full error pages with stack traces.
# DEBUG=False: production mode — errors return a plain 500 page.
# Never run DEBUG=True on a public server — it leaks internal code.
DEBUG = config("DEBUG", default=False, cast=bool)

# ALLOWED_HOSTS: list of domains Django will accept requests from.
# In production, set this to your real domain: ["bricbudget.com"].
# In development, "localhost" and "127.0.0.1" are enough.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")


# =============================================================================
# 2. Apps & middleware
# =============================================================================

INSTALLED_APPS = [
    # --- Django built-in apps (always required) ---
    "django.contrib.admin",  # /admin/ interface
    "django.contrib.auth",  # login, logout, permissions, groups
    "django.contrib.contenttypes",  # generic FK system (used internally by admin + auth)
    "django.contrib.sessions",  # server-side sessions (stored in DB)
    "django.contrib.messages",  # one-time flash messages (success/error banners)
    "django.contrib.staticfiles",  # static file serving in development
    # --- BricBudget apps ---
    # Declaration order matters when apps reference each other's models at import time.
    # Rule: always declare dependencies before dependents.
    # users/ has no FK to other apps → declared first
    # accounts/ has FK to users/ (Card.user) → declared second
    # transactions/ has FK to accounts/ (Transaction.account) → declared last
    "users",
    "accounts",
    "transactions",
]

# MIDDLEWARE: a stack of functions that wrap every request/response.
# Django runs them top-to-bottom on the way IN, bottom-to-top on the way OUT.
#
# SecurityMiddleware    → HTTPS redirects, HSTS headers, clickjacking protection
# SessionMiddleware     → loads the session from DB before the view runs
# CommonMiddleware      → normalises URLs (trailing slash, APPEND_SLASH)
# CsrfViewMiddleware    → validates the CSRF token on every POST request
# AuthenticationMiddleware → attaches request.user from the session
# MessageMiddleware     → makes flash messages available in templates
# XFrameOptionsMiddleware → sends X-Frame-Options header (prevents iframe embedding)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ROOT_URLCONF: the Python module Django reads to resolve URLs.
# Django imports config/urls.py and iterates urlpatterns top-to-bottom.
ROOT_URLCONF = "config.urls"


# =============================================================================
# 3. Auth
# =============================================================================

# AUTH_USER_MODEL: replaces Django's default User (username-based) with our
# CustomUser (email-based). CRITICAL: must be set before the first migration.
# Changing it afterwards requires dropping and recreating the entire database.
# Always reference users via settings.AUTH_USER_MODEL in FK fields —
# never import User directly from django.contrib.auth.models.
AUTH_USER_MODEL = "users.CustomUser"

# LOGIN_URL: where Django redirects unauthenticated users who try to access
# a view decorated with @login_required.
# Django appends ?next=/original-path/ so we can redirect back after login.
LOGIN_URL = "/login/"

# LOGIN_REDIRECT_URL: where to go after a successful login when no ?next= is set.
# Phase 1B: patrimoine est la page d'accueil principale.
LOGIN_REDIRECT_URL = "/synthese/"

# LOGOUT_REDIRECT_URL: where to go after logout.
LOGOUT_REDIRECT_URL = "/login/"


# =============================================================================
# 4. Templates
# =============================================================================

TEMPLATES = [
    {
        # BACKEND: which template engine to use. DjangoTemplates is the default.
        # Alternative: Jinja2 — but Django's engine integrates better with the admin.
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # DIRS: explicit list of directories Django searches first, in order.
        # We put our global templates here: base layout, login page, error pages.
        # Path: src/templates/
        "DIRS": [BASE_DIR / "templates"],
        # APP_DIRS: when True, Django also looks in <app>/templates/ for every
        # app in INSTALLED_APPS. Searched after DIRS.
        # This is how django.contrib.admin serves its own templates.
        # Rule of thumb: app-specific templates → <app>/templates/<app>/
        #                shared templates → src/templates/
        "APP_DIRS": True,
        "OPTIONS": {
            # context_processors: functions that inject variables into every template
            # automatically, without the view explicitly passing them.
            #
            # request → adds {{ request }} (current HTTP request object)
            # auth    → adds {{ user }} (current logged-in user or AnonymousUser)
            #           and {{ perms }} (user's permissions)
            # messages → adds {{ messages }} (flash messages list)
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# WSGI_APPLICATION: the entry point for production WSGI servers (gunicorn, uWSGI).
# Not used during development (manage.py runserver bypasses this).
WSGI_APPLICATION = "config.wsgi.application"


# =============================================================================
# 5. Database
# =============================================================================

# All values read from .env — never hardcode credentials here.
# DB_PORT default: 5433 because port 5432 is taken by Homebrew PostgreSQL on this Mac.
# Inside Docker the container still uses 5432 — only the Mac-side port differs.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="bricbudget"),
        "USER": config("DB_USER", default="bricbudget"),
        "PASSWORD": config("DB_PASSWORD", default="bricbudget"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}


# =============================================================================
# 6. Password policy
# =============================================================================

# Django runs these validators on every new password (registration, password change).
# Each validator checks one rule and raises ValidationError if it fails.
AUTH_PASSWORD_VALIDATORS = [
    {
        # Rejects passwords too similar to the user's email or name
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        # Minimum 8 characters by default (configurable via OPTIONS: {"min_length": 12})
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        # Rejects passwords from a list of 20 000 common passwords ("password", "123456"...)
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        # Rejects passwords that are entirely numeric ("19820412")
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# =============================================================================
# 7. Localisation
# =============================================================================

LANGUAGE_CODE = "en-us"

# All datetimes stored in DB are in UTC (USE_TZ=True below).
# Django converts them to Europe/Zurich when rendering in templates.
TIME_ZONE = "Europe/Zurich"

# USE_I18N=False: disables Django's translation system entirely.
# Side effect: the admin interface stays in English regardless of the browser language.
# Acceptable for BricBudget — we control the language via Profile.language in Phase 1B.
USE_I18N = False

# USE_TZ=True: all datetimes are stored in UTC in the database.
# Django converts to TIME_ZONE when displaying. Always keep True — avoids DST bugs.
USE_TZ = True


# =============================================================================
# 8. Static files (CSS, JavaScript, images, SVG icons)
# =============================================================================

# STATIC_URL: the URL *prefix* the browser uses to request static files.
# Example: {% static 'icons/banks/yuh.svg' %} → /static/icons/banks/yuh.svg
# This is the public-facing address — the browser never sees the disk path.
STATIC_URL = "static/"

# STATICFILES_DIRS: directories on disk where Django looks for static files
# when a browser requests /static/<path>.
# Django maps:  /static/icons/banks/yuh.svg
#           →   src/static/icons/banks/yuh.svg
#
# Only used in development (DEBUG=True). In production, run collectstatic instead:
#   python manage.py collectstatic
# → copies everything from STATICFILES_DIRS into STATIC_ROOT (a single folder)
# → Nginx serves STATIC_ROOT directly, bypassing Django entirely (much faster).
#
# STATIC_ROOT is not set here because we don't deploy yet.
STATICFILES_DIRS = [BASE_DIR / "static"]


# =============================================================================
# 9. Misc
# =============================================================================

# DEFAULT_AUTO_FIELD: the type of auto-generated primary key for models that
# don't declare their own primary key.
# BigAutoField = 64-bit integer (up to 9.2 × 10^18 rows).
# The old default was AutoField (32-bit, ~2 billion rows) — BigAutoField is safer.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
