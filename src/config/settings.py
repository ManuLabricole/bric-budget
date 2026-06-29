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
from urllib.parse import urlparse

from decouple import config  # reads variables from .env — never hardcode secrets here
from django.core.exceptions import ImproperlyConfigured

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
# En local : localhost,127.0.0.1 (défaut).
# En prod Railway : ajouter votre domaine dans la variable ALLOWED_HOSTS.
# Railway injecte aussi RAILWAY_PUBLIC_DOMAIN automatiquement — on l'ajoute ici.
# strip() + filtre vides : "example.com, www.example.com" → ["example.com", "www.example.com"]
# sans ça, un espace ou une virgule finale crée une entrée vide/avec espace qui ne matche jamais.
_raw_hosts = config("ALLOWED_HOSTS", default="localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(",") if h.strip()]

_railway_domain = config("RAILWAY_PUBLIC_DOMAIN", default="").strip()
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)

# Railway effectue son healthcheck depuis le host `healthcheck.railway.app` (doc
# Healthchecks). Avec DEBUG=False, Django renvoie 400 si ce host n'est pas autorisé
# → le healthcheck échoue (« failed with status 400 ») et le deploy est marqué KO.
# On l'ajoute uniquement quand on tourne sur Railway (domaine public présent).
if _railway_domain and "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# CSRF_TRUSTED_ORIGINS : obligatoire pour les POST en HTTPS (Django 4+).
# Toujours préfixer avec https:// — les cookies SameSite exigent l'origine complète.
# On exclut localhost/127.0.0.1 (HTTP local) et "*" (wildcard invalide comme origin).
_local_hosts = {"localhost", "127.0.0.1"}
CSRF_TRUSTED_ORIGINS = [
    f"https://{h}" for h in ALLOWED_HOSTS if h not in _local_hosts and h != "*"
]

# En production (DEBUG=False) : forcer HTTPS et sécuriser les cookies.
if not DEBUG:
    # Railway termine SSL en amont (edge proxy) → Django reçoit HTTP en interne.
    # Sans SECURE_PROXY_SSL_HEADER, SECURE_SSL_REDIRECT crée une boucle infinie.
    # Ce header indique à Django que le proxy a déjà géré HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # Le healthcheck Railway arrive en HTTP interne — exempter du redirect HTTPS.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 an — validé en prod
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Permissions-Policy : désactive les APIs navigateur non utilisées.
    # Réduit la surface d'attaque côté client (caméra, micro, géoloc...).
    PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"


# =============================================================================
# 1b. Error tracking — Sentry (#259)
# =============================================================================
#
# Sentry est un service CLOUD : l'app ENVOIE ses exceptions non gérées via une DSN.
# Découplage par variable d'env : SENTRY_DSN absente (dev/CI) → init sautée, zéro
# effet ; présente (var Railway, prod) → tracking actif. La DSN n'est JAMAIS
# committée ni mise dans le .env de dev.
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    from config.sentry import scrub_sensitive  # before_send testable (#259)

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Tag d'environnement (Railway injecte RAILWAY_ENVIRONMENT_NAME) → un futur
        # staging aura ses erreurs étiquetées à part.
        environment=config("RAILWAY_ENVIRONMENT_NAME", default="production"),
        send_default_pii=False,  # pas de cookies/IP
        # ⛔ App bancaire : couper les VECTEURS de fuite à la source (audit #260).
        # include_local_variables=False : ne PAS envoyer les variables locales des
        # stack traces (sinon un IBAN/montant/ligne CSV d'une frame partirait).
        include_local_variables=False,
        max_request_body_size="never",  # jamais le corps de requête
        traces_sample_rate=0.0,  # erreurs only au départ — pas de perf tracing
        before_send=scrub_sensitive,  # 2e couche : masque IBAN par clé ET par valeur
    )


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
    "transactions.apps.TransactionsConfig",  # explicit config → ready() appelé → signals connectés
    "budget",
    # imports/ n'a pas de FK vers d'autres apps → déclaré en dernier
    "imports",
    # patrimoine/ lit accounts + transactions au runtime (pas de modèle propre en 3A)
    "patrimoine",
    # demo/ : seed/démo dev. Toujours installée (testable en DEBUG=False), inerte en
    # prod — points d'entrée gardés par assert_dev_environment, admin si DEBUG (cf. demo/apps.py).
    "demo.apps.DemoConfig",
    "axes",  # brute-force protection — doit être après contrib.auth
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
    # WhiteNoise doit être juste après SecurityMiddleware pour servir les fichiers
    # statiques directement depuis Django (sans Nginx) — requis sur Railway.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Injecte le header Permissions-Policy (non géré par SecurityMiddleware).
    "config.middleware.PermissionsPolicyMiddleware",
    # AxesMiddleware doit être en DERNIER — il intercepte les réponses 401/403
    # pour enregistrer les tentatives échouées. Si placé avant AuthenticationMiddleware,
    # il ne voit pas encore request.user et ne peut pas logger correctement.
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    # AxesStandaloneBackend doit être en PREMIER — il lève PermissionDenied si le
    # compte est verrouillé, avant que ModelBackend tente l'authentification.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # heure avant déverrouillage automatique

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
LOGIN_REDIRECT_URL = "/budget/"

