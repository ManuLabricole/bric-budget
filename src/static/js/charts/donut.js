// BricBudget — Donut ECharts (dépenses par catégorie).
//
// Signature :
//   BricCharts.initDonut(el, data, options)
//     el      : élément DOM du conteneur
//     data    : objet { segments: [...], label: str, sign: str, total: number }
//     options : { onSegmentClick: function(segmentData) {} }  — optionnel

window.BricCharts = window.BricCharts || {};

(function (BC) {
  BC.initDonut = function (el, data, options) {
    if (!el || !data) return null;
    options = options || {};

    const T    = BC.T;
    const FONT = BC.FONT;

    const donut = echarts.init(el, null, { renderer: "svg" });

    // Formatage du montant centre — espace insécable cohérent avec le filtre |chf Django
    const totalFormatted = Math.round(data.total)
      .toLocaleString("fr-FR")
      .replace(/ /g, " ");

    donut.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 12, fontFamily: FONT },
        formatter: function (params) {
          const val = params.value.toLocaleString("fr-CH", { maximumFractionDigits: 0 });
          return `${params.name}<br /><b>${val} CHF</b> (${params.percent}%)`;
        },
      },
      // "graphic" : couche de dessin libre superposée au graphique.
      // Utilisé pour le label + montant au centre du donut (ECharts pie n'a pas de center-label natif).
      graphic: [
        {
          type: "text",
          left: "center",
          top: "38%",
          style: {
            text: data.label,
            fill: T["text-muted"],
            fontSize: 10,
            fontFamily: FONT,
          },
        },
        {
          type: "text",
          left: "center",
          top: "48%",
          style: {
            text: data.sign + totalFormatted + " CHF",
            fill: T["text-base"],
            fontSize: 13,
            fontWeight: "bold",
            fontFamily: FONT,
          },
        },
      ],
      series: [{
        type: "pie",
        radius: ["55%", "78%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          scale: true,
          scaleSize: 4,
        },
        data: data.segments,
      }],
    });

    // ── Click navigation — optionnel ─────────────────────────────────────────
    if (options.onSegmentClick) {
      donut.on("click", "series.pie", function (params) {
        options.onSegmentClick(params.data);
      });
    }

    window.addEventListener("resize", function () { donut.resize(); });
    return donut;
  };
})(window.BricCharts);
