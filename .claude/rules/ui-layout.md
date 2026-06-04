---
paths:
  - "src/templates/**"
  - "src/static/js/charts/**"
---

# Layout & patterns UI — BricBudget (chargé sur les templates + charts)

> **Grammaire UI extraite du flow Budget (livré, stable).** Tout nouvel écran de
> navigation (Patrimoine, etc.) la réutilise : même layout, mêmes conventions
> d'onglets / panels / graphes. But : ne pas re-déduire à chaque écran.
> Réf vivante — mettre à jour quand un pattern se stabilise.

## Layout 3 zones (`base_app.html`)
- `[ sidebar 240px fixe ] | [ zone principale flex-1 ] | [ right-panel 384px ]`
- Deux blocs Django à remplir : `{% block panel_left %}` / `{% block panel_right %}`.
- Panel droit = soit **Distribution** (donut / treemap), soit **détail contextuel**
  (transaction sélectionnée, détails compte). Carte : `bg-surface-3/70 … border-edge/60 rounded-xl`.

## Flow liste → détail → zoom (le pattern Budget, à calquer)
1. **Page liste** : graphe en haut · tabs au milieu · distribution à droite.
2. **Clic sur un item** (catégorie, compte) → redirige vers une **page zoom** dédiée.
3. **Page zoom** : même grammaire (graphe + liste transactions + panneau détail à droite).
- Budget : liste catégories → `budget/categorie/<slug>/`.
- Patrimoine : liste comptes → `patrimoine/compte/<id>/`. Identique.

## Onglets (tabs)
- Onglet actif en **session Django** — jamais d'URL param, jamais d'état JS.
- Switch d'onglet = requête HTMX → partial `_xxx.html`, swap de la zone concernée.
- Surbrillance active : `text-gold bg-surface-hover/30` ; inactif : `text-text-muted hover:text-gold`.

## Sélecteurs (période, empilé/standard, treemap/donut)
- Boutons HTML qui rappellent une fonction du chart (`chart.renderX(...)`) **et** persistent
  l'état en session côté serveur (PRG). Pas d'état uniquement client.
- Bouton actif : pill `bg-surface-hover` ; les autres en `text-text-muted`.

## Graphes (ECharts, auto-init déclaratif)
- `<div data-chart="donut" data-chart-data="donut-data">` + `{{ data|json_script:"donut-data" }}`.
- `auto-init.js` instancie ; un module par type dans `static/js/charts/`
  (`donut`, `bar`, `sankey`, `activity`, `balance`, `treemap`…). Signature `BC.initX(el, data)`.
- Redirection au clic : `data-on-click-url="/budget/categorie/{slug}/"` (placeholder remplacé).
- ⛔ Couleurs / police **uniquement** via `BC.T` / `BC.FONT` (tokens). Jamais de hex ni font inline.
- Logique buckets temporels réutilisable : voir `activity.js` (`buildBuckets`, `parseLocal`, `monday`).

## Composants transaction réutilisables (`budget/partials/`)
- `_panel_tx_list.html` — liste scrollable de transactions.
- `_panel_tx_row.html` — une ligne (icône catégorie, libellé, montant tabular-nums).
- `_panel_tx_detail.html` — détail d'une transaction sélectionnée (panneau droit).
- `_panel_tx_rows_append.html` — pagination infinie (HTMX append).
- → réutiliser tels quels dans Patrimoine (onglet Transactions + page compte).

## SOON (feature pas encore prête)
- `{% include "components/badges/soon.html" with extra_class="ml-auto" %}` sur le lien.
- Catégorie / écran non fonctionnel → page rendue en **état SOON**, jamais de 404.

## Édition inline (champ éditable ✏️)
- Affichage : valeur + crayon `✏️`. Clic → GET partial champ en mode édition (HTMX swap de la ligne).
- Submit → POST, **validation dans la vue** (pas de Form), re-render de la ligne en lecture.
- Valeur vide affichée `-` (ex. IBAN absent). `hx-disabled-elt="this"` contre le double-submit.
