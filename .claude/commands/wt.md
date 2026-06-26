# /wt — Ouvrir un worktree isolé pour résoudre une issue en parallèle

> Usage : `/wt <issue#> <slug>`   (ex. `/wt 144 settings-split`)
> Permet de mener **plusieurs PR de front**, chaque session Claude Code dans son
> propre répertoire, sa propre base Postgres, son propre port. Zéro collision, zéro
> stacking (cf. `commands/github.md` — règle 1 issue = 1 branche = 1 PR).

---

## Étapes

```bash
unset GITHUB_TOKEN
# 1. Récupérer le contexte de l'issue (sert pour la PR plus tard : labels + milestone).
gh issue view <issue#> --json number,title,labels,milestone

# 2. Créer le worktree isolé (branche depuis origin/development, DB + port dédiés).
scripts/wt-new.sh <issue#> <slug>
```

Le script gère **A** branche `feature/<issue>-<slug>` depuis `origin/development`,
**B** base `bric_wt_<issue>` (migrée), **C** `.venv`/`node_modules` symlinkés +
port `8000 + (issue % 1000)`.

## Ensuite — lancer la session parallèle

```bash
cd ../.bric-worktrees/<issue>-<slug>
claude                      # session Claude Code isolée pour cette issue
make run PORT=<port>        # serveur dev (port affiché par le script)
```

### Briefer la session worktree (1 session = 1 issue)

Dans la nouvelle session Claude, donner un prompt **scopé à l'unique issue**, ex. :

> Tu es dans le worktree de l'**issue #144**. Lis-la (`gh issue view 144`), fais
> `/research` puis `/plan`, puis implémente **uniquement** cette issue. Reste dans
> ce dossier. Vérif live GET/POST avant de déclarer terminé. À la fin :
> `gh pr create --base development` (labels/milestone hérités) + agent
> `bricbudget-reviewer`. Ne touche pas aux autres issues.

Une session ne connaît que SON issue → pas de contamination entre les travaux parallèles.

## Discipline parallèle (humain)

- Avant de lancer un lot, vérifier que les issues touchent des **fichiers disjoints**
  (frontières de domaine). Deux worktrees sur les mêmes fichiers = conflit au merge.
- Le cycle PR ne change pas : `gh pr create --base development` + labels/milestone
  **hérités de l'issue** + `gh project item-add 7` + agent `bricbudget-reviewer`
  (+ `security-auditor` si views/models/imports/services). Voir `commands/github.md`.
- PR mergée → `/wt-done <issue#> <slug>` pour le teardown.

> ⚠️ Ne PAS utiliser `claude --worktree` nu : il branche depuis `main`, pas
> `development`. Toujours passer par `/wt`.
