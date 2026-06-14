#!/usr/bin/env bash
# =============================================================================
# wt-new.sh — crée un worktree ISOLÉ pour résoudre une issue en parallèle.
#
# Usage : scripts/wt-new.sh <issue#> <slug>
# Ex.   : scripts/wt-new.sh 144 settings-split
#
# Ce qu'il garantit (les 3 collisions du multi-Claude) :
#   A. branche depuis origin/development (jamais main, jamais stacking)   → feature/<issue>-<slug>
#   B. base Postgres DÉDIÉE dans le container bricbudget-db               → bric_wt_<issue>
#   C. deps partagées (.venv + node_modules symlinkés) + port runserver  → 8000 + (issue % 1000)
#
# POURQUOI ça suffit pour isoler la DB : decouple.config() résout .env à partir
# de l'emplacement de settings.py. Dans le worktree, c'est le .env DU WORKTREE
# (avec sa propre DATABASE_URL) qui est lu → migrate/pytest tapent la base dédiée.
# =============================================================================
set -euo pipefail

ISSUE="${1:-}"
SLUG="${2:-}"
if [[ -z "$ISSUE" || -z "$SLUG" ]]; then
  echo "❌ Usage : scripts/wt-new.sh <issue#> <slug>   (ex. scripts/wt-new.sh 144 settings-split)" >&2
  exit 1
fi
if ! [[ "$ISSUE" =~ ^[0-9]+$ ]]; then
  echo "❌ <issue#> doit être numérique (reçu : '$ISSUE')" >&2
  exit 1
fi

# --- Chemins & noms dérivés ---------------------------------------------------
MAIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # racine du repo principal
WT_ROOT="$(cd "$MAIN/.." && pwd)/.bric-worktrees"           # sibling HORS repo
WT_DIR="$WT_ROOT/${ISSUE}-${SLUG}"
BRANCH="feature/${ISSUE}-${SLUG}"
DB="bric_wt_${ISSUE}"
PORT=$((8000 + (ISSUE % 1000)))
PG_CONTAINER="bricbudget-db"

echo "🌳 Worktree : $WT_DIR"
echo "   branche  : $BRANCH (depuis origin/development)"
echo "   base     : $DB        port runserver : $PORT"
echo

# --- Garde-fous ---------------------------------------------------------------
if [[ -e "$WT_DIR" ]]; then
  echo "❌ $WT_DIR existe déjà. Teardown d'abord : scripts/wt-rm.sh $ISSUE $SLUG" >&2
  exit 1
fi
if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "❌ La branche $BRANCH existe déjà. Choisis un autre slug ou supprime-la." >&2
  exit 1
fi
if ! docker inspect -f '{{.State.Health.Status}}' "$PG_CONTAINER" 2>/dev/null | grep -q healthy; then
  echo "❌ Container $PG_CONTAINER pas 'healthy'. Lance d'abord : make up" >&2
  exit 1
fi

# --- A. Worktree depuis origin/development ------------------------------------
mkdir -p "$WT_ROOT"
git -C "$MAIN" fetch origin --quiet
git -C "$MAIN" worktree add "$WT_DIR" -b "$BRANCH" origin/development
echo "✅ A — worktree créé sur $BRANCH"

# --- C. Deps partagées (symlinks) ---------------------------------------------
# .venv et node_modules sont gitignorés → absents du checkout neuf → symlink propre.
ln -s "$MAIN/.venv" "$WT_DIR/.venv"
ln -s "$MAIN/node_modules" "$WT_DIR/node_modules"
# Les patterns .gitignore à slash final (.venv/ node_modules/) NE matchent PAS un
# symlink → sans ça ils apparaissent en "untracked" et risquent un commit accidentel.
# On les exclut via le info/exclude partagé du repo (idempotent).
EXCLUDE="$(git -C "$WT_DIR" rev-parse --path-format=absolute --git-path info/exclude)"
grep -qxF '/.venv' "$EXCLUDE" 2>/dev/null || printf '/.venv\n/node_modules\n' >> "$EXCLUDE"
echo "✅ C — .venv + node_modules symlinkés (deps partagées, 0 install) + exclus de git"

# --- B. .env du worktree avec DATABASE_URL dédiée -----------------------------
cp "$MAIN/.env" "$WT_DIR/.env"
python3 - "$WT_DIR/.env" "$DB" <<'PY'
import sys, urllib.parse
env_path, db = sys.argv[1], sys.argv[2]
lines = open(env_path).read().splitlines()
out, found = [], False
for ln in lines:
    if ln.startswith("DATABASE_URL="):
        found = True
        url = ln[len("DATABASE_URL="):].strip()
        if url:
            u = urllib.parse.urlsplit(url)
            ln = "DATABASE_URL=" + urllib.parse.urlunsplit(u._replace(path="/" + db))
        else:
            ln = f"DATABASE_URL=postgresql://bricbudget:bricbudget@localhost:5433/{db}"
    out.append(ln)
if not found:
    out.append(f"DATABASE_URL=postgresql://bricbudget:bricbudget@localhost:5433/{db}")
open(env_path, "w").write("\n".join(out) + "\n")
PY

# Création de la base dédiée (idempotent).
if docker exec "$PG_CONTAINER" psql -U bricbudget -tAc \
     "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  echo "ℹ️  base $DB déjà présente — réutilisée"
else
  docker exec "$PG_CONTAINER" createdb -U bricbudget "$DB"
  echo "✅ B — base $DB créée dans $PG_CONTAINER"
fi

# --- Migrate sur la base dédiée -----------------------------------------------
echo "🔄 migrate sur $DB..."
( cd "$WT_DIR" && "$MAIN/.venv/bin/python" src/manage.py migrate --no-input )
echo "✅ migrations appliquées"

# --- Récap --------------------------------------------------------------------
cat <<EOF

╭─────────────────────────────────────────────────────────────╮
│ Worktree prêt — issue #$ISSUE
├─────────────────────────────────────────────────────────────
│ 📂 cd $WT_DIR
│ 🤖 claude                 # lance une session Claude Code isolée
│ 🌐 make run PORT=$PORT     # serveur dev sur http://localhost:$PORT
│ 🧪 make test              # pytest sur la base test_$DB (isolée)
│ 🎨 npm run build:css      # SI tu touches des templates (sinon nouvelles classes Tailwind ignorées)
├─────────────────────────────────────────────────────────────
│ Fini & mergé ? → scripts/wt-rm.sh $ISSUE $SLUG
╰─────────────────────────────────────────────────────────────╯
EOF
