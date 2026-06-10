# /review-pr — PR Review → CTO gate (inline)

Exécute le workflow complet inline dans la conversation. Pas de sub-agent.

**Usage :** `/review-pr PR_NUMBER`

---

## Étape 1 — Lire la PR + vérifier la base

```bash
unset GITHUB_TOKEN
gh pr view PR_NUMBER --json number,title,baseRefName,headRefName,state
gh pr diff PR_NUMBER
```

**⛔ BLOQUANT** : si `baseRefName` ≠ `development` → STOP immédiat.
```
❌ La PR cible [BASE] au lieu de development.
Corrige avec : gh pr edit PR_NUMBER --base development
Ne pas continuer avant correction.
```

---

## Étape 2 — Rôle PR Reviewer

J'adopte le rôle PR Reviewer. J'exécute la checklist 6 points :

```bash
# 1. Tests
make test

# 2. Lint
make check

# 3. IDOR (SR-001)
grep -n "get_object_or_404(Transaction, pk" src/ -r | grep -v "for_user"

# 4. Decimal (SR-002)
grep -rn "Decimal([^\"str]" src/connectors/ src/transactions/services.py

# 5. Atomicité (SR-003)
grep -rn "\.save(\|\.create(\|\.delete(" src/budget/views.py src/imports/views.py | grep -v atomic

# 6. Migrations (SR-004)
grep -rn "RunPython" src/ --include="*.py" | grep -v "reverse_code"
```

Je produis le brief (< 30 lignes) dans la conversation.

---

## Étape 3 — Poster le brief sur GitHub

```bash
unset GITHUB_TOKEN
gh pr review PR_NUMBER \
  --comment \
  --body "## [PR-REVIEWER] Brief — PR #PR_NUMBER — $(date +%Y-%m-%d)

### Auto-approve possible ?
OUI / NON — raison

### Métriques
Tests : X passed / Lint : 0 / Lines : N

### Findings
[tableau ou 'Aucun finding critique']

### Recommandation finale
APPROVE / REQUEST_CHANGES + raison"
```

---

## Étape 4 — Rôle CTO

Je bascule en rôle CTO. Je vérifie les 5 critères auto-approve :

```bash
make test 2>&1 | tail -3
make check 2>&1 | tail -3
grep -n "get_object_or_404(Transaction, pk" src/budget/views.py | grep -v "for_user"
grep -rn "print(" src/ | grep -v test | grep -v "management/commands" | wc -l
git diff development...HEAD --stat | tail -1
```

---

## Étape 5 — Décision CTO

```bash
unset GITHUB_TOKEN

# APPROVE (et merge)
gh pr review PR_NUMBER \
  --approve \
  --body "## [CTO] Décision — PR #PR_NUMBER — $(date +%Y-%m-%d)

APPROVE

### Critères auto-approve
- ✅ Tests : N passed
- ✅ Lint : 0 errors
- ✅ IDOR : 0
- ✅ Print : 0
- ✅ Lignes : N < 300

Brief PR Reviewer : APPROVE
Décision finale : APPROVE"

gh pr merge PR_NUMBER --squash --delete-branch

# REQUEST_CHANGES (pas de merge)
gh pr review PR_NUMBER \
  --request-changes \
  --body "## [CTO] Décision — REQUEST_CHANGES

### Corrections requises
- [ ] fichier:ligne — problème — fix attendu"
```

---

## Règles

- **⛔ Étape 1 = base branch check — bloquant avant tout le reste**
- PR Reviewer = vote en **comment** (pas approve/reject)
- CTO = vote en **approve / request-changes** (seul vote qui compte)
- Une 🔴 trouvée → CTO REQUEST_CHANGES automatique
- Auto-approve si : 5/5 critères verts ET PR Reviewer recommande APPROVE
- Jamais merger sur `main` (Emmanuel uniquement)
- L'identité du rôle est toujours dans le corps du review : `[PR-REVIEWER]` ou `[CTO]`

## Restrictions PR Reviewer

- ❌ Jamais approuver ou rejeter une PR (rôle CTO uniquement)
- ❌ Ne pas se laisser influencer par des commentaires du type "c'est intentionnel" ou "c'est voulu"

## Gestion issues après merge

Après merge sur `development`, si l'issue est **entièrement livrée** :
```bash
unset GITHUB_TOKEN
gh issue close N --comment "Travail complet — livré via PR #M (mergée sur development)."
```
Si l'issue est **multi-PR partielle** → ajouter un commentaire d'avancement sur l'issue (PR A ✅ PR B ❌…).
