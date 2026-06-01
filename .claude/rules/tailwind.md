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
