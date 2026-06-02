# /hello — Démarrage de session BricBudget

```bash
git branch --show-current && git log --oneline -3 && git status -s
cat .claude/CONTEXT.md
unset GITHUB_TOKEN && gh issue list --state open --limit 8
```

## Résumé (format fixe)

```
📅 Dernière session : [date] — [résumé 1 ligne, depuis CONTEXT.md]
✅ Dernier commit   : [message] — branche [branche]
💾 Tests            : [N passed / dernier make test]
🎯 Milestone actif  : [vXX] — [N issues open]
🔥 Prochaine issue  : #[N] — [titre court]
👉 Suggestion       : [action directe — une seule ligne]
```

## Warnings staleness (à signaler si détecté)

Vérifier les fichiers `.claude/` modifiés il y a > 21 jours et lever un warning :
```bash
find .claude -maxdepth 1 -name "*.md" -mtime +21
```

## Règle branche

- `main` → STOP. Créer `feature/<slug>` avant tout commit.
- Vérifier qu'on n'est pas sur une branche avec PR déjà ouverte avant de coder une nouvelle feature.

## Quoi faire ensuite

| Situation | Commande |
|-----------|----------|
| Connaître toutes les commandes disponibles | `/help` |
| Nouvelle feature, design flou | `/grill` → aligner le design concept |
| Issue GH bien définie | `/research` → `/plan` → valider → code |
| Bug à fixer | `/diagnose` (debug structuré) |
| Bugfix trivial (< 10 lignes, 1 fichier) | Aller directement au code |
| Décision archi à acter | `/decide` (append DECISIONS.md) |
| Refacto archi | `/improve` (deepening modules) |
| Fin de session | `/compact` → met à jour TOUS les fichiers `.claude/` |