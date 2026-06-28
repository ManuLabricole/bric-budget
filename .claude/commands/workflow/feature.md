---
name: feature
description: Cycle complet de dev d'une issue BricBudget — research → plan → GATE → wt → code/TDD → review → PR (merge = Emmanuel)
argument-hint: <issue#>
---

# /workflow:feature — Cycle complet d'une issue

Mène l'issue **#$ARGUMENTS** de bout en bout, **dans cet ordre**, sans court-circuiter le gate de plan. Chaque étape réutilise une sous-commande/skill/agent existante.

## Séquence

1. **Cadrage** — via skill `github` : `gh issue view $ARGUMENTS` (titre, labels, milestone → hérités par la PR). Le skill `github` porte la convention 5-axes — ne pas réimplémenter labels/milestone/board à la main.
2. **Research** — lancer le skill `/research` scopé à l'issue → produit `.claude/research_<slug>.md`. **Identifier le pattern existant à répliquer** (gate #3 de la Definition of Done).
3. **Grill (optionnel)** — si le concept est ambigu, lancer `/grill` (interview adversarial).
4. **Plan** — lancer `/plan` → produit `.claude/plan_<slug>.md`.
   - Si le code touche accès données / auth / argent → invoquer le skill `security` **au design** : valider l'isolation **fail-closed** (`for_user`, owner, RLS) AVANT de coder, pas au review.
   - ⛔ **GATE** : Emmanuel doit **voir et valider le plan**. **NE PAS coder sans "go" explicite.**
5. **Worktree isolé** — `/wt $ARGUMENTS <slug>` (branche depuis development, base + port dédiés). Travailler **uniquement** dans ce worktree.
6. **Code + TDD** — agent `tdd-guide` (RED d'abord) ; suivre les patterns du repo ; respecter SR-XX (IDOR `for_user`, Decimal, atomic). La rule `definition-of-done.md` est chargée par chemin → le standard est en contexte.
7. **⛔ Definition of Done — prouver, pas affirmer** (voir `rules/definition-of-done.md`) :
   - **Vérif live GET + POST** (`manage.py shell` / app réelle) — due, **non couverte par la CI**.
   - **Gate #1 tests réels** : RED vu d'abord, assert le comportement (pas le status), mock au boundary → agent `test-auditor` si le diff touche `src/tests/**`.
   - **Gate #2 simplifié** : passe d'altitude DRY/KISS/YAGNI sur mon propre diff → `/simplify` au moindre doute.
   - **Gate #3 pas de spaghetti** : je **cite le pattern répliqué** + la frontière de module.
   - **Gate #4 idiome Django** : je **nomme l'outil natif** employé (ORM/forms/atomic), aucun workaround.
   - agent `silent-failure-hunter` (échecs avalés).
   - Récap des 4 gates **prouvés** à Emmanuel → s'il doit reposer une de ses 4 questions, le gate a échoué.
8. **Revue** — enchaîner `/workflow:review` (reviewers + CodeRabbit). Ils doivent **ne rien trouver** : c'est un filet, pas le contrôle qualité.
9. **PR** — via skill `github` (labels/milestone hérités de l'issue, ajout au board, corps `Closes #N`) :
   ```bash
   unset GITHUB_TOKEN
   gh pr create --base development \
     --label <labels hérités de l'issue> --milestone "<milestone de l'issue>" \
     --title "<type>(scope): …" --body "Closes #$ARGUMENTS …"
   gh project item-add 7 --owner ManuLabricole --url <PR_URL>
   ```
10. ⛔ **STOP** — Claude ne merge **jamais**. Le merge sur `development` est réservé à Emmanuel.
11. **Apprentissage** — si un pattern réutilisable ou un piège a émergé (ou si un gate DoD a été raté) → `/learn` pour le capturer en instinct/auto-memory. Ferme la boucle.

## Garde-fous
- ⛔ Pas de stacking : si la tâche est trop grosse → 2 issues distinctes.
- ⛔ Jamais `--no-verify` (le hook le bloque). Hook bloque → corriger, recommiter.
- Après merge : `/wt-done $ARGUMENTS <slug>`.
