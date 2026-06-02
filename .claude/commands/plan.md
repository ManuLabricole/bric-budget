# /plan — Phase Plan (après /research)

> Inspiré de "Solving Hard Problems" (Dex) et "Principles for AI Coding" (Matt Pocock)
> But : comprimer l'INTENTION en étapes exécutables avec des snippets de code réels.
> ⛔ Emmanuel DOIT valider le plan avant que Claude commence à coder.

---

## Quand utiliser

- Après `/research` sur une tâche non-triviale
- Avant d'implémenter quoi que ce soit de > 1 fichier
- Inutile pour bugfix trivial — aller directement au code

---

## Protocole

### 1. Lire le fichier research

```bash
cat .claude/research_<slug>.md
```

Si research absente → lancer `/research` d'abord.

### 2. Lire les specs UI si applicable

```bash
# UI : chercher dans la documentation
ls documentation/
cat documentation/ui_budget_specs.md | grep -A20 "<section concernée>"
```

### 3. Produire le plan

Format exact — chaque étape doit être **verifiable** et **atomique** :

```markdown
# Plan : <nom de la tâche>
Date : <date>
Branch : <branche git>

## Étapes

### Étape 1 — <nom court> [~N min]
**Fichier** : `src/<app>/file.py`
**Quoi** : Ajouter vue `xxx_yyy(request)` → retourne fragment HTMX

```python
# Snippet exact à écrire
@require_POST
def xxx_yyy(request):
    obj = get_object_or_404(Model.objects.for_user(request.user), pk=request.POST.get("id"))
    ...
    return render(request, "app/_fragment.html", ctx)
```

**Test** : `make test` → vérifier que test_xxx_yyy passe

---

### Étape 2 — <nom court> [~N min]
**Fichier** : `src/templates/<app>/_fragment.html`
**Quoi** : Template HTMX avec `hx-post` + `hx-target`

```html
<!-- Snippet exact -->
<div id="panel-content">
  <form hx-post="{% url 'app:xxx_yyy' %}" hx-target="#panel-content">
    {% csrf_token %}
    ...
  </form>
</div>
```

**Test** : GET via `Client()` Django shell → vérifier status 200

---

### Étape 3 — URL + Test [~N min]
**Fichier** : `src/<app>/urls.py`
```python
path("xxx/yyy/", views.xxx_yyy, name="xxx_yyy"),
```

**Fichier test** : `src/tests/test_xxx.py`
```python
def test_xxx_yyy_requires_auth(client):
    ...
```

## Vérification finale

- [ ] `make test` → N passed / 0 failed
- [ ] `make check` → 0 erreurs
- [ ] GET + POST testés via Django Client
- [ ] Aucun `for_user` manquant
- [ ] Aucun `print()` introduit

## Périmètre
- Fichiers modifiés : N
- Fichiers créés : N
- Lignes de code : ~N
- Migrations : oui/non
```

### 4. Attendre la validation d'Emmanuel

```
📋 Plan prêt → .claude/plan_<slug>.md
⏳ En attente de ta validation avant de coder.

Questions : [si points ambigus]
Risques : [si contraintes à signaler]
```

**⛔ Ne pas coder sans "go" explicite d'Emmanuel.**

---

## Règles

- Chaque étape contient un snippet de code réel (pas de pseudo-code vague)
- Chaque étape contient sa méthode de test
- Maximum 5-6 étapes — si plus, découper en deux tâches
- Le plan est révisable — si Emmanuel change d'avis, réécrire le plan
- Ne pas inclure les refactorisations non-demandées dans le plan
