# `.claude/` — Configuration Claude Code de BricBudget

Ce dossier configure [Claude Code](https://claude.com/claude-code) pour le projet.
Il est **partiellement publié** : seuls les outils réutilisables sont sur GitHub, le
reste (notes de session, état projet, audits) est local.

## Ce qui est publié (versionné)

| Élément | Rôle |
|---------|------|
| `CLAUDE.md` | Config d'entrée — règles toujours actives, stack, workflow git/PR, règles sécurité |
| `commands/*.md` | Les skills (slash-commands) : `/hello`, `/research`, `/plan`, `/grill`, `/review-pr`, `/diagnose`, `/improve`, `/sync`, `/github`, `/audit_cto`, `/audit-tests`, `/help` |
| `skills/security/` | Skill sécurité : SR-XX → OWASP 2025, LLM security, Python quirks, HTTP headers |
| `skills/security/scripts/security_audit.sh` | Audit sécurité automatisé (SR-001/002/004/005/008/009 — IDOR, Decimal, print(), IBAN…) |
| `settings.example.json` | Template de permissions — à copier |
| `*.example.md` | Squelettes des docs privés (CONTEXT, CHANGELOG, DECISIONS, SECURITY_RULES, UBIQUITOUS_LANGUAGE, MEMO) — décrivent le rôle + la structure |
| `README.md` | Ce fichier |

## Ce qui est local (gitignoré — voir `.gitignore` racine)

`CHANGELOG.md`, `CONTEXT.md`, `MEMO.md`, `DECISIONS.md`, `SECURITY_RULES.md`,
`UBIQUITOUS_LANGUAGE.md`, `history/`, `audits/`, `ai_code_references/`,
`settings.json`, et les scratchpads `plan_*.md` / `research_*.md`.

> **Whitelist** : le `.gitignore` racine ignore tout `.claude/` par défaut et ne
> ré-inclut que les éléments ci-dessus. Un nouveau fichier est donc **privé par
> défaut** — jamais publié par accident.

## Setup (après clone)

```bash
cp .claude/settings.example.json .claude/settings.json
# adapter additionalDirectories si besoin (chemin relatif .claude par défaut)

# puis créer les docs de travail à partir des squelettes, au besoin :
cp .claude/CONTEXT.example.md .claude/CONTEXT.md   # etc. pour les autres .example.md
```

## Scratchpads `plan_*` / `research_*`

Les skills `/research` et `/plan` écrivent des fichiers `research_<slug>.md` et
`plan_<slug>.md` à la racine de `.claude/`. Ce sont des **scratchpads éphémères** :
gitignorés, à supprimer dès que la feature est mergée. Le durable est distillé dans
`DECISIONS.md` / `CHANGELOG.md` / `UBIQUITOUS_LANGUAGE.md`.
