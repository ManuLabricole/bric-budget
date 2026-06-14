#!/usr/bin/env bash
# =============================================================================
# wt-rm.sh — teardown d'un worktree après merge de sa PR.
#
# Usage : scripts/wt-rm.sh <issue#> <slug>
# Ex.   : scripts/wt-rm.sh 144 settings-split
#
# Supprime : worktree + branche locale + base Postgres dédiée + entrée prune.
# À lancer UNIQUEMENT quand la PR est mergée sur development (sinon perte de code).
# =============================================================================
set -euo pipefail

ISSUE="${1:-}"
SLUG="${2:-}"
if [[ -z "$ISSUE" || -z "$SLUG" ]]; then
  echo "❌ Usage : scripts/wt-rm.sh <issue#> <slug>" >&2
  exit 1
fi

MAIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT_DIR="$(cd "$MAIN/.." && pwd)/.bric-worktrees/${ISSUE}-${SLUG}"
BRANCH="feature/${ISSUE}-${SLUG}"
DB="bric_wt_${ISSUE}"
PG_CONTAINER="bricbudget-db"

echo "🗑️  Teardown worktree #$ISSUE ($BRANCH)"

# Avertir si du travail non commité traîne (ne pas supprimer en silence).
if [[ -d "$WT_DIR" ]]; then
  if [[ -n "$(git -C "$WT_DIR" status --porcelain)" ]]; then
    echo "⚠️  $WT_DIR a des changements non commités — ils vont être PERDUS." >&2
    read -r -p "    Continuer ? [y/N] " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Annulé."; exit 1; }
  fi
  git -C "$MAIN" worktree remove --force "$WT_DIR"
  echo "✅ worktree supprimé"
else
  echo "ℹ️  $WT_DIR absent — rien à retirer côté worktree"
fi

git -C "$MAIN" worktree prune

if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$MAIN" branch -D "$BRANCH"
  echo "✅ branche locale $BRANCH supprimée"
fi

docker exec "$PG_CONTAINER" dropdb -U bricbudget --if-exists "$DB"
echo "✅ base $DB supprimée"

echo "🧹 Teardown terminé pour #$ISSUE"
