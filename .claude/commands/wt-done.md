# /wt-done — Teardown d'un worktree après merge

> Usage : `/wt-done <issue#> <slug>`   (ex. `/wt-done 144 settings-split`)
> À lancer **uniquement** quand la PR est mergée sur `development`.

---

## Pré-check

```bash
unset GITHUB_TOKEN
gh pr list --state merged --search "head:feature/<issue#>-<slug>" --json number,mergedAt
```

Si la PR n'est pas mergée → **ne pas teardown** (perte de code). Le script avertit
quand même si des changements non commités traînent dans le worktree.

## Teardown

```bash
scripts/wt-rm.sh <issue#> <slug>
```

Supprime : worktree + branche locale `feature/<issue>-<slug>` + base `bric_wt_<issue>`
+ `git worktree prune`.

## Clôture côté GitHub (cf. `commands/github.md`)

1. Vérifier les `- [ ]` du corps de l'issue → cocher seulement le réellement livré.
2. Fermer l'issue manuellement avec un commentaire référençant la/les PR.
3. Vérifier que la PR est bien au board (projet 7) et le milestone à jour.
