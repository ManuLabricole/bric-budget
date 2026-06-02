#!/usr/bin/env bash
# guard_protected_branch.sh — blocks DIRECT commits on protected branches.
#
# Why: main/development must only receive merges (via PR / `git merge`), never
# direct edits. Work happens on feature branches. This enforces the CLAUDE.md
# rule "⛔ jamais sur main" mechanically instead of relying on memory.
#
# Invoked by pre-commit at the `pre-commit` stage (no args) → checks the current
# branch. Does NOT fire on `git merge` (that triggers pre-merge-commit, not
# pre-commit), so merging into development still works.
#
# Test mode: pass a branch name as $1 to simulate (e.g. `... main`).
set -euo pipefail

branch="${1:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')}"

case "$branch" in
  main | development)
    echo "⛔ Commit direct interdit sur '$branch'." >&2
    echo "   → crée une feature branch :  git checkout -b feature/<slug>" >&2
    echo "   (main/development ne reçoivent que des merges via PR)" >&2
    exit 1
    ;;
esac

exit 0
