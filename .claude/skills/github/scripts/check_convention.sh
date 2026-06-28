#!/usr/bin/env bash
# check_convention.sh — Vérifie la convention GitHub de BricBudget (v2).
# Source de vérité : .claude/skills/github/SKILL.md
# Exit 0 = convention respectée, 1 = au moins une violation.
#
# Modèle (v2) : milestone = release PRODUIT ; epic = FOYER de l'issue ; priorité ;
# type ; statut board. Le milestone version n'est posé QUE quand l'issue est
# planifiée dans une release concrète → le transverse non planifié vit sous son
# epic (label `epic` ou `Part of #N`), SANS milestone.
#
# 4 checks (état du repo, pas du diff) :
#   1. Toute issue ouverte a un FOYER : milestone OU lien epic (label epic / Part of #N).
#   2. Aucune issue n'a >1 label priorité (P0/P1/P2).
#   3. Aucun label phase-* ne subsiste (le milestone EST la phase).
#   4. v0.4.5 est GELÉ : aucune issue ouverte ne doit y être rattachée (fourre-tout retiré).

# Robustesse : -u (variable non définie = erreur), pipefail (échec d'un pipe propagé).
# Pas de -e : on gère explicitement fail=1 pour agréger les violations.
set -uo pipefail

unset GITHUB_TOKEN
fail=0

FROZEN_MS="v0.4.5 — Qualité, Tests & CI/CD"

# 1 — issues ouvertes SANS FOYER : ni milestone, ni label epic, ni 'Part of #N' dans le corps.
#     (epic = foyer ; le milestone n'est obligatoire que pour une issue planifiée en release.)
orphans=$(gh issue list --state open --limit 300 --json number,milestone,labels,body --jq '
  .[]
  | select(.milestone == null)
  | select((.labels | map(.name) | index("epic")) == null)
  | select((.body // "") | test("(?i)part of #[0-9]+") | not)
  | "#\(.number)"' 2>/dev/null)
if [ -n "$orphans" ]; then
  echo "❌ Issues SANS foyer (ni milestone, ni epic, ni 'Part of #N') : ${orphans//$'\n'/ }"
  echo "   → rattacher à un epic ('Part of #N') ou poser un milestone de release."
  fail=1
fi

# 2 — issues avec >1 label priorité
dup_p=$(gh issue list --state open --limit 300 --json number,labels \
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

# 4 — v0.4.5 gelé : plus aucune issue ouverte rattachée (le fourre-tout a été éclaté).
frozen=$(gh issue list --state open --limit 300 --milestone "$FROZEN_MS" --json number \
  --jq '.[] | "#\(.number)"' 2>/dev/null)
if [ -n "$frozen" ]; then
  echo "❌ Issues encore dans le milestone GELÉ « $FROZEN_MS » : ${frozen//$'\n'/ }"
  echo "   → ce milestone est historique : rattacher ces issues à leur epic, retirer le milestone."
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✅ Convention GitHub respectée (foyer présent, priorité unique, 0 phase-*, v0.4.5 gelé)."
fi
exit $fail
