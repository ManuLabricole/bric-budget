#!/usr/bin/env bash
# =============================================================================
# wt-list.sh — vue d'ensemble de tous les worktrees parallèles (cockpit-lite).
#
# Usage : scripts/wt-list.sh
#
# Pour chaque worktree dans ../.bric-worktrees/ : branche, port, base, et état
# (commits d'avance sur development + fichiers non commités). Remplace le fait
# de jongler entre N terminaux sans savoir où on en est.
# =============================================================================
set -euo pipefail

MAIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT_ROOT="$(cd "$MAIN/.." && pwd)/.bric-worktrees"

if [[ ! -d "$WT_ROOT" ]] || [[ -z "$(ls -A "$WT_ROOT" 2>/dev/null)" ]]; then
  echo "Aucun worktree actif. Crée-en un : /wt <issue#> <slug>"
  exit 0
fi

git -C "$MAIN" fetch origin --quiet 2>/dev/null || true

printf "%-22s %-26s %-6s %-16s %-8s %s\n" "WORKTREE" "BRANCHE" "PORT" "BASE" "AVANCE" "ÉTAT"
printf "%-22s %-26s %-6s %-16s %-8s %s\n" "────────" "───────" "────" "────" "──────" "────"

for d in "$WT_ROOT"/*/; do
  [[ -d "$d" ]] || continue
  name="$(basename "$d")"
  issue="${name%%-*}"                         # NNNN-slug → NNNN
  branch="$(git -C "$d" branch --show-current 2>/dev/null || echo '?')"
  if [[ "$issue" =~ ^[0-9]+$ ]]; then
    port=$((8000 + (issue % 1000)))
    db="bric_wt_${issue}"
  else
    port="-"; db="-"
  fi
  ahead="$(git -C "$d" rev-list --count "origin/development..HEAD" 2>/dev/null || echo '?')"
  dirty=$(git -C "$d" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$dirty" -gt 0 ]]; then state="✏️  $dirty non commité(s)"; else state="✅ propre"; fi
  printf "%-22s %-26s %-6s %-16s %-8s %s\n" "$name" "$branch" "$port" "$db" "+$ahead" "$state"
done

echo
echo "Détail d'un worktree : git -C ../.bric-worktrees/<name> diff"
