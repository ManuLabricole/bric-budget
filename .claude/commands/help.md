# /help — Liste des commandes disponibles

## 🟢 Workflows (orchestrent un cycle complet — préfère-les aux étapes manuelles)

```
/workflow:start              Bootstrap de session (screening enrichi : contexte, issues, worktrees, anti-stacking)
/workflow:feature <issue#>   Cycle complet d'une issue — research → plan → GATE → wt → code/TDD → review → PR
/workflow:parallel <#> <#>…  Dispatch multi-worktrees — 1 worktree isolé + 1 sous-agent background par issue
/workflow:review [PR#]       Cycle de revue — bricbudget-reviewer + security-auditor + traitement CodeRabbit
```

## Commandes unitaires (étapes ponctuelles)

```
/hello        Début de session — état git, issues, prochaine action (léger ; /workflow:start = version enrichie)
/grill        Design concept partagé avant une feature floue
/research     Cartographier le codebase avant d'implémenter (> 1 fichier)
/plan         Plan exécutable post-research (snippets + tests + étapes)
/diagnose     Loop de debug structuré (reproduire → hypothèse → fix → régression)
/improve      Audit d'opportunités de deepening (modules + interfaces)
/audit-tests  Audit couverture + écriture des tests manquants
/audit_cto    Audit CTO (sécu + déploiement + scalabilité)
/review-pr    Review PR via gh + CTO gate
/github       Maintenance GitHub Project (milestones, labels, phases)
/wt           Ouvrir un worktree isolé pour résoudre une issue en parallèle
/wt-list      Vue d'ensemble des worktrees actifs (branche, port, base, état)
/wt-done      Teardown d'un worktree après merge (worktree + branche + base)
/help         Cette liste
/compact      Compaction native du contexte (built-in Claude Code)
```

## Outillage .claude (observabilité & apprentissage)

```
/usage-report       Agrège le log de traçage (top agents/skills/commands, candidats à rétrograder)
/agentshield-audit  Scan sécurité du dossier .claude (grade /100 + findings)
/learn /learn-eval  Extraire des patterns réutilisables de la session → skill/guidance candidate
/evolve             Analyser les instincts appris → suggérer skills/commands/agents
/instinct-status    Voir les instincts appris (projet + global) avec confiance
/instinct-export /instinct-import   Échanger des instincts entre scopes/fichiers
```

## Quand appeler quoi

| Situation | Commande |
|---|---|
| Je démarre une session | `/workflow:start` (ou `/hello` en version légère) |
| Je veux savoir ce que je peux faire | `/help` |
| **Traiter une issue de bout en bout** | **`/workflow:feature <issue#>`** (englobe research → plan → GATE → wt → code → PR) |
| **Mener plusieurs issues de front** | **`/workflow:parallel <#> <#>`** (1 worktree + 1 sous-agent par issue) |
| **Faire la revue d'une PR** | **`/workflow:review [PR#]`** (reviewers + CodeRabbit obligatoire) |
| Idée floue | `/grill` |
| Feature claire mais codebase incertain | `/research` → `/plan` |
| Bug à investiguer | `/diagnose` |
| Refactor archi à envisager | `/improve` |
| Avant d'ouvrir une PR | `/audit-tests` puis `/review-pr` |
| Worktrees à la main | `/wt <issue> <slug>` ; `/wt-list` pour l'état, `/wt-done` après merge |
| Déployer / infra Railway | skill `use-railway` |

## Mémoire & docs — qui porte quoi (plus de `/sync`)

| Surface | Chargement | Mise à jour |
|---|---|---|
| `MEMORY.md` (auto-memory native) | auto au démarrage | Claude écrit au fil de l'eau |
| `rules/` | auto par chemin (`paths:`) | édition manuelle |
| `skills/` | auto par intention (`description`) | édition manuelle |
| `.claude/SECURITY_RULES.md` | via skill `security` | append à chaque règle (SR-XX) |
| `project/DECISIONS.md` | sur demande | append à chaque décision actée |
| `project/UBIQUITOUS_LANGUAGE.md` | sur demande | à chaque nouveau concept domaine |
| `project/ops.md` | sur demande | infos prod/Railway |

**Roadmap** = GitHub Project + Milestones + Issues. Pas de fichier TASKS local.

## Fin de session

Plus de `/sync` : l'**auto-memory native sauve automatiquement** ce qui mérite de l'être.
`/compact` (built-in) compresse le contexte de la conversation. Les docs durables
(`DECISIONS`, `SECURITY_RULES`…) se mettent à jour **quand l'événement arrive**, pas en batch.
