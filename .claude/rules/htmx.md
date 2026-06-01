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
- **Jamais** de `{# … #}` multiligne dans un partial → `{% comment %} … {% endcomment %}`.

## UX
- `hx-indicator` sur les actions longues ; `hx-disabled-elt="this"` contre le double-submit.
- Erreurs : renvoyer un partial d'erreur + statut HTTP correct — jamais d'échec silencieux.
- Fermer un `<details>` : `this.closest('details').removeAttribute('open')` (pas un handler parent).

## État UI
- Filtres / période / onglets vivent en **session Django** — pas d'URL params, pas d'état en JS.
