---
paths:
  - "src/templates/**"
---

# HTMX — conventions BricBudget (chargé sur les templates)

## Partials & réponses
- Réponse à une requête HTMX = **partial** préfixé `_` (`_xxx.html`), jamais la page complète.
- Détection côté vue : `request.headers.get("HX-Request")` (**header brut**, pas `request.htmx`).
- Cibler/échanger via `hx-target` / `hx-swap` ; déclencher des events serveur via le header de réponse `HX-Trigger`.

## Commentaires
- **Jamais** de `{# … #}` multiligne → `{% comment %} … {% endcomment %}`. Django ne ferme
  `{# #}` que sur **une seule ligne** ; un `{# #}` sur 2+ lignes **s'affiche en texte brut**.
- Nuance : il ne fuit que dans du contenu **réellement rendu** — un `{% include %}` (partial),
  un template racine (base.html), ou l'intérieur d'un `{% block %}`. Dans l'espace top-level
  d'un template qui `{% extends %}` (hors block), tout est ignoré → ne rend jamais. Dans le
  doute, **toujours `{% comment %}`** (réflexe à l'écriture, pas à la relecture).

## Toggle animé (déplier/replier, accordéon, rotation chevron)
- ⛔ Un toggle qui doit **s'animer** ne passe **pas** par un swap HTMX : `hx-swap="outerHTML"`
  remplace l'élément → une transition CSS ne se déclenche **jamais** sur un élément
  fraîchement inséré (rendu direct dans l'état final). Résultat = instantané, quelle que
  soit la `duration`.
- Pattern correct = **CSS pur, état persistant** : `<input type=checkbox class="sr-only">`
  masquée + variantes `group-has-[:checked]:` sur le conteneur `group` (chevron `rotate-180`,
  accordéon `grid-rows-[0fr]` → `grid-rows-[1fr]` + `overflow-hidden`). Les éléments persistent
  → la transition s'anime. Le label HTML (`<label for>`) toggle la checkbox.
- Persistance serveur = **fire-and-forget** : la checkbox émet `hx-post` `hx-trigger="change"`
  `hx-swap="none"`, la vue lit l'état réel (`"open" in request.POST`) et renvoie **204**.

## UX
- `hx-indicator` sur les actions longues ; `hx-disabled-elt="this"` contre le double-submit.
- Erreurs : renvoyer un partial d'erreur + statut HTTP correct — jamais d'échec silencieux.
- Fermer un `<details>` : `this.closest('details').removeAttribute('open')` (pas un handler parent).

## État UI
- Filtres / période / onglets vivent en **session Django** — pas d'URL params, pas d'état en JS.

## Composants inclus plusieurs fois
- Un partial `{% include %}` peut apparaître 2× dans le DOM (page + panel) → IDs dupliqués.
  `getElementById` ne voit que le 1er → utiliser `document.querySelectorAll("#foo")` + `forEach`.
