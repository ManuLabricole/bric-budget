#!/usr/bin/env bash
# Bloque `git commit/push --no-verify` (règle CLAUDE.md : jamais --no-verify).
# PreToolUse Bash, exit 2 = bloquant. Lecture défensive du tool_input.command.
input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
if printf '%s' "$cmd" | grep -Eq '(commit|push)([^|;&]*)--no-verify|--no-verify([^|;&]*)(commit|push)'; then
  echo "⛔ --no-verify interdit (CLAUDE.md). Corrige ce que le hook bloque, ne le contourne pas." >&2
  exit 2
fi
exit 0
