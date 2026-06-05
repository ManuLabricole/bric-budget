// BricBudget — Treemap de répartition (page bilan patrimoine).
//
// Signature :
//   BricCharts.initTreemap(el, data, options)
//     data    : { segments: [{ name, value, color }], total }  (même shape que le donut)
//     options : { onSegmentClick: function(segmentData) {} }    — optionnel
//
// Toggle avec donut.js : même données, deux rendus. ⛔ Couleurs = data.segments[].color.

window.BricCharts = window.BricCharts || {};

(function (BC) {
  BC.initTreemap = function (el, data, options) {
    if (!el || !data) return null;
    options = options || {};
    var T = BC.T;
    var FONT = BC.FONT;

    var chart = echarts.init(el, null, { renderer: "svg" });
    var total = data.total || 0;

    var nodes = (data.segments || []).map(function (s) {
      var color = (s.itemStyle && s.itemStyle.color) || s.color;
      return {
        name: s.name,
        value: s.value,
        itemStyle: {
          color: color,
          borderColor: "transparent",
          borderWidth: 0,
          gapWidth: 2,
        },
      };
    });

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        confine: true,
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 11, fontFamily: FONT },
        formatter: function (p) {
          var pct = total ? ((p.value / total) * 100).toFixed(1) : "0";
          var val = Math.round(p.value).toLocaleString("fr-CH");
          return p.name + "<br /><b>" + val + " CHF</b> (" + pct + "%)";
        },
      },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          width: "100%",
          height: "100%",
          itemStyle: { gapWidth: 2, borderWidth: 0 },
          label: {
            color: "#ffffff",
            fontFamily: FONT,
            fontSize: 9,
            fontWeight: 600,
            formatter: function (p) {
              var pct = total ? Math.round((p.value / total) * 100) : 0;
              return pct >= 8 ? p.name + "\n" + pct + "%" : "";
            },
          },
          data: nodes,
        },
      ],
    });

    if (typeof options.onSegmentClick === "function") {
      chart.on("click", function (p) {
        options.onSegmentClick({ name: p.name, value: p.value });
      });
    }

    window.addEventListener("resize", function () {
      chart.resize();
    });
    return chart;
  };
})(window.BricCharts);
