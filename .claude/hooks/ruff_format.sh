#!/usr/bin/env bash
# PostToolUse hook — ruff format automatique du fichier Python édité par Claude.
# Claude Code passe le contexte de l'outil en JSON sur stdin ; on lit tool_input.file_path.
# Silencieux et non bloquant (exit 0 toujours) : le formatage ne doit jamais casser le flux.

input=$(cat)

# Extraire le chemin du fichier édité (Edit/Write/MultiEdit) depuis le JSON stdin.
file=$(printf '%s' "$input" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" \
  2>/dev/null)

# Rien à faire si pas de fichier, pas un .py, ou fichier absent.
[ -z "$file" ] && exit 0
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

# Trouver ruff : venv racine, sinon poetry, sinon PATH.
root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
if [ -x "$root/.venv/bin/ruff" ]; then
  "$root/.venv/bin/ruff" format "$file" >/dev/null 2>&1 || true
elif command -v poetry >/dev/null 2>&1 && [ -d "$root/src" ]; then
  (cd "$root/src" && poetry run ruff format "$file" >/dev/null 2>&1) || true
elif command -v ruff >/dev/null 2>&1; then
  ruff format "$file" >/dev/null 2>&1 || true
fi

exit 0
