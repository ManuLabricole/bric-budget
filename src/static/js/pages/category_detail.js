// pages/category_detail.js — Logique spécifique à la page détail catégorie.
//
// Deux responsabilités :
//   1. Aligner la hauteur de la carte donut sur la carte cashflow (égalisation visuelle).
//   2. Refresh du cashflow card après toggle_ignore depuis le panneau détail.
//
// L'init des charts est déléguée à auto-init.js (data-chart attrs sur les containers).

(function () {
  function alignDonutToCashflow() {
    var cashflowCard = document.getElementById("cashflow-card");
    var donutCard = document.getElementById("donut-card");
    if (cashflowCard && donutCard) {
      donutCard.style.minHeight = cashflowCard.offsetHeight + "px";
    }
  }

  // Premier appel au DOMContentLoaded — après que auto-init.js ait posé les charts.
  document.addEventListener("DOMContentLoaded", alignDonutToCashflow);

  // Refresh Sankey + KPIs après toggle_ignore depuis le panneau détail.
  //
  // Flux :
  //   1. toggle_ignore (close_on_back=True) injecte [data-cashflow-refresh] dans
  //      le panneau → #panel-content est swappé par HTMX → htmx:afterSwap fire.
  //   2. Le listener détecte le signal, déclenche htmx.ajax vers /cashflow/
  //      → #cashflow-card innerHTML est remplacé → second htmx:afterSwap fire.
  //   3. auto-init.js (déjà branché sur htmx:afterSwap) ré-initialise le Sankey
  //      sur le nouveau container. On se contente de ré-aligner la hauteur ici.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target) return;

    // Étape 1 : un fragment portant [data-cashflow-refresh] vient d'être swappé
    // (overlay #panel-content OU carte inline #cat-tx-detail après toggle_ignore)
    // → recharger le Sankey/KPIs du cashflow card.
    if (target.id === "panel-content" || target.id === "cat-tx-detail") {
      var refreshEl = target.querySelector("[data-cashflow-refresh]");
      if (refreshEl) {
        htmx.ajax("GET", refreshEl.getAttribute("data-cashflow-refresh"), {
          target: "#cashflow-card",
          swap: "innerHTML",
        });
      }
    }

    // Étape 2 : cashflow-card swappé → auto-init va ré-instancier le Sankey,
    // on ré-aligne juste la hauteur du donut.
    if (target.id === "cashflow-card") {
      alignDonutToCashflow();
    }
  });
})();
