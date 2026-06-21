<!--
  Template de PR BricBudget. Garde-le court : ce qui ne s'applique pas, supprime-le.
  Rappel : base = `development` (jamais `main` directement).
-->

## Quoi & pourquoi
<!-- 1 à 3 phrases : le changement et la raison. -->


## Issue liée
<!--
  OBLIGATOIRE. Une PR se rattache toujours à une issue (sauf micro-chore réactif évident).
  - Closes #N   → l'issue se ferme automatiquement au merge (sur la branche par défaut).
  - Part of #N  → contribue à une epic / issue qui reste ouverte (plusieurs PR).
  Le MILESTONE vit sur l'ISSUE (source de vérité du périmètre de release), pas sur la PR.
-->
Closes #


## Type
- [ ] feat — [ ] fix — [ ] refactor — [ ] perf — [ ] chore — [ ] docs — [ ] test


## Comment testé
<!--
  Tests automatisés + la VÉRIF LIVE (GET + POST via `manage.py shell` ou l'app réelle) :
  la CI ne couvre PAS le live. Décris ce que tu as réellement vérifié.
-->


## Checklist (Definition of Done)
- [ ] Conventional commits (commitizen passe)
- [ ] Tests verts (pytest) + 0 ruff ; vérif live GET/POST faite
- [ ] **IDOR (SR-001)** : accès scopés `for_user` / `members=request.user` / `account__members`
- [ ] **Argent (SR-002)** `Decimal(str(x))` · **atomicité (SR-003)** `transaction.atomic()`
- [ ] **Logs (SR-005)** `logger`, pas de `print()` · **secrets (SR-008)** aucun IBAN/RIB en dur
- [ ] Base = `development` · labels + milestone portés par l'**issue** liée
- [ ] Docs `.claude/` (rules/commands) à jour si le comportement change


## Captures (si UI)
<!-- Avant / Après — un screenshot vaut mille mots pour une revue UI. -->
