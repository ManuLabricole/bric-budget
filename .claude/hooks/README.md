# `.claude/hooks/` — garde-fous déterministes

> Une règle `⛔` de `CLAUDE.md` écrite en prose est un *vœu* ; un hook `PreToolUse`
> qui `exit 2` est une *loi* (la commande est bloquée à 100 %, l'agent reçoit la raison
> sur stderr). Issue de référence : **#188** (epic #216). Contrat Claude Code : stdin =
> JSON du tool, `exit 2` = feedback bloquant transmis au modèle.

## Garde-fous actifs (`PreToolUse`)

| Hook | Matcher | Bloque | Override |
|------|---------|--------|----------|
| `block_no_verify.sh` | `Bash` | `--no-verify` / `git commit -n` | — |
| `block_gh_merge.sh` | `Bash` | `gh pr merge` (merge = Emmanuel) | — |
| `block_protected_branch.sh` | `Bash` | `git commit`/`push` **sur** ou **vers** `main`/`development` | — |
| `config_protection.sh` | `Edit\|Write\|MultiEdit` | édition des configs linter + `.claude/settings.json` | `ECC_ALLOW_CONFIG_EDIT=1` |

> ⚠️ Wirer un nouveau hook édite `.claude/settings.json` → protégé par `config_protection.sh`.
> Le faire avec `ECC_ALLOW_CONFIG_EDIT=1`, ou via une commande Bash (matcher non couvert).

### Détail des règles `git` protégées
- **commit** : bloqué si la **branche courante** ∈ {`main`, `development`}.
- **push** : bloqué si la **branche courante** ∈ protégées **OU** si une **ref destination**
  du refspec ∈ protégées (ex. `git push origin development` bloqué même depuis une feature branch ;
  `git push origin HEAD:main` aussi). Une branche feature (`git push -u origin feature/x`) passe.

### Pourquoi `shlex` et pas une regex
Le `command` est segmenté via `shlex.split` sur les séparateurs shell (`&& || | ; & ( ) { }`)
puis analysé token par token → **zéro faux positif** : un message de commit, un `echo`
ou un `--body "merge"` contenant le mot interdit ne déclenchent rien.

## Tester un garde-fou (sans danger)
On simule l'appel du tool en passant un faux JSON sur stdin :
```bash
# Interdit → message sur stderr + rc=2 (on capture stderr pour voir la raison du blocage).
out=$(echo '{"tool_input":{"command":"gh pr merge 1"}}' | bash .claude/hooks/block_gh_merge.sh 2>&1); rc=$?
printf '%s\n(rc=%s)\n' "$out" "$rc"          # → ⛔ 'gh pr merge' interdit … + rc=2

out=$(echo '{"tool_input":{"command":"git push origin development"}}' | bash .claude/hooks/block_protected_branch.sh 2>&1); rc=$?
printf '%s\n(rc=%s)\n' "$out" "$rc"          # → ⛔ commit/push sur 'main'/'development' … + rc=2

# Autorisé → aucun message, rc=0.
echo '{"tool_input":{"command":"gh pr view 1"}}' | bash .claude/hooks/block_gh_merge.sh; echo "rc=$?"   # → rc=0
```

## Limites connues (hors scope #188)
- `git -C <autre-repo> commit` : la branche courante lue est celle du CWD (le refspec
  d'un `push` reste, lui, vérifié). Protection serveur (branch protection GitHub) = autre chantier.
- **Wrapper shell** (`bash -lc '…'`) et **opérateurs collés sans espace** (`ok&&git push …`) :
  les guards parsent l'argv top-level (`shlex`) ; ces formes cachent la commande. Choix assumé :
  un vrai parseur shell ré-introduirait des faux positifs sur les strings quotées, et `block_no_verify.sh`
  partage la même limite → à traiter (si besoin) dans un helper de parsing commun à tous les hooks, pas ici.
  Les chaînes `&&`/`;` **avec espaces** et les commandes `git`/`gh` directes restent, elles, bien couvertes.
