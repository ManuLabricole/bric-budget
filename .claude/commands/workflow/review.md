---
name: review
description: Cycle de revue d'une PR BricBudget — bricbudget-reviewer + security-auditor + traitement obligatoire de CodeRabbit
argument-hint: [PR#]
---

# /workflow:review — Cycle de revue

Revue complète avant merge. Cible : la PR courante (ou **#$ARGUMENTS** si fourni).

## 1. Revue par agents (sur le diff)
```bash
git diff origin/development...HEAD
```
- Agent **`bricbudget-reviewer`** : correctness, Django/HTMX, perf (N+1), tests, SR-XX.
- Si le diff touche `views/`, `models/`, `imports/`, `services/` → agent **`security-auditor`** (IDOR, Decimal, atomicité, secrets, OWASP).
- Findings bloquants/sécu → **corriger avant merge** (commit + push re-déclenche la CI + CodeRabbit).

## 2. CodeRabbit (obligatoire — le cycle n'est pas fini sans 🐰)
1. Attendre `CodeRabbit … Review completed` : `gh pr checks <PR>` (re-tourne à chaque push).
2. Lire ses commentaires **+ les « 🤖 Prompt for AI Agents » + findings *outside-diff*** :
   ```bash
   unset GITHUB_TOKEN
   gh pr view <PR> --json reviews
   gh api repos/ManuLabricole/bric-budget/pulls/<PR>/comments
   ```
3. **Juger chaque suggestion** : pertinente → implémenter (commit + push) ; hors scope / déjà couverte → écarter **avec raison brève**. Jamais en masse aveugle.
4. Vérifier `[ "$(git rev-list --count origin/<branch>..HEAD)" -ge 1 ]` après chaque commit (le formateur pre-commit peut l'avaler).
5. Récap à Emmanuel : finding → action.

## 3. Gate final
- Auto-OK si : tests 100% verts + 0 ruff + 0 IDOR sans `for_user` + 0 `print()`.
- ⛔ Claude ne merge **jamais** — le merge est réservé à Emmanuel.
