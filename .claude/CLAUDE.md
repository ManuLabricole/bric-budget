# CLAUDE.md — BricBudget
> Chargé automatiquement à chaque session. Contient UNIQUEMENT les règles toujours actives.
> Références complètes → voir tableau ci-dessous.

---

## Références

| Fichier | Sync gate | Contenu |
|---------|-----------|---------|
| `CONTEXT.md` | /compact phase 2 | État git, version, tests |
| `CHANGELOG.md` | /compact phase 3 | Append par session |
| `DECISIONS.md` | /compact phase 4.1 | ADRs append-only |
| `SECURITY_RULES.md` | /compact phase 4.2 | SR-XX source de vérité sécurité |
| `UBIQUITOUS_LANGUAGE.md` | /compact phase 4.3 | Vocabulaire + module map |
| `MEMO.md` | /compact phase 4.4 | Patterns Django/HTMX |
| `CLAUDE.md` | /compact phase 4.5 (rare) | Règles toujours actives |
| Memory `~/.claude/.../memory/` | /compact phase 4.6 | Préférences durables |

**Source de vérité roadmap** : GitHub Project + Milestones (issues, phases, releases). Pas de fichier TASKS local.

**Règle structurelle** : `/sync` est le sync gate (met à jour les fichiers `.claude/`). Suivi de `/compact` (compression native du contexte). Entre création et merge d'une branche, tous les fichiers `.claude/` doivent refléter l'état courant. `/help` liste les commandes disponibles.

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
- **Tester GET + POST via `manage.py shell`** avant de déclarer terminé (voir MEMO.md)
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
