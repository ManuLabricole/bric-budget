# /diagnose — Debugging structuré

> Adapté de `/diagnose` (Matt Pocock).
> But : éviter le debugging en aveugle. Loop disciplinée reproduire → hypothèse → instrumenter → fix → test de régression.

---

## Quand utiliser

- Bug reproductible mais cause inconnue
- Comportement inattendu en prod qu'on ne comprend pas
- Régression : ça marchait, ça ne marche plus
- **Pas nécessaire** pour les bugs triviaux (typo, condition inversée évidente)

---

## Protocole

### 1. Reproduire — c'est la première étape, jamais skipper

Si on ne peut pas reproduire, on ne peut pas fixer. Ne jamais tenter un fix sans repro.

```
- Quelle action exacte déclenche le bug ?
- Sur quelle page / route / commande ?
- Quel utilisateur ? Quelles données ?
- Quel comportement attendu vs observé ?
```

Reproduire d'abord en local via `make up` + browser ou `manage.py shell` + `Client()`.

### 2. Minimiser

Réduire au plus petit cas qui reproduit :
- Une seule transaction au lieu de 100
- Un seul user au lieu d'une session multi-onglets
- Un seul fichier au lieu d'un batch d'imports

Si tu ne sais pas réduire → le bug n'est pas compris, retour étape 1.

### 3. Hypothèse explicite

Écrire **une seule hypothèse** : "Je pense que X cause Y parce que Z."

Pas plusieurs en parallèle. Tester une à la fois, sinon tu confondras les causes.

Sources d'hypothèses prioritaires (par fréquence dans ce projet) :
1. **IDOR / queryset filtré manquant** — toujours vérifier `for_user()`, `members=request.user`
2. **Decimal/float confusion** — `Decimal(float)` au lieu de `Decimal(str(float))`
3. **Session state stale** — état UI vieux vs DB fraîche
4. **HTMX swap mauvaise cible** — `hx-target` qui pointe vers un ID absent
5. **Template block name** — `{% block panel_left %}` vs `{% block content %}` dans `base_app.html`
6. **Migration manquante** — modèle modifié sans `makemigrations`
7. **N+1 / query count** — boucle qui déclenche une SQL par item

### 4. Instrumenter — pas modifier

Ajouter du logging temporaire, des `import pdb; pdb.set_trace()`, ou exécuter en `manage.py shell` pour observer l'état.

**Ne pas modifier le code de production** pendant l'instrumentation. C'est de la lecture, pas de l'écriture.

```python
# Pattern d'instrumentation temporaire (à virer après fix)
logger.debug(f"DIAG state before={tx.is_ignored} user={request.user.id} qs={qs.query}")
```

### 5. Confirmer ou réfuter l'hypothèse

L'output de l'instrumentation confirme ou réfute. Si réfuté → revenir étape 3 avec une nouvelle hypothèse. **Ne jamais coder un fix sans hypothèse confirmée.**

### 6. Fix + test de régression

Une fois la cause identifiée :
1. Écrire un test qui reproduit le bug (rouge)
2. Implémenter le fix (vert)
3. Vérifier que le test passe + tous les autres restent verts
4. Retirer l'instrumentation temporaire

```python
@pytest.mark.django_db
def test_<bug-name>_does_not_recur():
    # Setup qui reproduit le bug
    ...
    # Assertion qui aurait échoué avant le fix
    assert ...
```

### 7. Documenter si surprise

Si la cause était non-évidente, ajouter une mémoire :
- Pattern récurrent → `feedback_<topic>.md`
- Anti-pattern Django/HTMX → `MEMO.md` section "Pièges connus"
- Décision archi → `/decide`

---

## Anti-patterns à rejeter

- ❌ "Je vais essayer de toucher à X pour voir" → c'est shotgun debugging, fais une hypothèse d'abord
- ❌ Fix sans repro → tu ne sais pas si c'est fixé
- ❌ Fix sans test de régression → ça reviendra
- ❌ Modifier 5 choses en même temps → impossible de savoir laquelle a fixé
- ❌ Garder l'instrumentation après le fix → pollue les logs prod

## Output attendu

```
🐛 Bug : <description courte>
🔍 Hypothèse confirmée : <cause exacte>
🔧 Fix : <fichier:ligne — change minimal>
✅ Test régression : <test_xxx ajouté>
📋 Mémoire ajoutée : <si applicable>
```