---
name: start
description: Démarrage de session BricBudget — screening contexte, issues, état worktrees, rappel anti-stacking
---

# /workflow:start — Bootstrap de session

Exécute le screening de démarrage (équivalent enrichi de `/hello`) :

1. **Contexte projet** : lire l'en-tête de `.claude/CLAUDE.md` (stack figée, règles sécu, git workflow) et le `MEMORY.md` auto-memory.
2. **État Git** :
   ```bash
   git branch --show-current        # ⛔ si main/development → STOP, brancher
   git status --short
   git log --oneline -5
   ```
3. **Worktrees parallèles** (savoir si un autre agent bosse) :
   ```bash
   git worktree list
   ```
4. **Roadmap** : issues ouvertes (snapshot) + milestone courant. (repo solo → on liste l'ensemble, pas un filtre `--assignee` qui renverrait du vide.)
   ```bash
   unset GITHUB_TOKEN
   gh issue list --repo ManuLabricole/bric-budget --state open --limit 100 \
     --json number,title,labels,milestone --jq '.[] | "\(.number) [\(.milestone.title // "—")] \(.title)"'
   ```
5. **Rappels actifs** : 1 issue = 1 branche = 1 PR (⛔ jamais de stacking) ; PR toujours `--base development` ; Claude ne merge jamais ; vérif live GET/POST due (pas couverte par la CI).
6. **Arsenal disponible** (à mobiliser au bon moment, pas à oublier) :
   - **Gate qualité** : `rules/definition-of-done.md` (chargé par chemin sur le code) — les 4 questions d'Emmanuel à prouver avant « terminé ».
   - **Agents** : `bricbudget-reviewer` (revue), `security-auditor` (sensible), `test-auditor` (qualité tests), `silent-failure-hunter` (erreurs avalées).
   - **Skills** : `security` (design fail-closed, AVANT de coder), `github` (issues/PR/board 5-axes), `/research` `/plan` `/grill` `/simplify`, `/learn` (clore la boucle).
   - **ecc-** (global, par intention) : `ecc-django-security`, `ecc-postgres-patterns`, `ecc-security-review`, `ecc-deployment-patterns`.

Produire un résumé **HELLO** court : où on en est, sur quoi enchaîner, points de vigilance.
