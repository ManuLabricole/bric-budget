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

```bash
git branch --show-current   # ⛔ si main → STOP
git checkout -b feature/phase-Xg-<slug>
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
→ /review-pr PR_NUMBER → /cto gate
→ Approve + merge → development
→ development → main : Emmanuel uniquement
```

Critères auto-approve : tests 100% verts + 0 ruff errors + 0 IDOR sans for_user + 0 print() + < 300 lignes changées.
Après `gh pr create` → lire Qodo findings (voir `commands/github.md`).

`unset GITHUB_TOKEN` avant toute commande `gh`.
