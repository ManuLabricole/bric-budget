# `.claude/` — Configuration Claude Code de BricBudget

Ce dossier configure [Claude Code](https://claude.com/claude-code) pour le projet.
Il est **partiellement publié** : seuls les outils réutilisables (config Claude Code) sont
sur GitHub ; les docs projet privées vivent dans `project/` (gitignoré).

## Les 5 couches (comment Claude charge le contexte)

| Couche | Déclenchement | Pour quoi |
|--------|---------------|-----------|
| **`CLAUDE.md`** | Toujours (chaque session) | Règles absolues, stack, workflow git/PR |
| **`rules/`** | Auto, **par chemin** (frontmatter `paths:`) | Conventions courtes always-on quand on touche un type de fichier |
| **`commands/`** | **Manuel** (tu tapes `/xxx`) | Rituels délibérés |
| **`skills/`** | Auto, **par intention** (frontmatter `description`) | Expertise riche + scripts, chargée à la demande |
| **`hooks/`** | Sur **événement** (PostToolUse…) | Guardrails automatiques |
| **`agents/`** | **Manuel** (délégation) | Sweep en contexte isolé |

> Règle de séparation (D-025) : **rule** = court/path/always-on · **skill** = riche/intention/à la demande · **command** = rituel manuel · **agent** = contexte isolé. Cas critique (IDOR) = 1-ligne dans la rule + détail dans le skill.

## Ce qui est publié (versionné)

| Élément | Rôle |
|---------|------|
| `CLAUDE.md` | Config d'entrée — règles toujours actives, stack, workflow git/PR, sécurité |
| `rules/*.md` | Conventions path-scoped : `django.md` (`src/**/*.py`), `htmx.md` + `tailwind.md` (templates), `testing.md` (tests) |
| `commands/*.md` | Slash-commands (tu les tapes) : `/hello`, `/research`, `/plan`, `/grill`, `/review-pr`, `/diagnose`, `/improve`, `/github`, `/audit_cto`, `/audit-tests`, `/help` |
| `skills/security/` | Skill sécurité (auto par `description`) : SR-XX → OWASP 2025, LLM security, Python quirks, HTTP headers + `scripts/security_audit.sh` |
| `skills/skill-creator/` | Outillage Anthropic (Apache-2.0) : valide/scaffolde/package les skills |
| `agents/*.md` | Subagents : `security-auditor` (audit OWASP/SR-XX), `bricbudget-reviewer` (revue Django + structurelle) |
| `hooks/ruff_format.sh` | Hook PostToolUse : `ruff format` auto du `.py` édité |
| `settings.json` | Config d'équipe committée : permissions + hook ruff-format |
| `SECURITY_RULES.md` | Source de vérité sécurité (SR-XX) — référencée par le skill `security` |
| `VERSION` | Version de la config (stampée en footer de chaque commit) |
| `README.md` | Ce fichier |

## Ce qui est local (gitignoré — voir `.gitignore` racine)

- **`project/`** — docs durables privés : `DECISIONS.md` (ADRs), `UBIQUITOUS_LANGUAGE.md`
  (glossaire), `ops.md` (config Railway), `history/` (CHANGELOG + MEMO archivés, figés).
- **`settings.local.json`** — overrides perso.
- Scratchpads `plan_*.md` / `research_*.md`.
- L'état courant (git, version, roadmap) n'est plus un fichier : **GitHub Project** +
  **auto-memory native** (`~/.claude/.../memory/`, chargée seule au démarrage).

> **Whitelist** : le `.gitignore` racine ignore tout `.claude/` par défaut et ne
> ré-inclut que les éléments ci-dessus. Un nouveau fichier est donc **privé par
> défaut** — jamais publié par accident.

## Setup (après clone)

`settings.json` est **committé** (config d'équipe : permissions + hook ruff-format) et
fonctionne tel quel. Pour tes préférences perso (modèle, chemins absolus, defaultMode),
crée un **`settings.local.json`** (gitignoré, Claude l'écrit aussi automatiquement) :

```jsonc
// .claude/settings.local.json
{ "permissions": { "defaultMode": "dontAsk" } }
```

## Scratchpads `plan_*` / `research_*`

Les commands `/research` et `/plan` écrivent des fichiers `research_<slug>.md` et
`plan_<slug>.md` à la racine de `.claude/`. Ce sont des **scratchpads éphémères** :
gitignorés, à supprimer dès que la feature est mergée. Le durable est distillé dans
`project/DECISIONS.md` / `project/UBIQUITOUS_LANGUAGE.md` + l'auto-memory native.
