// static/js/tokens.js — Source de vérité des design tokens consommés par les charts.
//
// Doit rester synchronisé avec tailwind.config.js (palette Tailwind utilisée
// par les templates HTML). Si tu modifies la palette, mets à jour les DEUX fichiers
// puis lance `make build-css` pour reconstruire le CSS.
//
// Pourquoi un fichier séparé du HTML ? Quand on utilisait le CDN play-mode,
// tailwind.config était inline dans <script> et lisible depuis window. Avec le build
// statique, le config n'est plus chargé en runtime — on duplique donc la palette ici.
// Test pytest `test_tokens_match_tailwind_config` vérifie la synchro.

window.BRICBUDGET_TOKENS = {
  "surface-1":      "#0e0e27",
  "surface-2":      "#131314",
  "surface-3":      "#131314",
  "surface-hover":  "#1c1c1e",
  "edge":           "#2a2a2e",
  "edge-subtle":    "#3a3a3f",
  "text-base":      "#edf0f5",
  "text-secondary": "#e0e2e7",
  "text-muted":     "#8b8d97",
  "text-disabled":  "#4a4c55",
  "gold":           "#f2c086",
  "gold-hover":     "#e8ab6a",
  "income":         "#4dbf93",
  "expense":        "#e5494a",
  "warning":        "#f97316",
};

window.BRICBUDGET_FONT = "Inter, ui-sans-serif, system-ui";
