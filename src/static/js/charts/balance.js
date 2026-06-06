// BricBudget — Courbe net worth (page bilan patrimoine).
//
// Signature :
//   BricCharts.initBalance(el, data, options)
//     data : {
//       dates  : ["2026-03-10", ...]            une date ISO par jour
//       total  : [1500.0, ...]                  somme net worth (mode standard)
//       series : [{ name, color, values:[...] }]  une série par compte/classe (mode empilé)
//       anchored, complete : bool
//     }
//     options : { stacked: bool }  — sinon lu depuis el.dataset.stacked ("1")
//
// Mode empilé (stacked) : aires empilées, une par compte/classe (couleur = data.series[].color).
// Mode standard         : ligne gold unique = somme de tous les comptes (data.total).
// ⛔ Couleurs : data.series[].color (venu de Python) + BC.T pour l'UI. Jamais de hex en dur.

window.BricCharts = window.BricCharts || {};

(function (BC) {
  // "2026-03-10" → "10 mars" (libellé d'axe court, locale FR).
  function shortDate(iso) {
    var p = iso.split("-");
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  }

  BC.initBalance = function (el, data, options) {
    if (!el || !data) return null;
    options = options || {};
    var T = BC.T;
    var FONT = BC.FONT;

    var stacked =
      options.stacked !== undefined
        ? !!options.stacked
        : el.dataset.stacked === "1";
    stacked = stacked && Array.isArray(data.series) && data.series.length > 0;

    var chart = echarts.init(el, null, { renderer: "svg" });

    // Dégradé vertical : couleur de la courbe en haut → transparent vers le bas,
    // fade rapide (transparent dès ~55% de la hauteur).
    function fade(hex) {
      return {
        type: "linear",
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: BC.hexToRgba(hex, 0.45) },
          { offset: 0.55, color: BC.hexToRgba(hex, 0.04) },
          { offset: 1, color: BC.hexToRgba(hex, 0) },
        ],
      };
    }

    var series;
    if (stacked) {
      // Aires empilées — une par compte/classe.
      series = data.series.map(function (s) {
        return {
          name: s.name,
          type: "line",
          stack: "networth",
          showSymbol: false,
          lineStyle: { width: 1.2, color: s.color },
          areaStyle: { color: fade(s.color) },
          itemStyle: { color: s.color },
          emphasis: { focus: "series" },
          data: s.values,
        };
      });
    } else {
      // Standard : ligne gold unique = somme de tous les comptes.
      series = [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5, color: T["gold"] },
          areaStyle: { color: fade(T["gold"]) },
          itemStyle: { color: T["gold"] },
          data: data.total,
        },
      ];
    }

    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 250,
      animationDurationUpdate: 250,
      grid: { left: 4, right: 12, top: 14, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 10, fontFamily: FONT },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var dateLabel = shortDate(params[0].axisValue);
          var out =
            '<div style="font-size:9px;color:' +
            T["text-muted"] +
            ';margin-bottom:3px">' +
            dateLabel +
            "</div>";
          params.forEach(function (p) {
            if (p.value == null) return;
            var col = typeof p.color === "string" ? p.color : T["gold"];
            var amount =
              '<span style="color:' +
              col +
              ";font-weight:500;font-family:" +
              FONT +
              '">' +
              Math.round(p.value).toLocaleString("fr-CH") +
              " CHF</span>";
            out +=
              '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:10px">';
            if (params.length > 1) {
              out +=
                '<span style="color:' +
                T["text-muted"] +
                ';display:flex;align-items:center;gap:4px;font-family:' +
                FONT +
                '">' +
                p.marker +
                p.seriesName +
                "</span>";
            }
            out += amount + "</div>";
          });
          return out;
        },
      },
      xAxis: {
        type: "category",
        data: data.dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: T["edge"] } },
        axisTick: { show: false },
        axisLabel: {
          color: T["text-muted"],
          fontSize: 10,
          fontFamily: FONT,
          formatter: shortDate,
          hideOverlap: true,
        },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: T["edge"], opacity: 0.35 } },
        axisLabel: {
          color: T["text-muted"],
          fontSize: 10,
          fontFamily: FONT,
          formatter: function (v) {
            return Math.round(v / 1000) + " k";
          },
        },
      },
      series: series,
    });

    window.addEventListener("resize", function () {
      chart.resize();
    });
    return chart;
  };
})(window.BricCharts);