# LOGOUT_REDIRECT_URL: where to go after logout.
LOGOUT_REDIRECT_URL = "/login/"

# SESSION_COOKIE_AGE: durée de vie du cookie de session (30 jours).
# SESSION_EXPIRE_AT_BROWSER_CLOSE=False : la session persiste entre fermetures —
# comportement attendu pour une app perso sur machine de confiance.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_EXPIRE_AT_BROWSER_CLOSE = False


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
                "budget.context_processors.design_tokens",
                # Objectifs budget (jauges) dans la topbar — présents sur TOUTES les
                # pages car la topbar vit dans base_app.html (#24).
                "budget.context_processors.budget_objectives",
                # Sidebar Patrimoine ▼ (registre classes d'actifs + état déplié en session).
                # Présent sur toutes les pages car la sidebar vit dans base_app.html.
                "patrimoine.context_processors.sidebar",
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

# Convention 12-factor : une seule variable décrit toute la connexion DB.
# Local  : postgresql://bricbudget:bricbudget@localhost:5433/bricbudget  (port 5433 = Docker)
# CI     : postgresql://bricbudget:bricbudget@localhost:5432/bricbudget
# Railway: injectée automatiquement via Variable Reference depuis le service Postgres
# Si DATABASE_URL est absente, decouple lève UndefinedValueError avec un message clair.
_db_url = config("DATABASE_URL")
_u = urlparse(_db_url)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _u.path.lstrip("/"),
        "USER": _u.username,
        "PASSWORD": _u.password,
        "HOST": _u.hostname,
        "PORT": _u.port or 5432,
        "CONN_MAX_AGE": 60,
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
# Example: {% static 'icons/institutions/yuh.svg' %} → /static/icons/institutions/yuh.svg
# This is the public-facing address — the browser never sees the disk path.
STATIC_URL = "static/"

# STATICFILES_DIRS: directories on disk where Django looks for static files
# when a browser requests /static/<path>.
# Django maps:  /static/icons/institutions/yuh.svg
#           →   src/static/icons/institutions/yuh.svg
#
# Only used in development (DEBUG=True). In production, run collectstatic instead:
#   python manage.py collectstatic
# → copies everything from STATICFILES_DIRS into STATIC_ROOT (a single folder)
# → Nginx serves STATIC_ROOT directly, bypassing Django entirely (much faster).
#
# STATIC_ROOT : dossier cible de `collectstatic` en production.
# Railway lance `python manage.py collectstatic` au build (via Procfile/nixpacks).
# WhiteNoise sert ce dossier directement — pas besoin de Nginx.
STATIC_ROOT = BASE_DIR / "staticfiles"

# STATICFILES_DIRS : sources en développement (ignoré après collectstatic).
STATICFILES_DIRS = [BASE_DIR / "static"]

# =============================================================================
# MEDIA — fichiers ÉCRITS À CHAUD par l'app (logos réparés #128, logos marchands #124)
# =============================================================================
# ⚠️ static/ ≠ media/. static = assets committés en git, livrés par le build et servis
# par WhiteNoise (immuables par release). media = contenu créé par l'app en marche, qui
# DOIT survivre aux redeploys. Sur Railway le FS du container est éphémère (reset à chaque
# deploy) → le media va dans un bucket S3 persistant. En dev : dossier local mediafiles/.
MEDIA_URL = "media/"
MEDIA_ROOT = (
    BASE_DIR / "mediafiles"
)  # dev/CI uniquement (gitignoré) ; prod = S3 (cf. infra)

