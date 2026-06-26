#!/usr/bin/env bash
# scripts/db_prod_backup.sh — Dump horodaté de la DB PROD (Railway). (#257, plancher #216)
#
# Pourquoi un script dédié (≠ `make backup` qui vise le Docker local) :
#   la prod n'est PAS le container `bricbudget-db`. On se connecte à Railway via
#   l'URL de connexion PUBLIQUE (proxy) et on dumpe avec un client pg conteneurisé
#   (zéro dépendance locale, version pinnable pour matcher le serveur).
#
# Usage :
#   PROD_DATABASE_URL='postgresql://USER:PWD@HOST.proxy.rlwy.net:PORT/railway' \
#     bash scripts/db_prod_backup.sh
#   (ou: make prod-backup)
#
# ⚠️ PROD_DATABASE_URL contient un secret → la passer EN LIGNE (jamais committée,
#    jamais dans un fichier suivi). La récupérer : Railway → service Postgres →
#    onglet « Connect » → « Public Network » (host en .proxy.rlwy.net).
#
# Le dump (.sql.gz) atterrit dans backups/ (gitignoré) = DONNÉES SENSIBLES :
# ne jamais committer, ne jamais partager en clair.
set -euo pipefail

PG_IMAGE_TAG="${PG_IMAGE_TAG:-16}"  # matcher la version Postgres de Railway
BACKUP_DIR="backups"

if [ -z "${PROD_DATABASE_URL:-}" ]; then
    echo "❌ PROD_DATABASE_URL manquante." >&2
    echo "   Récupère l'URL publique : Railway → Postgres → Connect → Public Network." >&2
    echo "   Puis : PROD_DATABASE_URL='postgresql://…@….proxy.rlwy.net:PORT/railway' make prod-backup" >&2
    exit 1
fi

# Garde-fou : une URL .railway.internal ne marche QUE depuis le réseau Railway.
case "$PROD_DATABASE_URL" in
    *railway.internal*)
        echo "❌ URL interne (.railway.internal) détectée — injoignable depuis ta machine." >&2
        echo "   Utilise l'URL PUBLIQUE (host .proxy.rlwy.net) de l'onglet Connect." >&2
        exit 1
        ;;
esac

mkdir -p "$BACKUP_DIR"
ts="$(date +%Y%m%d_%H%M%S)"
out="$BACKUP_DIR/prod_${ts}.sql.gz"

echo "💾 Dump PROD → $out (pg_dump via postgres:${PG_IMAGE_TAG})…"
# set -e + pipefail : un pg_dump qui échoue (auth/réseau) sort AVANT le size-check
# et laisserait un $out tronqué. Le trap supprime le dump partiel sur tout chemin
# d'erreur ; on le désarme à la toute fin une fois le fichier validé.
trap 'rm -f "$out"' EXIT
# --clean --if-exists : le dump se restaure sur une base existante sans erreur.
# --no-owner --no-privileges : restaurable dans une DB scratch sans rejouer les rôles.
# -e PROD_DATABASE_URL : on passe le NOM de la variable (sa valeur secrète vient de
# l'env du shell), jamais l'URL en argv → invisible dans `ps aux`. sh -c la déréférence
# DANS le conteneur, où elle n'apparaît pas non plus dans la table des process hôte.
docker run --rm -i -e PROD_DATABASE_URL "postgres:${PG_IMAGE_TAG}" \
    sh -c 'pg_dump "$PROD_DATABASE_URL" --clean --if-exists --no-owner --no-privileges' \
    | gzip > "$out"

# Un dump qui a échoué silencieusement (auth, réseau) produit un fichier minuscule.
size_bytes="$(wc -c < "$out" | tr -d ' ')"
if [ "$size_bytes" -lt 1024 ]; then
    echo "❌ Dump suspect (${size_bytes} octets) — échec probable (auth/réseau/version). Fichier laissé pour inspection : $out" >&2
    exit 1
fi

# Dump validé → on désarme le trap pour CONSERVER le fichier.
trap - EXIT
echo "✅ Backup PROD créé : $out ($(du -h "$out" | cut -f1))"
echo "   ⚠️ Données sensibles — gitignoré, ne jamais committer/partager."
echo "   Restauration testée : voir le runbook (ops.md → « Restore testée »)."
