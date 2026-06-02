# /grill — Interview adversarial (design concept partagé)

> Inspiré de "Principles for AI Coding" (Matt Pocock — AI Engineer)
> But : atteindre un DESIGN CONCEPT PARTAGÉ avant de planifier.
> Empêche "l'AI a fait quelque chose de totalement différent de ce que je voulais."

---

## Quand utiliser

- Avant une nouvelle feature dont le comportement exact est flou
- Quand la formulation d'Emmanuel est vague ("améliore la page X", "ajoute un truc pour Y")
- Pour des décisions d'architecture importantes (nouveau modèle, nouveau flux UI)
- **Pas nécessaire** pour une issue GitHub déjà bien définie ou une spec claire

---

## Protocole

### 1. Lire le contexte

```bash
cat .claude/CONTEXT.md
cat .claude/UBIQUITOUS_LANGUAGE.md
unset GITHUB_TOKEN && gh issue list --state open --milestone "<milestone courante>" --limit 10
```

### 2. Lancer l'interview

Poser des questions **une par une**, dans cet ordre de priorité :

#### Bloc 1 — Comportement visible (UX)
- "Quel est le parcours exact de l'utilisateur pour déclencher cette feature ?"
- "Qu'est-ce qui s'affiche avant / pendant / après l'action ?"
- "Qu'est-ce qui se passe si X échoue ?" (erreur, état vide, timeout)
- "Est-ce que Carys voit la même chose qu'Emmanuel ?"

#### Bloc 2 — Données et modèles
- "Quelles données sont créées / modifiées / supprimées ?"
- "Est-ce que c'est réversible ?"
- "Y a-t-il une contrainte d'unicité ou de validation ?"
- "Quel modèle Django est le plus proche de ce besoin ?"

#### Bloc 3 — Périmètre et limites
- "Qu'est-ce qui est HORS périmètre pour cette feature ?"
- "Quelle est la définition du 'terminé' ? Comment on sait que c'est fait ?"
- "Est-ce que ça touche des données existantes ou seulement les nouvelles ?"

#### Bloc 4 — Contraintes techniques
- "Est-ce que cette feature doit fonctionner offline / sans JS ?"
- "Est-ce que c'est un HTMX partial ou une page complète ?"
- "Y a-t-il une contrainte de performance ?" (gros volumes, appels API externes)

### 3. Synthèse

Après avoir épuisé les questions pertinentes, produire :

```markdown
## Design Concept partagé — <nom feature>

### Ce qu'on construit
[1-2 phrases : comportement exact du point de vue utilisateur]

### Ce qu'on NE construit PAS
[liste courte des exclusions validées]

### Décisions prises
- [décision 1] — justification
- [décision 2] — justification

### Modèles impliqués
- [liste des modèles Django]

### Terminé quand
- [ ] [critère 1 mesurable]
- [ ] [critère 2 mesurable]
```

### 4. Valider avec Emmanuel

```
✅ Design concept stabilisé.
→ Lancer /research puis /plan pour implémenter.
```

---

## Règles

- Poser UNE question à la fois — pas de liste de 10 questions en bloc
- Être adversarial : challenger les hypothèses implicites
- Si Emmanuel dit "comme dans Finary" → demander exactement quelle fonctionnalité Finary
- Si Emmanuel dit "simple" → demander ce qui est simple selon lui
- Arrêter quand le design concept est clair, pas avant
