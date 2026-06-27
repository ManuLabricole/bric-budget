#!/usr/bin/env bash
# Bloque `git commit/push --no-verify` (règle CLAUDE.md : jamais --no-verify).
# PreToolUse Bash, exit 2 = bloquant. Lecture défensive du tool_input.command.
input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
# Retirer le contenu entre quotes (messages de commit) AVANT d'analyser les flags,
# sinon un message contenant "-n" ou "--no-verify" déclenche un faux positif.
stripped=$(printf '%s' "$cmd" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")
# Forme longue --no-verify (commit ET push).
if printf '%s' "$stripped" | grep -Eq '(commit|push)([^|;&]*)--no-verify|--no-verify([^|;&]*)(commit|push)'; then
  echo "⛔ --no-verify interdit (CLAUDE.md). Corrige ce que le hook bloque, ne le contourne pas." >&2
  exit 2
fi
# Alias court -n de `git commit` (push n'a pas de -n).
if printf '%s' "$stripped" | grep -Eq '\bgit[[:space:]]+commit\b[^|;&]*[[:space:]]-n([[:space:]]|$)'; then
  echo "⛔ 'git commit -n' (alias de --no-verify) interdit (CLAUDE.md). Corrige ce que le hook bloque, ne le contourne pas." >&2
  exit 2
fi
exit 0
