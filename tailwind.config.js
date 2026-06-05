/** @type {import('tailwindcss').Config} */
//
// Source de vérité de la palette BricBudget — utilisé par le build CSS.
// Doit rester synchro avec src/static/js/tokens.js qui expose window.BRICBUDGET_TOKENS
// pour les scripts JS (charts ECharts, etc.).
//
// Build : `npm run build:css` (ou `make build-css`)
//
module.exports = {
  content: [
    // Scanner les templates Django pour les classes Tailwind utilisées.
    "./src/templates/**/*.html",
    "./src/**/templates/**/*.html",
    "./src/static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui"],
      },
      // Durée d'animation globale de l'app : défaut de toutes les utilities
      // `transition-*` sans `duration-N` explicite (Tailwind par défaut : 150ms).
      // Léger ralentissement → transitions plus douces (chevron nav, accordéon, hovers, panels).
      transitionDuration: {
        DEFAULT: "250ms",
      },
      colors: {
        "surface-1":      "#0e0e27",
        "surface-2":      "#131314",
        "surface-3":      "#131314",
        "surface-hover":  "#1d1d1f",
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
      },
    },
  },
  // safelist : on force la génération de classes utilisées dynamiquement par les vues
  // (ex: bg-gold/10 pour les badges générés en Python via template tags).
  safelist: [
    "bg-gold/10", "bg-gold/15", "bg-gold/20", "border-gold/30",
    "bg-income/10", "bg-income/20", "text-income",
    "bg-expense/10", "bg-expense/20", "text-expense",
    "opacity-40", "opacity-80",
  ],
  plugins: [],
};
