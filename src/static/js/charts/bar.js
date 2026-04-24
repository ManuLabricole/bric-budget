// BricBudget — Bar chart historique objectif (category_detail, tab "Objectif").
//
// Signature :
//   BricCharts.initBar(el, data)
//     el   : élément DOM conteneur
//     data : {
//       months       : ["Avr 2025", "Mai 2025", ...]
//       values       : [1234.5, 890.0, ...]             toujours positifs (abs)
//       urls         : ["/budget/period/month/2025/4/", ...]
//       target       : 800.0 | null
//       current_month: "2026-04"
//       cat_color    : "#e88c45"                        couleur hex de la catégorie
//     }
//
// Couleurs des barres :
//   - Mois actif (current_month)   → cat_color pleine
//   - Mois normal sous objectif    → cat_color assombrie (factor 0.35)
//   - Mois au-dessus de l'objectif → cat_color assombrie (factor 0.35, même style)
//     l'utilisateur voit déjà la ligne objectif comme référence visuelle
//
// Ligne pointillée = objectif mensuel, couleur cat_color atténuée
//
// ⛔ Règle : jamais de hex hardcodé sauf cat_color transmis depuis Python.
//    Les tokens UI (text-disabled, surface-hover, etc.) viennent de BC.T.

window.BricCharts = window.BricCharts || {};

(function (BC) {
  BC.initBar = function (el, data) {
    if (!el || !data) return null;

    var T    = BC.T;
    var FONT = BC.FONT;

    var chart = echarts.init(el, null, { renderer: "svg" });

    // Extraire les clés YYYY-MM depuis les URLs pour identifier le mois actif.
    // URL format : "/budget/period/month/<year>/<month>/"
    var monthKeys = data.urls.map(function (url) {
      var parts = url.replace(/\/$/, "").split("/");
      var year  = parts[parts.length - 2];
      var month = parts[parts.length - 1].padStart(2, "0");
      return year + "-" + month;
    });

    // Couleur inactive = catégorie assombrie (factor 0.3)
    var colorActive   = data.cat_color;
    var colorInactive = BC.applyFactor(data.cat_color, 0.3);

    var barData = data.values.map(function (v, i) {
      var isActive = monthKeys[i] === data.current_month;
      return {
        value: v,
        itemStyle: {
          color: isActive ? colorActive : colorInactive,
          // Pill shape : rayon max sur les 4 coins (top-left, top-right, bottom-right, bottom-left)
          borderRadius: [999, 999, 999, 999],
        },
        emphasis: {
          itemStyle: { color: colorActive, opacity: 0.85 },
        },
      };
    });

    var series = [
      {
        type: "bar",
        data: barData,
        // Demi-largeur par rapport à l'original pour un look plus fin (Finary style)
        barMaxWidth: 7,
        cursor: "pointer",
        // Ligne de base zéro — traverse tout le graphique en horizontal
        markLine: {
          silent: true,
          symbol: "none",
          data: [{ yAxis: 0 }],
          lineStyle: { color: T["edge"], width: 1, type: "solid" },
          label: { show: false },
        },
      },
    ];

    // Ligne de référence objectif — pointillée + label "OBJECTIF" à droite
    if (data.target !== null) {
      series.push({
        type: "line",
        data: data.values.map(function () { return data.target; }),
        symbol: "none",
        lineStyle: { color: colorActive, width: 1, type: "dashed", opacity: 0.45 },
        emphasis: { disabled: true },
        tooltip: { show: false },
        // Label "OBJECTIF" sur le dernier point à droite (endLabel)
        endLabel: {
          show: true,
          formatter: "OBJECTIF",
          color: colorActive,
          fontSize: 8,
          fontFamily: FONT,
          opacity: 0.7,
        },
      });
    }

    chart.setOption({
      backgroundColor: "transparent",
      grid: {
        left: 0,        // labels collés au bord gauche du conteneur (containLabel gère l'espace)
        right: "2%",
        top: "8%",
        bottom: "18%",
        containLabel: true,
      },
      xAxis: {
        type: "category",
        data: data.months,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: T["text-disabled"],
          fontSize: 9,
          fontFamily: FONT,
          interval: 0,
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        show: true,
        position: "left",
        axisLabel: {
          color: T["text-disabled"],
          fontSize: 9,
          fontFamily: FONT,
          // Format compact : 1500 → "1.5k", 800 → "800"
          formatter: function (v) {
            if (v >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
            return v;
          },
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      tooltip: {
        trigger: "item",
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        borderWidth: 1,
        padding: [6, 10],
        textStyle: { color: T["text-base"], fontSize: 11, fontFamily: FONT },
        formatter: function (params) {
          if (params.seriesType === "line") return "";
          var formatted = Math.round(params.value)
            .toLocaleString("fr-FR")
            .replace(/ /g, " ");
          return params.name + "<br/>" + formatted + " CHF";
        },
      },
      series: series,
    });

    // Clic sur une barre → naviguer vers ce mois
    chart.on("click", function (params) {
      if (params.seriesType === "bar" && data.urls[params.dataIndex]) {
        window.location.href = data.urls[params.dataIndex];
      }
    });

    return chart;
  };
})(window.BricCharts);
