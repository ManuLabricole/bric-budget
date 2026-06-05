// BricBudget — Courbe net worth (page bilan patrimoine).
//
// Signature :
//   BricCharts.initBalance(el, data, options)
//     data : {
//       dates  : ["2026-03-10", ...]            une date ISO par jour
//       total  : [1500.0, ...]                  somme net worth (mode standard)
//       series : [{ name, color, values:[...] }]  une série par classe (mode empilé)
//       anchored, complete : bool
//     }
//     options : { stacked: bool }  — sinon lu depuis el.dataset.stacked ("1")
//
// Mode empilé (stacked) : une aire par classe d'actifs (couleur = data.series[].color).
// Mode standard         : une seule aire (total), couleur gold.
// ⛔ Couleurs : data.series[].color (venu de Python/AssetClass) + BC.T pour l'UI. Jamais de hex en dur.

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

    var series;
    if (stacked) {
      series = data.series.map(function (s) {
        return {
          name: s.name,
          type: "line",
          stack: "networth",
          showSymbol: false,
          lineStyle: { width: 1, color: s.color },
          areaStyle: { color: s.color, opacity: 0.28 },
          itemStyle: { color: s.color },
          emphasis: { focus: "series" },
          data: s.values,
        };
      });
    } else {
      series = [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5, color: T["gold"] },
          areaStyle: { color: T["gold"], opacity: 0.12 },
          itemStyle: { color: T["gold"] },
          data: data.total,
        },
      ];
    }

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 4, right: 12, top: 14, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 12, fontFamily: FONT },
        valueFormatter: function (v) {
          return Math.round(v).toLocaleString("fr-CH") + " CHF";
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