# Backend du storage MEDIA par défaut, choisi par PRÉSENCE du bucket Railway :
#   - bucket Railway (S3-compatible) si AWS_S3_BUCKET_NAME est défini (prod, et
#     "répétition générale" possible en dev en collant les vars dans .env)
#   - filesystem local (mediafiles/) sinon — dev / CI / tests.
# Aucun flag USE_S3 à maintenir : impossible d'oublier de basculer. Le code applicatif
# passe toujours par default_storage → identique dev (FS) / prod (bucket). Split settings → #144.
#
# ⚠️ Noms de variables = ceux du preset Railway "Connect Service to Bucket → AWS SDK
#    (Generic)" qui mappe les vars natives du bucket vers les noms AWS standard :
#      AWS_S3_BUCKET_NAME ← BUCKET · AWS_ENDPOINT_URL ← ENDPOINT · AWS_DEFAULT_REGION ← REGION
#      AWS_ACCESS_KEY_ID ← ACCESS_KEY_ID · AWS_SECRET_ACCESS_KEY ← SECRET_ACCESS_KEY
#    → 1 clic "Add Variables" avec ce preset suffit (cf. ops.md). Buckets = virtual-hosted URLs.
_bucket = config("AWS_S3_BUCKET_NAME", default="")
if _bucket:
    _media_storage: dict = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": _bucket,
            "endpoint_url": config(
                "AWS_ENDPOINT_URL", default="https://storage.railway.app"
            ),
            "access_key": config("AWS_ACCESS_KEY_ID"),
            "secret_key": config("AWS_SECRET_ACCESS_KEY"),
            "region_name": config("AWS_DEFAULT_REGION", default="auto"),
            "addressing_style": "virtual",  # Railway Buckets = bucket en sous-domaine
            "querystring_auth": True,  # bucket privé → URLs présignées, pas d'accès public
        },
    }
else:
    _media_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

# staticfiles : manifest + compression WhiteNoise en prod ; en dev/CI (DEBUG=True) le
# storage Django par défaut résout {% static %} sans manifest (CompressedManifest exige
# un staticfiles.json généré par collectstatic → ValueError sinon).
_staticfiles_storage = (
    {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
    if DEBUG
    else {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}
)

STORAGES = {
    "default": _media_storage,
    "staticfiles": _staticfiles_storage,
}


# =============================================================================
# 9. Misc
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# FILE_UPLOAD_MAX_MEMORY_SIZE: taille max d'un fichier uploadé conservé en RAM.
# Au-delà, Django bascule sur un fichier temporaire disque (TemporaryFileUploadHandler).
# 5 MB = largement suffisant pour un CSV/Excel bancaire (typiquement < 500 KB).
# Sans cette limite, un upload malveillant ou accidentel peut saturer la RAM du worker.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB


# =============================================================================
# 11. Logging
# =============================================================================

# LOGGING : logs structurés vers stdout → capturés par Railway dashboard.
#
# Niveaux :
#   DEBUG   → très verbeux, uniquement en dev local
#   INFO    → parseurs (nb transactions, nb skipped), imports validés
#   WARNING → lignes CSV ignorées, exceptions silencieuses dans les connecteurs
#   ERROR   → erreurs non récupérées (vues 500, signaux qui plantent)
#
# LOG_LEVEL : contrôlé par variable d'env.
#   Local  : DEBUG (tout voir pendant le dev)
#   Railway: WARNING (silence les INFO, ne remonte que les anomalies)
#
# Pourquoi disable_existing_loggers=False ?
#   Django + bibliothèques tiers configurent leurs propres loggers.
#   False = on AJOUTE notre config sans écraser les leurs.
#   True  = on les écrase → silence total des logs Django internes.

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NOTSET"}
_log_level_raw = (
    config("LOG_LEVEL", default="DEBUG" if DEBUG else "INFO").strip().upper()
)
if _log_level_raw not in _VALID_LOG_LEVELS:
    raise ImproperlyConfigured(
        f"LOG_LEVEL='{_log_level_raw}' est invalide. "
        f"Valeurs acceptées : {', '.join(sorted(_VALID_LOG_LEVELS))}"
    )
_log_level = _log_level_raw

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Format compact pour Railway : timestamp + level + logger + message
        "railway": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        # stdout → Railway capture automatiquement (pas de fichier log en prod)
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "railway",
        },
    },
    "root": {
        # Logger racine : s'applique à tout ce qui n'a pas de logger explicite
        "handlers": ["console"],
        "level": _log_level,
    },
    "loggers": {
        # Django lui-même : propagate=False pour éviter la double sortie.
        # Django configure ses propres loggers internement — on force WARNING en prod.
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Nos apps héritent du root logger via propagation (propagate=True par défaut).
        # Pas besoin de les déclarer explicitement — le root handler les couvre.
        # On les déclare uniquement pour contrôler leur niveau indépendamment.
        "connectors": {"level": _log_level},
        "imports": {"level": _log_level},
        "transactions": {"level": _log_level},
        # Clients S3 (django-storages → boto3) : très bavards en DEBUG (chaque requête
        # bucket = des centaines de lignes). On les fixe à WARNING même en dev — leur
        # DEBUG noie nos propres logs sans valeur de debug métier.
        "botocore": {"level": "WARNING"},
        "boto3": {"level": "WARNING"},
        "s3transfer": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
    },
}


