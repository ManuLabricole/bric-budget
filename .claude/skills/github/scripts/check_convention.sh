#!/usr/bin/env bash
# check_convention.sh — Vérifie la convention 3-axes GitHub de BricBudget.
# Source de vérité : .claude/skills/github/SKILL.md
# Exit 0 = convention respectée, 1 = au moins une violation.
#
# 3 checks (état du repo, pas du diff) :
#   1. Toute issue ouverte a un milestone (version).
#   2. Aucune issue n'a >1 label priorité (P0/P1/P2).
#   3. Aucun label phase-* ne subsiste (le milestone EST la phase).

# Robustesse : -u (variable non définie = erreur), pipefail (échec d'un pipe propagé).
# Pas de -e : on gère explicitement fail=1 pour agréger les violations.
set -uo pipefail

unset GITHUB_TOKEN
fail=0

# 1 — issues ouvertes sans milestone
no_ms=$(gh issue list --state open --limit 200 --json number,milestone \
  --jq '.[] | select(.milestone == null) | "#\(.number)"' 2>/dev/null)
if [ -n "$no_ms" ]; then
  echo "❌ Issues ouvertes SANS milestone : ${no_ms//$'\n'/ }"
  fail=1
fi

# 2 — issues avec >1 label priorité
dup_p=$(gh issue list --state open --limit 200 --json number,labels \
  --jq '.[] | {n: .number, p: [.labels[].name | select(test("^P[0-9]$"))]} | select(.p | length > 1) | "#\(.n) \(.p)"' 2>/dev/null)
if [ -n "$dup_p" ]; then
  echo "❌ Issues avec >1 label priorité :"
  echo "$dup_p"
  fail=1
fi

# 3 — labels phase-* résiduels
phase=$(gh label list --limit 200 2>/dev/null | grep -iE '^phase' )
if [ -n "$phase" ]; then
  echo "❌ Labels phase-* résiduels (à supprimer) :"
  echo "$phase"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✅ Convention GitHub respectée (milestone présent, priorité unique, 0 label phase-*)."
fi
exit $fail
