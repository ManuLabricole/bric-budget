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
# -e : on stoppe au premier échec (jamais continuer en root après une erreur).
# -u : une variable non définie est une erreur (attrape un typo sur IMPORT_STORAGE_ROOT).
set -eu

# IMPORT_STORAGE_ROOT est fixé à /mnt/imports sur Railway (env var). On le relit ici pour chowner le
# bon chemin, avec /mnt/imports comme défaut.
STORAGE_ROOT="${IMPORT_STORAGE_ROOT:-/mnt/imports}"

# Si on ne démarre PAS en root (ex. plateforme qui impose déjà un uid non privilégié — k8s
# runAsNonRoot, sandbox), on ne peut ni chowner ni gosu : on lance le CMD tel quel. L'app reste
# non-root dans les deux modes de lancement.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

# Démarré en root : on corrige la propriété du point de montage du volume (monté root:root) pour que
# l'app non-root puisse y créer ses dossiers.
#   - garde `-d`      : pas de volume en dev local → on ne chowne rien.
#   - garde `!= "/"`  : filet anti-catastrophe si IMPORT_STORAGE_ROOT est mal configuré (jamais chowner /).
#   - -R              : couvre aussi d'éventuels fichiers root-owned hérités d'un ancien run.
#   - échec explicite : sans ça, `set -e` ferait crasher le conteneur SANS log actionnable (juste un
#                       exit 1 opaque), pire à débugger sur Railway que le PermissionError d'origine.
if [ "$STORAGE_ROOT" != "/" ] && [ -d "$STORAGE_ROOT" ]; then
    chown -R appuser:appuser "$STORAGE_ROOT" \
        || { echo "[entrypoint] ERREUR : chown de $STORAGE_ROOT a échoué" >&2; exit 1; }
fi

# Vérifie que gosu est fonctionnel (binaire/architecture) AVANT de s'en remettre à lui pour lancer
# l'app — pattern de l'image officielle postgres. Échoue tôt et lisiblement plutôt qu'au runtime.
gosu appuser true

# Relâche les privilèges : le reste (migrate + seed + gunicorn) tourne en appuser (uid 10001).
exec gosu appuser "$@"
