---
name: parallel
description: Dispatch multi-worktrees — mener plusieurs issues de front, 1 worktree isolé + 1 sous-agent background par issue
argument-hint: <issue#> <issue#> …
---

# /workflow:parallel — Dispatch multi-worktrees

Lance plusieurs issues **en parallèle**, chacune totalement isolée. Issues visées : **#$ARGUMENTS**.

## Pré-vol (obligatoire)
- Vérifier que les issues touchent des **fichiers disjoints** (frontières de domaine). Deux worktrees sur les mêmes fichiers = conflit au merge → refuser et séquencer à la place.
- ⛔ Anti-stacking : chaque issue = sa branche depuis `development`, jamais empilée.

## Pour CHAQUE issue
1. Créer le worktree : `/wt <issue#> <slug>` (branche, base `bric_wt_<N>`, port `8<N>`).
2. Déléguer à **un sous-agent `general-purpose` en background** (PAS `isolation:worktree` — le worktree existe déjà), briefé **uniquement** sur son issue :
   > Tu es dans le worktree de l'issue #N (`../.bric-worktrees/N-slug`). Reste dans ce dossier. `/research` (identifie le pattern à répliquer) → `/plan` → **⛔ STOP : attendre le "go" explicite d'Emmanuel avant de coder, ne pas continuer sans réponse** → code (TDD) → **gate Definition of Done prouvé** (`rules/definition-of-done.md` : tests réels non-théâtre via `test-auditor`, diff simplifié, pattern cité, idiome Django) → vérif live GET/POST → `gh pr create --base development` + `bricbudget-reviewer` (+ `security-auditor` si sensible). Ne touche à aucune autre issue.
3. Ne pas mélanger les contextes : 1 sous-agent = 1 issue.

## Suivi
- Récapituler l'avancement de chaque branche (PR ✅/❌).
- Pousser les branches **en série** (le pre-push pytest concurrent collisionne sur `test_bricbudget`).
- PR mergée (par Emmanuel) → `/wt-done <issue#> <slug>`.
