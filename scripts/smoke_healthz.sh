#!/usr/bin/env bash
# scripts/smoke_healthz.sh — smoke test de liveness du déploiement.
#
# Démarre l'app EXACTEMENT comme en prod (gunicorn, DEBUG=False, manifest static
# storage) puis vérifie que /healthz/ répond 200 à une requête ANONYME — c'est le
# contrat que Railway pingue toutes les 30 s. Si un middleware auth global ou une
# erreur de boot cassait cette route, le container redémarrerait en boucle ; ce
# smoke le transforme en CI rouge AVANT le deploy (#165, part of #160).
#
# Pré-requis : collectstatic --noinput a déjà tourné (manifest storage exige
# staticfiles.json en DEBUG=False) — c'est l'étape précédente du job deploy-guard.
#
# Variables attendues : SECRET_KEY, DATABASE_URL (settings les lit au boot même si
# /healthz/ ne touche pas la DB). ALLOWED_HOSTS/DEBUG/ADMIN_URL fixés ci-dessous.
set -euo pipefail

PORT="${SMOKE_PORT:-8000}"
HOST="127.0.0.1"
URL="http://${HOST}:${PORT}/healthz/"

cd "$(dirname "$0")/../src"

# Démarre gunicorn en arrière-plan, config prod (DEBUG=False → CompressedManifest).
# ALLOWED_HOSTS inclut l'hôte loopback du curl. Un seul worker suffit pour le smoke.
DEBUG=False \
ALLOWED_HOSTS="${HOST},localhost" \
ADMIN_URL="${ADMIN_URL:-admin}" \
IMPORT_ENCRYPTION_KEY="${IMPORT_ENCRYPTION_KEY:-}" \
  poetry run gunicorn config.wsgi \
    --workers 1 \
    --bind "${HOST}:${PORT}" \
    --timeout 30 \
    --access-logfile - &
GUNICORN_PID=$!

# Toujours tuer gunicorn en sortie (succès comme échec).
cleanup() {
  kill "${GUNICORN_PID}" 2>/dev/null || true
  wait "${GUNICORN_PID}" 2>/dev/null || true
}
trap cleanup EXIT

# Attend que le serveur soit prêt (jusqu'à ~30 s), puis vérifie le code HTTP.
for attempt in $(seq 1 30); do
  if ! kill -0 "${GUNICORN_PID}" 2>/dev/null; then
    echo "❌ gunicorn s'est arrêté avant de répondre (boot cassé en config prod)." >&2
    exit 1
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' "${URL}" || echo 000)"
  if [ "${code}" = "200" ]; then
    body="$(curl -s "${URL}")"
    echo "✅ /healthz/ → 200 (body: ${body})"
    exit 0
  fi
  sleep 1
done

echo "❌ /healthz/ n'a pas répondu 200 après 30 s (dernier code: ${code:-000})." >&2
exit 1
