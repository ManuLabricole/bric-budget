---
name: github
description: >-
  Gestion de projet GitHub pour BricBudget — à utiliser DÈS qu'on crée, édite,
  ferme ou lie une issue ou une PR, ou qu'on touche aux milestones, labels ou au
  project board. Couvre la convention 3-axes (milestone=version, priorité=label,
  type=label), les templates issue/PR, le cycle 1 issue = 1 branche = 1 PR, le
  déclenchement de la revue, et les checks de non-régression de la convention.
---

# Gestion de projet GitHub — BricBudget

```
Owner   : ManuLabricole
Repo    : ManuLabricole/bric-budget      ⚠️ le slug N'EST PAS "BudgetTracker"
Project : 7 (board)  | PVT_kwHOBlw45M4BTJ3g
```

`unset GITHUB_TOKEN` **avant toute commande `gh`** (le token env masque le keyring valide).
En cas de doute sur le slug : `gh repo view --json nameWithOwner --jq .nameWithOwner`.

---

## ⛔ Convention 3-axes — 1 question = 1 endroit

Réconciliée le 2026-06-21. **Chaque dimension est encodée à UN seul endroit. Jamais de doublon.**

| Axe | Question | Encodage | Règle |
|-----|----------|----------|-------|
| **Milestone** | *Quand ?* (release) | `vX.Y.Z — <thème>` | **1 seul axe.** Toute issue ouverte ∈ **exactement un** milestone version. Jamais de milestone groupant par priorité ou thème sécu. |
| **Priorité** | *Urgence ?* | label `P0` / `P1` / `P2` | **Max 1** label priorité. Absence = backlog normal. Jamais la priorité dans le **nom** du milestone. |
| **Type** | *Quoi ?* | labels `feature` `chore` `refactor` `tests` `security` `infra` `bug` `documentation` | 1+ labels type. |
| **Epic** | *Regroupement* | label `epic` + issue parapluie | Pas de branche. Enfants liés via sub-issues / `Part of #N`. Porte le **milestone de la release** couverte. |

⛔ **Plus de labels `phase-*`** (le milestone EST la phase ; le label dupliquait — et contredisait — le milestone).
⛔ **Plus de milestone « Sécurité PX »** — une issue sécu = label `security` + `P0/1/2` dans un milestone **version**.
⛔ **Pas de milestone version « nu »** (`v0.5.0` sans thème) — toujours `vX.Y.Z — <thème>`.
➕ **Release intercalaire** sans renuméroter la suite → point-release (ex. `v0.4.5`).

**Vérifier la convention à tout moment :**
```bash
bash .claude/skills/github/scripts/check_convention.sh   # exit 0 propre, 1 si violation
```
> Ce check est aussi rejoué **automatiquement** par le hook `github_convention_guard.sh`
> après chaque `gh issue/pr/label/milestone` mutant (cf. `settings.json`).

---

## Cycle de travail — 1 issue = 1 branche = 1 PR

- Brancher depuis `development` à jour : `feature/<issue#>-<slug>`.
- ⛔ **Jamais** empiler une branche sur une autre non mergée (stacking = enfer de rebase, incident #125).
- Trop gros pour une PR ? → **2 issues distinctes**, pas 2 PRs stackées sur 1 issue.
- Travaux parallèles → un worktree par issue (`/wt`), jamais 2 branches empilées.

---

## Créer une issue — milestone + type + board OBLIGATOIRES

Titre `type(scope): desc`. Corps : `## Problème` / `## Tâches` (cases `- [ ]`) /
`## Critères d'acceptation`, `Part of #<epic>` si enfant. **+ milestone version + label type**
(+ priorité si pertinent), **+ ajout au board**.

```bash
unset GITHUB_TOKEN
url=$(gh issue create \
  --title "chore(infra): ..." \
  --body-file /tmp/issue.md \
  --label chore --label infra --label P1 \
  --milestone "v0.4.5 — Qualité, Tests & CI/CD")
gh project item-add 7 --owner ManuLabricole --url "$url"
```
⚠️ Jamais d'issue **sans milestone, sans label type, ou hors board**.

---

## Créer une PR — labels + milestone + board (hérités de l'issue)

```bash
unset GITHUB_TOKEN
gh issue view <N> --json labels,milestone        # hériter labels + milestone
gh pr create --base development \
  --title "feat(scope): ..." \
  --body "... Part of #N ..." \
  --label <label1> --label <label2> \
  --milestone "<milestone de l'issue>"
gh project item-add 7 --owner ManuLabricole --url <PR_URL>
```

⛔ **Toujours `--base development`**, jamais `main` (incident PR #121).
- PR feature (→ `development`) : corps `Part of #N` — **jamais `Closes`** (GitHub ne ferme que sur merge vers `main`).
- PR release (`development` → `main`) : `Closes #N1, Closes #N2` pour toutes les issues du milestone.
- ⛔ **Claude ne merge JAMAIS** — créer la PR + attendre CI verte. Merge = Emmanuel exclusivement.

---

## Revue obligatoire après chaque `gh pr create`

**Déclencher l'agent `bricbudget-reviewer`** sur le diff (`git diff origin/development...HEAD`) :
correctness, conventions Django/HTMX, perf (N+1), tests, ET règles SR-XX (IDOR, Decimal,
atomicité, secrets, print()). Code sensible (views/models/imports/services) → aussi `security-auditor`.
Finding bloquant/sécurité → corriger **avant** merge.

> **Qodo est en PAUSE** (siège non payé). Si réactivé : lire `gh pr view <N> --comments` (🐞/⛨ = bloquant).

---

## Fermer une issue

1. Vérifier chaque `- [ ]` du corps ; cocher `- [x]` uniquement les tâches **réellement livrées** (lire le code).
2. Tâches non faites → **ne pas fermer** (issue séparée ou laisser ouverte).
3. Fermer manuellement avec un commentaire référençant les PRs (le travail mergé sur `development` ne ferme pas l'issue automatiquement).

---

## Commandes de maintenance

```bash
unset GITHUB_TOKEN
# Issues fermées avec des tâches non cochées (ne devrait pas exister)
gh issue list --state closed --limit 30 --json number,title,body \
  | jq -r '.[] | select(.body | test("- \\[ \\]")) | "#\(.number) \(.title)"'
# Milestones + avancement
gh api repos/ManuLabricole/bric-budget/milestones --jq '.[] | "\(.title): \(.open_issues) open / \(.closed_issues) closed"'
# Items du board
gh project item-list 7 --owner ManuLabricole --limit 50
```
