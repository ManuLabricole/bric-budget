# /github — Maintenance GitHub Project BricBudget

```
Owner  : ManuLabricole
Repo   : bric-budget
Project: 7 (BricBudget board) | PVT_kwHOBlw45M4BTJ3g
```

`unset GITHUB_TOKEN` avant toute commande `gh`.

---

## Créer une issue → l'ajouter immédiatement au board

```bash
unset GITHUB_TOKEN
gh issue create --title "..." --body "..." | xargs gh project item-add 7 --owner ManuLabricole --url
```

⚠️ Ne jamais créer une issue sans l'ajouter au board dans la même commande.

---

## À la fermeture d'une issue

1. Vérifier chaque `- [ ]` dans le corps de l'issue
2. Cocher `- [x]` uniquement les tâches **réellement livrées** (lire le code)
3. Si tâches non faites → **ne pas fermer** — créer issue séparée ou laisser ouverte
4. `gh issue edit NUMBER --body "..."`

---

## À chaque merge de PR

```bash
gh project item-add 7 --owner ManuLabricole --url <PR_URL>
```

Vérifier issues liées fermées + milestones à jour.

---

## ⛔ Règle Qodo — obligatoire après chaque `gh pr create`

```bash
unset GITHUB_TOKEN
gh pr view <NUMBER> --comments
```

- `🐞 Bug` + `⛨ Security` = **bloquer le merge**, corriger d'abord
- `📎 Requirement gap` = tracker dans issue #42 ou issue dédiée
- Ne pas merger si Qodo a posté des "Action required" non traités

Qodo trouve des IDOR complémentaires à `/audit_cto` (querysets non scopés, file_hash cross-user, resolver.py).

---

## Commandes de vérification rapide

```bash
# Issues fermées avec des tâches non cochées (ne devrait pas exister)
unset GITHUB_TOKEN
gh issue list --state closed --limit 30 --json number,title,body \
  | jq -r '.[] | select(.body | test("- \\[ \\]")) | "#\(.number) \(.title)"'

# Milestones et leur avancement
gh api repos/ManuLabricole/bric-budget/milestones \
  --jq '.[] | "\(.title): \(.open_issues) open / \(.closed_issues) closed"'

# Items du project board
gh project item-list 7 --owner ManuLabricole --limit 50
```
