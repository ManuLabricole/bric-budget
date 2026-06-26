# /wt-list — Vue d'ensemble des worktrees parallèles

> Usage : `/wt-list`
> Le « cockpit » : tous les worktrees actifs d'un coup d'œil (branche, port, base,
> commits d'avance sur development, fichiers non commités).

```bash
scripts/wt-list.sh
```

Sert à : retrouver le **port** d'un worktree (pour ouvrir l'UI), repérer un worktree
**sale** (travail non commité) ou **en retard**, avant un merge ou un teardown.
