# /improve — Audit d'opportunités de deepening

> Adapté de `/improve-codebase-architecture` (Matt Pocock).
> Inspiré du principe "Deep Modules, Simple Interfaces" (John Ousterhout — A Philosophy of Software Design).
> But : identifier les modules trop fins, les interfaces trop larges, les duplications d'abstraction.

---

## Quand utiliser

- Périodiquement (toutes les 2-3 semaines) pour éviter la dérive
- Après l'ajout d'une grosse feature (Phase 2F imports, Phase 3A patrimoine…)
- Quand tu sens que le code grossit sans simplifier
- **Pas nécessaire** sur un module fraîchement écrit (donner le temps au pattern d'émerger)

---

## Protocole

### 1. Cartographier — N'observer qu'une seule app à la fois

Choisir UNE app Django : `budget/`, `accounts/`, `transactions/`, `imports/`, `users/`.

```bash
# Taille des modules
wc -l src/<app>/**/*.py | sort -n

# Nombre de fonctions par fichier
grep -c "^def \|^class " src/<app>/views/*.py

# Dépendances entre fichiers (imports internes)
grep -rn "from <app>\." src/<app>/ | head -20
```

### 2. Repérer les 5 anti-patterns

#### A. Module fin (shallow)

Un fichier qui n'expose qu'une seule fonction de 10 lignes ne mérite peut-être pas son propre fichier. **Sauf** s'il a une responsabilité distincte (ex: `connectors/yuh/parser.py`).

> **Test** : si je supprime ce fichier et inline son contenu ailleurs, est-ce que la complexité globale baisse ?

#### B. Interface large

Une vue Django avec 8 paramètres POST, 4 cas de figure, 200 lignes → l'interface est trop large.

> **Fix** : extraire en 2-3 vues spécialisées + helpers partagés.

#### C. Fonctions duplicates / quasi-duplicates

```bash
# Détecter signatures similaires
grep -E "^def [a-z_]+\(" src/<app>/views/*.py | sort | uniq -c | sort -rn | head -10
```

> **Fix** : abstraction commune si ≥ 3 usages, sinon laisser duppliqué (règle de 3).

#### D. Couplage transversal (god module)

Un module importé partout = soit c'est `models.py` (légitime), soit c'est un god module (illegitime).

```bash
grep -rl "from <app> import " src/ | wc -l
```

> **Fix** : séparer en sous-modules thématiques. Ex: `budget/views.py` → `budget/views/transactions.py`, `budget/views/rules.py`, `budget/views/categories.py`.

#### E. Profondeur insuffisante (interfaces qui leak l'implémentation)

```python
# Mauvais : leak SQL
def get_transactions(filters, order_by, limit, prefetch_related):
    ...

# Bon : signature simple, complexité cachée
def transactions_for_user(user, period) -> QuerySet[Transaction]:
    ...
```

### 3. Produire un rapport

Format strict :

```markdown
## Audit deepening — <app> — <date>

### 🔴 Critique (à traiter avant prochaine feature)
1. **<file:lignes>** — <anti-pattern> — <fix proposé en 1 phrase>

### 🟡 Important (Phase suivante)
1. ...

### 🟢 Opportunités (à garder en tête)
1. ...

### 📊 Métriques
- Fichiers app : N
- Lignes app : N
- Plus gros fichier : <name> (N lignes)
- Plus de couplage : <module> importé dans M fichiers
```

### 4. Stop — ne pas refactor immédiatement

Le rapport est une **carte**, pas une commande d'exécution. Le user décide quelles opportunités traiter, dans quel ordre, sur quelle branche.

Si > 3 opportunités critiques → proposer de créer des issues GitHub pour les tracker.

---

## Anti-patterns à éviter dans ce protocole

- ❌ Auditer plusieurs apps en un seul appel → diluer le focus, output trop long
- ❌ Refactor en même temps que l'audit → un audit = lire seul, écrire après
- ❌ Suggérer des refactos sans gain mesurable → règle d'Ousterhout : "Strategic vs Tactical programming"
- ❌ Renommer pour renommer → préférer changer l'architecture

## Output attendu

```
🔍 Audit deepening : <app>
📊 N fichiers · M lignes · plus gros : <file> (X lignes)
🔴 N critiques · 🟡 N importants · 🟢 N opportunités
👉 Prochaine action recommandée : <une seule, la plus haute valeur>
```