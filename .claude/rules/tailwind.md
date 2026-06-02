---
paths:
  - "src/templates/**"
  - "**/tailwind.config.*"
---

# Tailwind / design tokens — conventions BricBudget

- **Classes utilitaires Tailwind uniquement** — pas de CSS custom sauf besoin réel justifié.
- Couleurs & polices : lire depuis `window.BRICBUDGET_TOKENS` (exposé via context processor +
  `tailwind.config`). **Jamais** de hex ou de police hardcodé en JS ni en style inline.
- Source de vérité des tokens : Python (`constants.py`) → `tailwind.config` → JS, synchronisés
  par un test pytest. Si tu changes une couleur, change-la à la source, pas dans le template.

## Largeur fixe sur un bouton dont le texte varie
- Span invisible (texte le plus long) + overlay absolu, classes core uniquement (pas de `min-w` arbitraire) :
  `<span class="relative"><span class="invisible" aria-hidden="true">Texte long</span><span class="absolute inset-0 …">{{ vrai_texte }}</span></span>`
