# /hello — Démarrage de session BricBudget

```bash
git branch --show-current && git log --oneline -3 && git status -s
unset GITHUB_TOKEN && gh issue list --state open --limit 8
```

> L'état **durable** est chargé automatiquement : `MEMORY.md` (auto-memory native) au
> démarrage + les `rules/`/`skills/` selon le contexte. Roadmap = GitHub Project +
> Milestones. Infos prod/ops = `.claude/project/ops.md`.

## Résumé (format fixe)

```
✅ Dernier commit   : [message] — branche [branche]
🎯 Milestone actif  : [vXX] — [N issues open]
🔥 Prochaine issue  : #[N] — [titre court]
👉 Suggestion       : [action directe — une seule ligne]
```

## Règle branche

- `main` / `development` → STOP. Créer `feature/<slug>` avant tout commit.
- Vérifier qu'on n'est pas sur une branche avec PR déjà ouverte avant de coder une nouvelle feature.

## Quoi faire ensuite

| Situation | Commande |
|-----------|----------|
| Connaître toutes les commandes | `/help` |
| Nouvelle feature, design flou | `/grill` → aligner le design |
| Issue GH bien définie | `/research` → `/plan` → valider → code |
| Bug à fixer | `/diagnose` (debug structuré) |
| Bugfix trivial (< 10 lignes, 1 fichier) | Aller directement au code |
| Décision archi à acter | append `project/DECISIONS.md` (table ADR) |
| Refacto archi | `/improve` (deepening modules) |
| Fin de session | `/compact` (compaction native — l'auto-memory sauve déjà au fil de l'eau) |
