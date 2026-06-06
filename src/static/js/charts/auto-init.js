// charts/auto-init.js — Initialisation déclarative des charts ECharts.
//
// Convention HTML (au lieu de scripts inline d'init dans chaque template) :
//
//   <div id="sankey-chart" data-chart="sankey"
//        data-chart-data="sankey-data"
//        data-on-click-url="/budget/categorie/{slug}/"></div>
//   {{ payload|json_script:"sankey-data" }}
//
// Au DOMContentLoaded ET à chaque htmx:afterSwap, on scanne le DOM et on
// initialise tous les `[data-chart]` non encore traités. Les containers réinjectés
// par HTMX (panel transactions, fragment cashflow…) sont auto-réinitialisés.
//
// Pourquoi : élimine ~30 lignes de <script> répétées dans index.html / category_detail.html.
// Source de vérité : le HTML décrit le chart, le JS l'exécute. Pas d'imbrication Python ↔ JS.

(function () {
  function initChartsIn(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-chart]:not([data-chart-initialized])").forEach(function (el) {
      var kind = el.dataset.chart;            // "sankey" | "donut" | "bar" | "activity"
      var dataId = el.dataset.chartData;
      var dataEl = dataId && document.getElementById(dataId);
      if (!dataEl) return;

      var data;
      try {
        data = JSON.parse(dataEl.textContent);
      } catch (e) {
        console.warn("auto-init: invalid JSON for #" + dataId, e);
        return;
      }

      var opts = {};

      // URL template pour onClick : "/budget/categorie/{slug}/" → remplace {slug}
      if (el.dataset.onClickUrl) {
        var tmpl = el.dataset.onClickUrl;
        var handler = function (node) {
          if (node && node.slug) window.location.href = tmpl.replace("{slug}", node.slug);
        };
        opts.onNodeClick = handler;
        opts.onSegmentClick = handler;
      }

      var fnByKind = {
        sankey: window.BricCharts && BricCharts.initSankey,
        donut: window.BricCharts && BricCharts.initDonut,
        bar: window.BricCharts && BricCharts.initBar,
        activity: window.BricCharts && BricCharts.initActivity,
        balance: window.BricCharts && BricCharts.initBalance,
        treemap: window.BricCharts && BricCharts.initTreemap,
      };
      var fn = fnByKind[kind];
      if (typeof fn === "function") {
        fn(el, data, opts);
        el.dataset.chartInitialized = "1";
      } else {
        console.warn("auto-init: BricCharts.init" + kind + " not loaded");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initChartsIn(document);
  });

  // HTMX swap → réinitialiser les charts dans la zone fraîchement injectée.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    initChartsIn(e.target);
  });

  // Ferme tous les <details> de filtres quand on clique en dehors.
  // querySelectorAll au lieu de getElementById : plusieurs instances peuvent coexister
  // (ex: filtre comptes dans la page principale ET dans le right panel).
  document.addEventListener("click", function (e) {
    ["accounts-filter-details", "categories-filter-details"].forEach(function (id) {
      document.querySelectorAll("#" + id + "[open]").forEach(function (el) {
        if (!el.contains(e.target)) {
          el.removeAttribute("open");
        }
      });
    });
  });
})();
