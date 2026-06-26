#!/usr/bin/env bash
# PostToolUse hook — non-régression de la convention GitHub.
# Après une commande qui MUTE issues/PR/labels/milestones, rejoue check_convention.sh.
# - Commande non concernée → exit 0 immédiat (zéro coût réseau).
# - Violation détectée → message sur stderr + exit 2 (Claude reçoit l'alerte et corrige).
# Contrat Claude Code : stdin = JSON du tool ; exit 2 = feedback bloquant transmis au modèle.

input=$(cat)

# Extraire la commande Bash exécutée depuis tool_input.command.
cmd=$(printf '%s' "$input" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" \
  2>/dev/null)

# Ne déclencher que sur les mutations de gestion de projet (issues, PR, labels, milestones).
case "$cmd" in
  *"gh issue create"*|*"gh issue edit"* \
  |*"gh pr create"*|*"gh pr edit"* \
  |*"gh label create"*|*"gh label delete"* \
  |*"gh milestone create"*|*"gh milestone edit"*|*"gh api"*milestone*) ;;
  *) exit 0 ;;
esac

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
script="$root/.claude/skills/github/scripts/check_convention.sh"
[ -x "$script" ] || exit 0   # script absent/non exécutable → ne pas bloquer

# Borne le coût réseau : 3 appels gh API. Si GitHub est lent/hors ligne (timeout),
# convention non vérifiable ≠ violation → on ne bloque pas.
out=$(timeout 15 bash "$script" 2>&1)
rc=$?
if [ "$rc" -eq 124 ]; then
  echo "⚠️ check_convention.sh : timeout réseau (>15s) — vérification ignorée (non bloquant)." >&2
  exit 0
fi
if [ "$rc" -ne 0 ]; then
  {
    echo "⚠️ Convention GitHub violée après cette commande — à corriger :"
    echo "$out"
    echo "(détails : .claude/skills/github/SKILL.md)"
  } >&2
  exit 2
fi
exit 0
