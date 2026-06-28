# CLAUDE.md — BricBudget
> Chargé automatiquement à chaque session. Contient UNIQUEMENT les règles toujours actives.
> Références complètes → voir tableau ci-dessous.

---

## Références & mémoire

| Surface | Chargement | Contenu |
|---------|-----------|---------|
| `rules/` | auto **par chemin** (`paths:`) | conventions courtes (django, htmx, tailwind, testing) |
| `skills/` | auto **par intention** (`description`) | expertise (`security`) + outillage (`skill-creator`) |
| `SECURITY_RULES.md` | via skill `security` | SR-XX — source de vérité sécurité (committé) |
| `project/DECISIONS.md` | sur demande | ADRs append-only (privé) |
| `project/UBIQUITOUS_LANGUAGE.md` | sur demande | vocabulaire + module map (privé) |
| `project/ops.md` | sur demande | config prod / Railway (privé) |
| Auto-memory `~/.claude/.../memory/` | auto au démarrage (`MEMORY.md`) | apprentissages + préférences durables |

**Source de vérité roadmap** : GitHub Project + Milestones (issues, phases, releases). Pas de fichier TASKS local.

**Mémoire** : l'**auto-memory native** sauve les apprentissages au fil de l'eau — **plus de `/sync`**. `/compact` = compaction native du contexte. Les docs durables (`DECISIONS`, `SECURITY_RULES`…) se mettent à jour **quand l'événement arrive**, pas en batch. `/help` liste les commandes.

---

## Projet & Stack FINALE (ne jamais remettre en question)

**BricBudget** — Suivi budgétaire personnel. Vision SaaS 50 000 users (3-5 ans).

| Composant | Choix |
|-----------|-------|
| Framework | **Django** — pas React/Dash/Streamlit |
| UI | **HTMX** — pas de JS custom, état côté serveur |
| CSS | **Tailwind CSS** — classes utilitaires uniquement |
| DB | **PostgreSQL** — Docker local → Railway prod |
| État UI | **Django sessions** — pas d'URL params |
| Parsing | **Python + pandas** — connecteurs CSV par banque |
| Catégorisation | **Règles keywords → Claude API** |
| Infra | **Docker Compose** + Railway |

---

## ⛔ Sécurité — règles absolues (détails : SECURITY_RULES.md)

```python
# IDOR Transaction — TOUJOURS
Transaction.objects.for_user(request.user)

# IDOR Account — TOUJOURS
Account.objects.filter(is_active=True, members=request.user)

# IDOR ImportLog — TOUJOURS
ImportLog.objects.filter(file_hash=h, account__members=request.user)

# Précision monétaire — TOUJOURS
Decimal(str(float_value))  # jamais Decimal(float_value)

# Atomicité DB
with transaction.atomic(): ...

# Logs prod — jamais print()
logger.debug/info/exception(...)
```

**IBAN/RIB** → `.env` + `config()` sans exception, même dans les commentaires.

---

## Git workflow

