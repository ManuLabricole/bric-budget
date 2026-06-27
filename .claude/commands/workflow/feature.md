---
name: feature
description: Cycle complet de dev d'une issue BricBudget — research → plan → GATE → wt → code/TDD → review → PR (merge = Emmanuel)
argument-hint: <issue#>
---

# /workflow:feature — Cycle complet d'une issue

Mène l'issue **#$ARGUMENTS** de bout en bout, **dans cet ordre**, sans court-circuiter le gate de plan. Chaque étape réutilise une sous-commande/skill/agent existante.

## Séquence

1. **Cadrage** — `gh issue view $ARGUMENTS` (titre, labels, milestone → serviront à la PR).
2. **Research** — lancer le skill `/research` scopé à l'issue → produit `.claude/research_<slug>.md`.
3. **Grill (optionnel)** — si le concept est ambigu, lancer `/grill` (interview adversarial).
4. **Plan** — lancer `/plan` → produit `.claude/plan_<slug>.md`.
   - ⛔ **GATE** : Emmanuel doit **voir et valider le plan**. **NE PAS coder sans "go" explicite.**
5. **Worktree isolé** — `/wt $ARGUMENTS <slug>` (branche depuis development, base + port dédiés). Travailler **uniquement** dans ce worktree.
6. **Code + TDD** — agent `tdd-guide` (RED d'abord) ; suivre les patterns du repo ; respecter SR-XX (IDOR `for_user`, Decimal, atomic).
7. **Vérif avant "terminé"** :
   - vérif live GET + POST (`manage.py shell` / app réelle) — **due, non couverte par la CI** ;
   - agent `silent-failure-hunter` (échecs avalés) ; agent `bricbudget-reviewer` ;
   - si views/models/imports/services → agent `security-auditor`.
8. **Revue** — enchaîner `/workflow:review` (reviewers + CodeRabbit).
9. **PR** :
   ```bash
   unset GITHUB_TOKEN
   gh pr create --base development \
     --label <labels hérités de l'issue> --milestone "<milestone de l'issue>" \
     --title "<type>(scope): …" --body "Closes #$ARGUMENTS …"
   gh project item-add 7 --owner ManuLabricole --url <PR_URL>
   ```
10. ⛔ **STOP** — Claude ne merge **jamais**. Le merge sur `development` est réservé à Emmanuel.

## Garde-fous
- ⛔ Pas de stacking : si la tâche est trop grosse → 2 issues distinctes.
- ⛔ Jamais `--no-verify` (le hook le bloque). Hook bloque → corriger, recommiter.
- Après merge : `/wt-done $ARGUMENTS <slug>`.
