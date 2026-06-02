# /research — Phase Research avant d'implémenter

> Inspiré de "Solving Hard Problems in Complex Codebases" (Dex — AI Engineer)
> But : comprimer la vérité du codebase sur la tâche cible AVANT de planifier.
> Output : fichier `research_<slug>.md` dans `.claude/` — lu par `/plan`

---

## Quand utiliser

- Avant toute feature impliquant > 1 fichier
- Avant tout refactoring
- Quand on est incertain de l'impact d'un changement
- PAS nécessaire pour un bugfix trivial (< 10 lignes, 1 fichier évident)

---

## Protocole

### 1. Identifier le périmètre

Lire `CONTEXT.md` (état courant) et identifier l'issue GitHub cible :
```bash
unset GITHUB_TOKEN && gh issue view <numéro>
```
Lire `project/UBIQUITOUS_LANGUAGE.md` → module map pour identifier les apps concernées.

### 2. Explorer les apps concernées (vertical slices)

Pour chaque app impliquée :
```bash
# Structure
find src/<app>/ -name "*.py" | head -20

# Modèles impliqués
grep -n "class.*Model\|def.*:" src/<app>/models.py | head -30

# Vues impliquées
grep -n "^def \|^class " src/<app>/views.py | head -40

# URLs exposées
cat src/<app>/urls.py

# Tests existants
ls src/tests/
grep -rn "def test_" src/tests/ | grep -i <keyword> | head -20
```

### 3. Identifier les fichiers exacts et les lignes clés

Pour chaque fichier pertinent, noter :
- Le chemin exact
- Les numéros de ligne des fonctions/classes à modifier
- Les dépendances (imports, appels)

### 4. Vérifier les patterns existants

```bash
# Patterns HTMX dans les templates
grep -rn "hx-get\|hx-post\|hx-target\|hx-swap" src/templates/<app>/ | head -20

# Patterns de vue similaires déjà en place
grep -n "def budget_" src/budget/views.py | head -30

# Tests du même type
ls src/tests/
```

### 5. Produire le fichier research

Créer `.claude/research_<slug>.md` avec :

```markdown
# Research : <nom de la tâche>
Date : <date>

## Fichiers à modifier
- `src/<app>/views.py:L42-L67` — fonction `xxx` — [ce qu'on y change]
- `src/templates/<app>/_fragment.html` — [ce qu'on y change]

## Fichiers à créer
- `src/<app>/new_file.py` — [pourquoi]

## Tests existants à préserver
- `src/tests/test_xxx.py:L10` — `test_yyy` — [ce qu'il teste]

## Pattern à suivre
[extrait de code du pattern existant le plus proche]

## Points d'attention
- [dépendance non-évidente]
- [anti-pattern à éviter]
- [règle IDOR applicable]

## Périmètre estimé
- Lignes créées/modifiées : ~N
- Apps touchées : [liste]
- Migrations nécessaires : oui/non
```

### 6. Signaler à Emmanuel

```
✅ Research terminée → fichier .claude/research_<slug>.md
📋 Périmètre : N fichiers, ~N lignes
⚠️  Points d'attention : [liste courte]
→ Lancer /plan quand tu es prêt
```

---

## Règles

- Ne pas coder pendant la research — observer seulement
- Citer les fichiers avec `chemin:ligne` exact
- Si découverte d'un bug ou d'une dette → noter dans research mais ne pas corriger
- La research est jetable si le plan change — c'est normal
