#!/usr/bin/env bash
# stamp_claude_version.sh — appends the .claude config version as a git trailer.
#
# Invoked by pre-commit at the `prepare-commit-msg` stage (see .pre-commit-config.yaml).
# pre-commit passes the path to the commit message file as $1.
#
# Why: every commit becomes traceable to the .claude config version it was made
# under, via a `Claude-Config: vX.Y.Z` footer (read from .claude/VERSION).
# Idempotent (safe on --amend/rebase) and never blocks a commit.
set -euo pipefail

msg_file="${1:-}"
[ -n "$msg_file" ] || exit 0
[ -f "$msg_file" ] || exit 0

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
version_file="$repo_root/.claude/VERSION"
[ -f "$version_file" ] || exit 0

version="$(tr -d '[:space:]' < "$version_file")"
[ -n "$version" ] || exit 0

# Idempotent: don't double-stamp if a trailer is already present.
if grep -q '^Claude-Config:' "$msg_file"; then
  exit 0
fi

printf '\nClaude-Config: v%s\n' "$version" >> "$msg_file"
exit 0