**1 issue = 1 branche = 1 PR.** ⛔ Ne **jamais** empiler une branche sur une autre
non mergée (stacking = enfer de rebase, incident réel #125 découpée en 2 branches).
Trop gros pour une PR ? → en faire **2 issues distinctes**, chacune sa branche,
**mergée avant** de brancher la suivante. Toujours partir de `development` à jour.

```bash
git branch --show-current   # ⛔ si main / development → STOP
git checkout development && git pull --ff-only
git checkout -b feature/<issue#>-<slug>   # ex. feature/125-institutions
```

Format commit (Conventional Commits) :
```
feat(scope): description courte
```
**Jamais de `Co-Authored-By`** — jamais de mention Claude dans les commits.

Si hook bloque → corriger + recommiter. **Jamais `--no-verify`.**

### Worktrees parallèles (multi-Claude) — `/wt`

Pour mener **plusieurs PR de front**, une session Claude Code par issue, totalement
isolée (branche + base Postgres + port). Renforce l'anti-stacking : impossible
d'empiler, chaque branche vit dans son répertoire.

```bash
/wt 144 settings-split        # crée ../.bric-worktrees/144-settings-split (branche depuis development,
                              # base bric_wt_144, port 8144, .venv/node_modules symlinkés)
cd ../.bric-worktrees/144-settings-split && claude
/wt-done 144 settings-split   # après merge : teardown worktree + branche + base
```

⛔ Ne PAS lancer `claude --worktree` nu (il branche depuis `main`). Toujours `/wt`.
Détails : `commands/wt.md`, `scripts/wt-new.sh`.

---

## Règles de code

- Code simple, commenté (le POURQUOI), debuggable
- Pas de sur-abstraction — ROI d'abord
- Une fonction ou classe à la fois
- Si grosse modif → expliquer → plan → step-by-step
- **Tester GET + POST via `manage.py shell`** avant de déclarer terminé (voir `rules/testing.md`)
- **Jamais `{# #}` multilignes dans les partials** → `{% comment %}`
- Tokens design : `window.BRICBUDGET_TOKENS` — jamais de hex/font hardcodé en JS
- ⛔ **Definition of Done** (`rules/definition-of-done.md`, chargé par chemin) : avant de dire « terminé »,
  **prouver** (pas affirmer) les 4 gates — ① tests réels non-théâtre ② diff simplifié ③ pattern d'archi cité,
  pas de spaghetti ④ idiome Django, pas de workaround. La revue + CodeRabbit sont un **filet**, pas le QA.

---

## Workflow PR

⛔ **Ne PAS lancer `make check` / `make test` à la main avant commit/PR** — c'est du double
emploi : pre-commit (ruff + djlint + gitleaks) + pre-push (**pytest**) + CI (**mypy** + semgrep)
couvrent tout automatiquement. On commit/push directement et on laisse les hooks + la CI tourner.
Seul `mypy` n'est pas dans les hooks locaux (CI only) → un `make type` ponctuel est ok après une
grosse modif de types, jamais le `make check` complet. La **vérif live GET/POST** (`manage.py shell` /
app réelle) reste due — elle n'est PAS couverte par la CI.

```
feature branch → commit (hooks: ruff/djlint/pytest) → gh pr create --base development
→ ⚙️ agent `bricbudget-reviewer` (revue code) → 🐰 attendre + traiter CodeRabbit → corriger les bloquants
→ Emmanuel merge → development   (development → main : Emmanuel uniquement)
```

Après `gh pr create` → **déclencher l'agent `bricbudget-reviewer`** sur le diff
(`git diff origin/development...HEAD`). **Qodo est en PAUSE** sur le compte → c'est
l'agent qui assure la revue (+ `security-auditor` sur le code sensible). Findings
bloquants/sécurité → corriger **avant** merge. Voir `commands/github.md`.
Auto-approve si : tests 100% verts + 0 ruff + 0 IDOR sans for_user + 0 print().

⛔ **Après CHAQUE PR — traiter CodeRabbit (obligatoire, ne pas attendre qu'on le demande).**
Le cycle de revue n'est PAS fini tant que 🐰 CodeRabbit n'a pas tourné :
1. Attendre `CodeRabbit … Review completed` (`gh pr checks <PR>` ; il re-tourne à chaque push).
2. Lire ses commentaires **+ les « 🤖 Prompt for AI Agents » + findings *outside-diff*** (souvent dans
   le corps de la revue, pas en inline) : `gh pr view <PR> --json reviews` +
   `gh api repos/ManuLabricole/bric-budget/pulls/<PR>/comments`.
3. **Juger chaque suggestion** → pertinente = implémenter (commit + push re-déclenche CodeRabbit) ;
   non pertinente / hors scope / déjà couverte = écarter **avec raison brève**. Jamais en masse aveugle.
4. Récap à Emmanuel : finding → action. Vérifier `git rev-list --count origin/<branch>..HEAD ≥ 1`
   après chaque commit (le formateur pre-commit peut l'avaler) ; pousser les branches **en série**
   (pytest pre-push concurrents collisionnent sur `test_bricbudget`).

`unset GITHUB_TOKEN` avant toute commande `gh`.

### ⛔ Règles PR obligatoires

```bash
# Toujours cibler development — jamais main directement.
# Labels + milestone HÉRITÉS DE L'ISSUE + ajout au board dans la même foulée.
gh pr create --base development --label <labels issue> --milestone "<milestone issue>" ...
gh project item-add 7 --owner ManuLabricole --url <PR_URL>
```

**Corps PR — pattern issues :**
- PRs feature (→ `development`) : `Closes #N` — `development` est la **branche par défaut** (depuis 2026-06-22) → le merge sur `development` **ferme l'issue automatiquement** ET crée le lien issue↔PR. (Garder `Part of #N` pour une issue parente/epic qu'on ne ferme pas.)
- PRs release (`development` → `main`) : les issues sont déjà fermées au merge sur `development` ; lister `Closes #N…` reste optionnel (traçabilité du milestone).

**Fermeture des issues = automatique** au merge sur `development` via `Closes #N` dans le corps de la PR. Fermeture manuelle uniquement en rattrapage (mot-clé oublié).

**Multi-PR sur une issue — à ÉVITER** (cause de stacking, incident #125). Préférer
**découper en issues distinctes** (1 issue = 1 branche). Si vraiment inévitable :
merger chaque PR **avant** d'ouvrir la suivante — **jamais 2 branches empilées**.
Commentaire d'avancement sur l'issue (`PR A ✅ PR B ❌`), ne pas clore avant que tout soit mergé.