# =============================================================================
# 10. Import file storage
# =============================================================================

# Dossier de stockage des fichiers bancaires uploadés via l'UI /import/.
#
# Local  : assets/private/data/imports/ (gitignored, reste sur le Mac)
# Railway: /mnt/imports (Railway Volume monté sur le service bric-budget)
#          → Volume persistant : survit aux redeploys et aux redémarrages.
#          → Sans Volume, le filesystem Railway est éphémère — les fichiers
#            disparaissent à chaque deploy.
#
# Phase 2H : Railway Volume (simple, suffisant pour usage perso)
# Phase future : migrer vers object storage (Cloudflare R2 ou AWS S3)
#                pour un stockage sans état, scalable, et indépendant du serveur.
#
# ⚠️  Le dossier doit exister avant le premier import — Django ne le crée pas.
#     En local : mkdir -p assets/private/data/imports
#     Sur Railway : créé automatiquement au montage du Volume.
_default_storage = str(BASE_DIR.parent / "assets" / "private" / "data" / "imports")
IMPORT_STORAGE_ROOT = Path(config("IMPORT_STORAGE_ROOT", default=_default_storage))

# Clé Fernet (AES-128-CBC + HMAC-SHA256) pour chiffrer les fichiers au repos.
# default="" permet de démarrer sans la clé (CI, dev sans imports web).
# La clé est requise au moment de l'usage — imports/storage.py lève ImproperlyConfigured
# si elle est vide quand on tente de chiffrer ou déchiffrer un fichier.
# Générer :  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
IMPORT_ENCRYPTION_KEY = config("IMPORT_ENCRYPTION_KEY", default="")


# ── Démo / seed dev (#118) ────────────────────────────────────────────────────
# Identifiants du user de démo créé par `manage.py dev_seed` (app demo/). Vivent
# dans .env — jamais committés. Le user est loginable avec ces identifiants en local.
# Le seed refuse de tourner si le mot de passe est vide (pas de user démo sans mdp).
DEMO_USER_EMAIL = config("DEMO_USER_EMAIL", default="demo@bricbudget.local")
DEMO_USER_PASSWORD = config("DEMO_USER_PASSWORD", default="")


# ── Seed perso de l'admin (#146) ──────────────────────────────────────────────
# User cible par défaut de `manage.py seed_perso` (catégories perso + règles Finary,
# owner=user) et de l'action admin associée. Surchargeable via --user. C'est un EMAIL
# de compte applicatif (pas un identifiant bancaire), donc committable en défaut —
# overridable en .env pour une autre instance/propriétaire.
PERSO_SEED_USER_EMAIL = config(
    "PERSO_SEED_USER_EMAIL", default="emmanuel.barriol@gmail.com"
)


# --- Test speedup (#261) : hachage MD5 SOUS pytest uniquement ----------------
# PBKDF2 (défaut) est volontairement lent ; les tests n'ont pas besoin de sa
# robustesse → MD5 accélère nettement les tests qui créent des users. Inactif en
# prod (pytest absent de sys.modules sous gunicorn).
import sys  # noqa: E402

if "pytest" in sys.modules:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
