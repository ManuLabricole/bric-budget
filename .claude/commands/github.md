# /github — Maintenance GitHub Project BricBudget

```
Owner  : ManuLabricole
Repo   : bric-budget
Project: 7 (BricBudget board) | PVT_kwHOBlw45M4BTJ3g
```

`unset GITHUB_TOKEN` avant toute commande `gh`.

---

## Cycle de travail — 1 issue = 1 branche = 1 PR

- Brancher depuis `development` à jour : `feature/<issue#>-<slug>`.
- ⛔ **Jamais** empiler une branche sur une autre **non mergée** (stacking = enfer de rebase, incident #125 découpée en 2 branches).
- Trop gros pour une PR ? → **2 issues distinctes**, pas 2 PRs stackées sur 1 issue.
- PR `--base development`, corps `Part of #N`. Après `gh pr create` → agent `bricbudget-reviewer` (voir plus bas).

---

## Créer une PR — labels + milestone + board OBLIGATOIRES

La PR hérite des **labels** et du **milestone de son issue**, et rejoint le board
**à la création** (pas au merge) :

```bash
unset GITHUB_TOKEN
gh issue view <N> --json labels,milestone   # récupérer labels + milestone de l'issue
gh pr create --base development \
  --title "feat(scope): ..." \
  --body "... Part of #N ..." \
  --label <label1> --label <label2> \
  --milestone "<milestone de l'issue>"
gh project item-add 7 --owner ManuLabricole --url <PR_URL>
```

⚠️ Une PR sans labels/milestone/board = PR incomplète (rappel Emmanuel 2026-06-12).

---

## Créer une issue → l'ajouter immédiatement au board

```bash
unset GITHUB_TOKEN
gh issue create --title "..." --body "..." | xargs gh project item-add 7 --owner ManuLabricole --url
```

⚠️ Ne jamais créer une issue sans l'ajouter au board dans la même commande.

---

## À la fermeture d'une issue

1. Vérifier chaque `- [ ]` dans le corps de l'issue
2. Cocher `- [x]` uniquement les tâches **réellement livrées** (lire le code)
3. Si tâches non faites → **ne pas fermer** — créer issue séparée ou laisser ouverte
4. `gh issue edit NUMBER --body "..."`

---

## À chaque merge de PR

La PR est déjà au board (ajoutée à la création). Vérifier : issues liées fermées
(manuellement, avec commentaire référençant la PR) + milestones à jour.

---

## ⛔ Revue obligatoire après chaque `gh pr create`

**Déclencher l'agent `bricbudget-reviewer`** sur le diff de la PR
(`git diff origin/development...HEAD`) : correctness, conventions Django/HTMX,
perf (N+1), tests, ET les règles SR-XX (IDOR, Decimal, atomicité, secrets, print()).
Code sensible (views / models / imports / services) → aussi `security-auditor`.

- Finding **bloquant / sécurité** → corriger **AVANT** le merge.
- Finding mineur / nit → corriger ou tracker selon le ROI.

> **Qodo est en PAUSE** sur ce compte (siège non payé) → il ne poste plus de revue.
> S'il redevient actif : lire aussi `gh pr view <N> --comments` (🐞 Bug / ⛨ Security = bloquant).

---

## Commandes de vérification rapide

```bash
# Issues fermées avec des tâches non cochées (ne devrait pas exister)
unset GITHUB_TOKEN
gh issue list --state closed --limit 30 --json number,title,body \
  | jq -r '.[] | select(.body | test("- \\[ \\]")) | "#\(.number) \(.title)"'

# Milestones et leur avancement
gh api repos/ManuLabricole/bric-budget/milestones \
  --jq '.[] | "\(.title): \(.open_issues) open / \(.closed_issues) closed"'

# Items du project board
gh project item-list 7 --owner ManuLabricole --limit 50
```
