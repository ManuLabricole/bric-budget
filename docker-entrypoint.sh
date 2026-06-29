#!/bin/sh
# docker-entrypoint.sh — corrige les permissions du volume Railway, puis DÉGRADE les privilèges.
#
# Pourquoi ce fichier :
#   Le conteneur applicatif tourne en utilisateur NON privilégié (appuser, uid 10001) par sécurité
#   (cf. Dockerfile, section « user non-root »). Mais un Railway Volume est monté en root:root au
#   démarrage → l'app non-root ne peut pas y créer de dossier : `mkdir /mnt/imports/...` lève
#   PermissionError [Errno 13] (cause du 500 sur /import/confirm/).
#
#   Patron Docker standard (images officielles postgres / redis / mysql) :
#     1. l'entrypoint démarre en root UNIQUEMENT le temps de chown le point de montage,
#     2. puis `exec gosu appuser` relâche les privilèges et lance le process applicatif.
#   → L'application ne tourne JAMAIS en root. Pas de RAILWAY_RUN_UID=0 (= conteneur root = workaround).
set -e

# IMPORT_STORAGE_ROOT est fixé à /mnt/imports sur Railway (env var). On le relit ici pour chowner le
# bon chemin, avec /mnt/imports comme défaut. Le garde `-d` évite de chowner en dev local quand le
# dossier de stockage est ailleurs (déjà possédé par appuser, chowné dans le Dockerfile).
STORAGE_ROOT="${IMPORT_STORAGE_ROOT:-/mnt/imports}"
if [ -d "$STORAGE_ROOT" ]; then
    # -R : couvre aussi d'éventuels fichiers root-owned hérités d'un ancien run en root.
    chown -R appuser:appuser "$STORAGE_ROOT"
fi

# Relâche les privilèges : le reste (migrate + seed + gunicorn) tourne en appuser.
exec gosu appuser "$@"
