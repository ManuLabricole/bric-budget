# /help — Liste des commandes disponibles

Display les commandes BricBudget avec leur fonction et quand les appeler.

## Cycle de vie d'une session

```
/hello              Début — état git, tests, prochaine issue, warnings staleness
/grill              Design concept partagé avant feature floue
/research           Cartographier le codebase avant d'implémenter (> 1 fichier)
/plan               Plan exécutable post-research (snippets + tests + étapes)
/diagnose           Loop de debug structuré (reproduire → hypothèse → fix → régression)
/improve            Audit d'opportunités de deepening (modules + interfaces)
/audit-tests        Audit couverture + écriture tests manquants (Zulip-style)
/audit_cto          Audit CTO mode (sécu + déploiement + scalabilité)
/review-pr          Review PR via gh + CTO gate
/deploy             Expert déploiement Railway
/github             Maintenance GitHub Project (milestones, labels, phases)
/sync               Fin — sync gate, met à jour TOUS les fichiers .claude/
/compact            Fin — compression native du contexte (built-in Claude Code)
```

## Quand appeler quoi

| Situation | Commande |
|---|---|
| Je démarre une session | `/hello` |
| Je veux savoir ce que je peux faire | `/help` |
| L'utilisateur a une idée floue | `/grill` |
| Feature claire mais codebase incertain | `/research` |
| Codebase cartographié, prêt à coder | `/plan` |
| Bug à investiguer | `/diagnose` |
| Refactor archi à envisager | `/improve` |
| On vient d'arbitrer un trade-off important | `/decide` |
| Avant d'ouvrir une PR | `/audit-tests` puis `/review-pr` |
| Déployer / infra Railway | skill `use-railway` (ou skills Railway communautaires) |
| Avant de fermer la session ou de merger | `/sync` puis `/compact` |

## Fichiers `.claude/` — qui écrit quoi

| Fichier | Sync gate | Quand mis à jour |
|---|---|---|
| `CONTEXT.md` | `/sync` phase 2 | Chaque fin de session |
| `CHANGELOG.md` | `/sync` phase 3 | Chaque fin de session (append) |
| `DECISIONS.md` | `/sync` phase 4.1 | À chaque décision actée |
| `SECURITY_RULES.md` | `/sync` phase 4.2 | À chaque nouvelle règle |
| `UBIQUITOUS_LANGUAGE.md` | `/sync` phase 4.3 | À chaque nouveau concept |
| `MEMO.md` | `/sync` phase 4.4 | À chaque nouveau pattern |
| `CLAUDE.md` | `/sync` phase 4.5 (rare) | Quand règle globale change |
| Memory | `/sync` phase 4.6 | À chaque feedback récurrent |

**Source de vérité roadmap** : GitHub Project + Milestones + Issues. Pas de fichier TASKS local.

## Règle

`/sync` est le **sync gate** : met à jour tous les fichiers `.claude/`, puis `/compact` (built-in) compresse réellement le contexte de la conversation. Entre la création et le merge d'une branche, tous les fichiers `.claude/` doivent refléter l'état courant.