# /help — Liste des commandes disponibles

## Commandes (slash-commands — déclenchées par toi)

```
/hello        Début de session — état git, issues, prochaine action
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

## Quand appeler quoi

| Situation | Commande |
|---|---|
| Je démarre une session | `/hello` |
| Je veux savoir ce que je peux faire | `/help` |
| Idée floue | `/grill` |
| Feature claire mais codebase incertain | `/research` → `/plan` |
| Bug à investiguer | `/diagnose` |
| Refactor archi à envisager | `/improve` |
| Avant d'ouvrir une PR | `/audit-tests` puis `/review-pr` |
| Mener plusieurs PR en parallèle | `/wt <issue> <slug>` → `cd` + `claude` (1 session/issue) ; `/wt-list` pour l'état, `/wt-done` après merge |
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
