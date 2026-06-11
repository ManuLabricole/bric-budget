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

---

## Règles de code

- Code simple, commenté (le POURQUOI), debuggable
- Pas de sur-abstraction — ROI d'abord
- Une fonction ou classe à la fois
- Si grosse modif → expliquer → plan → step-by-step
- **Tester GET + POST via `manage.py shell`** avant de déclarer terminé (voir `rules/testing.md`)
- **Jamais `{# #}` multilignes dans les partials** → `{% comment %}`
- Tokens design : `window.BRICBUDGET_TOKENS` — jamais de hex/font hardcodé en JS

---

## Workflow PR

```
feature branch → make check + make test
→ gh pr create --base development
→ ⚙️ agent `bricbudget-reviewer` (revue code) → corriger les bloquants
→ Emmanuel merge → development   (development → main : Emmanuel uniquement)
```

Après `gh pr create` → **déclencher l'agent `bricbudget-reviewer`** sur le diff
(`git diff origin/development...HEAD`). **Qodo est en PAUSE** sur le compte → c'est
l'agent qui assure la revue (+ `security-auditor` sur le code sensible). Findings
bloquants/sécurité → corriger **avant** merge. Voir `commands/github.md`.
Auto-approve si : tests 100% verts + 0 ruff + 0 IDOR sans for_user + 0 print().

`unset GITHUB_TOKEN` avant toute commande `gh`.

### ⛔ Règles PR obligatoires

```bash
# Toujours cibler development — jamais main directement
gh pr create --base development ...
```

**Corps PR — pattern issues :**
- PRs feature (→ `development`) : `Part of #N` — **jamais `Closes`** (GitHub ferme uniquement sur merge vers `main`)
- PRs release (`development` → `main`) : `Closes #N1, Closes #N2` — pour **toutes** les issues du milestone

**Fermeture manuelle des issues :** quand le travail est complet et mergé sur `development`, fermer l'issue manuellement avec un commentaire référençant les PRs.

**Multi-PR sur une issue — à ÉVITER** (cause de stacking, incident #125). Préférer
**découper en issues distinctes** (1 issue = 1 branche). Si vraiment inévitable :
merger chaque PR **avant** d'ouvrir la suivante — **jamais 2 branches empilées**.
Commentaire d'avancement sur l'issue (`PR A ✅ PR B ❌`), ne pas clore avant que tout soit mergé.
