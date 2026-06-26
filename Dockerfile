# Dockerfile — image applicative BricBudget (déploiement Railway).
#
# Pourquoi un Dockerfile (≠ Railpack/Nixpacks) :
#   Railway ne supporte plus que 2 builders : RAILPACK (défaut, auto) ou DOCKERFILE.
#   Railpack ignore nixpacks.toml et n'installe PAS pg_dump → la commande de backup
#   (dump_db_to_s3, pre-deploy) ne pouvait pas tourner. Le Dockerfile donne le contrôle
#   TOTAL de l'image : on y embarque pg_dump, on y fige le build et la commande de start.
#   Railway détecte automatiquement ce fichier et build avec (cf. doc « Builds »).
#
# Découpage : image de base Python → client postgres (pg_dump) → deps → static → start.

FROM python:3.13-slim

# ── pg_dump 18 ────────────────────────────────────────────────────────────────
# Le serveur Postgres Railway est en 18.x ; pg_dump DOIT être >= la version serveur,
# sinon « server version mismatch ». Debian n'embarque pas la 18 → on ajoute le dépôt
# officiel PostgreSQL (PGDG). $VERSION_CODENAME = codename Debian de l'image de base
# (bookworm/trixie) → on prend le bon repo automatiquement.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/*

# ── Poetry ────────────────────────────────────────────────────────────────────
# virtualenvs.create=false : on installe dans le site-packages système (pas de venv
# imbriqué dans le conteneur) → image plus simple, `poetry run` reste fonctionnel.
ENV POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# ── Dépendances ───────────────────────────────────────────────────────────────
# On copie d'abord SEULEMENT les manifestes → la couche d'install est cachée tant que
# pyproject.toml / poetry.lock ne changent pas (rebuilds rapides). --only main : pas
# les deps de dev (pytest, ruff…). --no-root : le projet n'est pas un package installable.
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --only main --no-root

# ── Code + statiques ──────────────────────────────────────────────────────────
COPY . .
# collectstatic à la build (WhiteNoise sert src/staticfiles/ en prod). SECRET_KEY
# factice : ne sert qu'à la copie de fichiers statiques, la vraie clé vient de Railway.
# DATABASE_URL factice : settings.py lit config("DATABASE_URL") au chargement, mais
# collectstatic ne se connecte JAMAIS à la DB → une URL bidon suffit à charger les
# settings. La vraie URL vient de Railway au runtime/pre-deploy.
RUN cd src \
 && SECRET_KEY=build-only-not-secret ALLOWED_HOSTS=localhost DEBUG=False \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    poetry run python manage.py collectstatic --noinput

# ── Start ─────────────────────────────────────────────────────────────────────
# Ex-Procfile. Forme shell (string) → $PORT injecté par Railway est expansé.
# Les migrations NE tournent PAS ici (multi-workers) → pre-deploy (railway.json).
CMD ["sh", "-c", "cd src && poetry run gunicorn config.wsgi --workers 3 --bind 0.0.0.0:$PORT --timeout 30 --access-logfile -"]
