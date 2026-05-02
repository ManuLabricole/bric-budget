// BricBudget — utilitaires partagés entre tous les charts ECharts.
// Charge les design tokens depuis window.BRICBUDGET_TOKENS (exposé dans base.html).
// ⛔ Règle : jamais de hex ou de police hardcodée ici — tout vient des tokens.

window.BricCharts = window.BricCharts || {};

(function (BC) {
  // Alias courts — disponibles dans sankey.js et donut.js via BC.T et BC.FONT
  BC.T    = window.BRICBUDGET_TOKENS;
  BC.FONT = window.BRICBUDGET_FONT;

  // applyFactor — assombrit une couleur hex en multipliant chaque canal RGB par factor.
  // factor=0 → noir, factor=1 → couleur d'origine, factor=1.2 → légèrement plus clair.
  // Utilisé pour les dégradés Sankey (sombre côté pool, lumineux côté catégorie).
  BC.applyFactor = function (hex, factor) {
    if (!hex || hex.length < 7) return "rgba(80,80,80,1)";
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${Math.round(r * factor)},${Math.round(g * factor)},${Math.round(b * factor)},1)`;
  };
})(window.BricCharts);
