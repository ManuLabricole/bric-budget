#!/usr/bin/env bash
# Empêche d'affaiblir les configs linter/formatter (steer : corrige le code, pas l'outil).
# PreToolUse Edit|Write|MultiEdit, exit 2 = bloquant. Échappatoire : ECC_ALLOW_CONFIG_EDIT=1.
input=$(cat)
path=$(printf '%s' "$input" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
case "$path" in
  *pyproject.toml|*ruff.toml|*.ruff.toml|*setup.cfg|*.pre-commit-config.yaml|*.flake8|*mypy.ini)
    if [ "$ECC_ALLOW_CONFIG_EDIT" = "1" ]; then
      exit 0
    fi
    echo "⛔ Modif de config linter ($path) bloquée. Corrige le code, n'affaiblis pas l'outil. (override : ECC_ALLOW_CONFIG_EDIT=1)" >&2
    exit 2
    ;;
esac
exit 0
