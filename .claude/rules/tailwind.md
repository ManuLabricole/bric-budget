---
paths:
  - "src/templates/**"
  - "**/tailwind.config.*"
---

# Tailwind / design tokens — conventions BricBudget

- ⚠️ **Tailwind est compilé** (`npm run build:css` → `src/static/css/tailwind.css`), **pas** de
  JIT runtime. Une classe utilitaire utilisée pour la **première fois** ne fait **rien** tant que
  le CSS n'est pas rebuildé (absente du bundle). Après toute nouvelle classe : `npm run build:css`
  + vérifier `grep "\.<classe>{" src/static/css/tailwind.css`. Ne jamais conclure « cache navigateur »
  sans avoir vérifié le bundle. Le `tailwind.css` compilé est committé (artefact versionné).
- **Durée d'animation globale** : `theme.extend.transitionDuration.DEFAULT` dans `tailwind.config.js`
  (250ms). C'est le défaut de **toutes** les utilities `transition-*` sans `duration-N` explicite.
  Ne pas éparpiller des `duration-[…]` ad hoc — laisser hériter du global.
- **Classes utilitaires Tailwind uniquement** — pas de CSS custom sauf besoin réel justifié.
- Couleurs & polices : lire depuis `window.BRICBUDGET_TOKENS` (exposé via context processor +
  `tailwind.config`). **Jamais** de hex ou de police hardcodé en JS ni en style inline.
- Source de vérité des tokens : Python (`constants.py`) → `tailwind.config` → JS, synchronisés
  par un test pytest. Si tu changes une couleur, change-la à la source, pas dans le template.

## Div interactive / dépliante (catégories budget, classes patrimoine, comptes, imports…)
- **Surface** : fond normal `bg-surface-3` (#131314), survol `hover:bg-surface-hover` (#1d1d1f).
  Ces deux tokens sont la convention pour TOUTE ligne/carte cliquable ou dépliante. Pas d'overlays
  `/20` ad hoc, pas de hex en dur.
- **Border de séparation au dépliage** (un `<details>` qui ouvre, header ↔ enfants) : ⛔ ne jamais
  faire apparaître une border via une variante `group-open:border-b group-open:border-<couleur>`
  combinée à `transition-colors` → **flash clair** (transition-colors anime la border-color depuis
  le défaut Tailwind clair). Pattern correct = **couleur de border CONSTANTE**, seule la **largeur**
  bascule : `border-edge/50 border-b-0 group-open/x:border-b` (la largeur n'est pas animée → net).

## Largeur fixe sur un bouton dont le texte varie
- Span invisible (texte le plus long) + overlay absolu, classes core uniquement (pas de `min-w` arbitraire) :
  `<span class="relative"><span class="invisible" aria-hidden="true">Texte long</span><span class="absolute inset-0 …">{{ vrai_texte }}</span></span>`
