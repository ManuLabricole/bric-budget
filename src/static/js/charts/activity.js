// BricBudget — Activity chart (imports/upload.html).
//
// Bar chart empilé : transactions importées par banque, filtrable par période et métrique.
//
// Signature :
//   var ch = BricCharts.initActivity(el, data)
//   ch.render(period, metric)   — rafraîchit le graphique (appelé par les boutons HTML)
//
//   el   : élément DOM conteneur
//   data : {
//     banks : ["Yuh", "UBS", "CIC", ...]
//     logs  : [{ date: "YYYY-MM-DD", bank: "Yuh", created: N, total: N }, ...]
//   }
//
// Périodes :
//   1m → 1 barre par jour  (30 barres)
//   3m → 1 barre par semaine (13 barres)
//   1a → 1 barre par semaine (52 barres)
//
// Métriques : "created" (nouvelles tx) | "total" (created + skipped)
//
// ⛔ Règle : jamais de hex hardcodé ici — tout vient de BC.T. Police via BC.FONT.

window.BricCharts = window.BricCharts || {};

(function (BC) {
  BC.initActivity = function (el, data) {
    if (!el || !data) return null;

    var T    = BC.T;
    var FONT = BC.FONT;

    var chart = echarts.init(el, null, { renderer: "svg" });

    // Palette par banque — couleurs sémantiques des tokens design
    var COLORS = [
      T["gold"],
      T["income"],
      T["warning"],
      T["expense"],
    ];

    // ── Helpers date ────────────────────────────────────────────────────────
    // new Date("YYYY-MM-DD") parse en UTC → décalage d'un jour en heure locale.
    // parseLocal() force la construction en heure locale.
    function parseLocal(str) {
      var p = str.split("-");
      return new Date(+p[0], +p[1] - 1, +p[2]);
    }

    function pad(n) { return String(n).padStart(2, "0"); }

    // Lundi de la semaine ISO d'une date
    function monday(d) {
      var m = new Date(d);
      m.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      return m;
    }

    // Clé de bucket pour une date selon la granularité
    // day  → "YYYY-MM-DD"
    // week → "YYYY-MM-DD" (lundi de la semaine)
    function bucketKey(d, gran) {
      if (gran === "day") {
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
      }
      var m = monday(d);
      return m.getFullYear() + "-" + pad(m.getMonth() + 1) + "-" + pad(m.getDate());
    }

    // ── Construction des buckets selon la période ───────────────────────────
    // Retourne { keys: [...], labels: [...] } — même longueur, indexés ensemble.
    function buildBuckets(period) {
      var today = new Date();
      today.setHours(0, 0, 0, 0);
      var keys   = [];
      var labels = [];

      if (period === "1m") {
        // 30 jours — un label tous les 7 jours + dernier jour
        for (var i = 29; i >= 0; i--) {
          var d = new Date(today);
          d.setDate(today.getDate() - i);
          keys.push(bucketKey(d, "day"));
          labels.push((i % 7 === 0 || i === 0)
            ? d.getDate() + " " + d.toLocaleString("fr", { month: "short" })
            : "");
        }
      } else {
        // 3M = 13 semaines / 1A = 52 semaines
        // Label affiché uniquement en début de mois (quand le mois change)
        var weeks = period === "3m" ? 13 : 52;
        var start = monday(today);
        start.setDate(start.getDate() - (weeks - 1) * 7);

        for (var i = 0; i < weeks; i++) {
          var d = new Date(start);
          d.setDate(start.getDate() + i * 7);
          keys.push(bucketKey(d, "week"));

          var isNewMonth = i === 0;
          if (!isNewMonth) {
            var prev = new Date(start);
            prev.setDate(start.getDate() + (i - 1) * 7);
            isNewMonth = monday(prev).getMonth() !== monday(d).getMonth();
          }
          labels.push(isNewMonth
            ? d.getDate() + " " + d.toLocaleString("fr", { month: "short" })
            : "");
        }
      }
      return { keys: keys, labels: labels };
    }

    // ── Rendu principal ─────────────────────────────────────────────────────
    function render(period, metric) {
      var gran = period === "1m" ? "day" : "week";
      var bb   = buildBuckets(period);

      // Initialiser les compteurs à zéro pour chaque banque × bucket
      var counts = {};
      data.banks.forEach(function (b) {
        counts[b] = {};
        bb.keys.forEach(function (k) { counts[b][k] = 0; });
      });

      // Remplir les compteurs depuis les logs bruts
      data.logs.forEach(function (l) {
        var d = parseLocal(l.date);
        var k = bucketKey(d, gran);
        if (counts[l.bank] && counts[l.bank].hasOwnProperty(k)) {
          counts[l.bank][k] += l[metric];
        }
      });

      // ── Y max intelligent : exclure les imports initiaux (outliers) ────────
      // Problème : le premier import bulk (milliers de tx) écrase l'axe et rend
      // les imports quotidiens (quelques tx) invisibles.
      //
      // Solution : calculer le max de l'axe sur le 90e percentile des valeurs
      // non-nulles × 1.5. Les barres qui dépassent sont visuellement tronquées
      // mais le tooltip affiche toujours la vraie valeur.
      //
      // Si toutes les valeurs sont dans le même ordre de grandeur (pas d'outlier),
      // le 90e percentile ≈ le max réel → comportement identique à l'auto-scale.
      var bucketTotals = bb.keys.map(function (k) {
        return data.banks.reduce(function (s, b) { return s + counts[b][k]; }, 0);
      });
      var nonZero = bucketTotals.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
      var yMax;
      if (nonZero.length > 1) {
        var p90 = nonZero[Math.floor(nonZero.length * 0.9)];
        yMax = Math.max(p90 * 1.5, 10);
      }
      // nonZero.length <= 1 → undefined → ECharts auto-scale (pas de données = pas de problème)

      var series = data.banks.map(function (bank, i) {
        var isTop = i === data.banks.length - 1; // série empilée du dessus
        return {
          name: bank,
          type: "bar",
          stack: "total",
          data: bb.keys.map(function (k) { return counts[bank][k]; }),
          itemStyle: {
            color: COLORS[i % COLORS.length],
            // Arrondir uniquement le dessus de la barre empilée totale
            borderRadius: isTop ? [3, 3, 0, 0] : [0, 0, 0, 0],
            opacity: 0.85,
          },
          emphasis: { itemStyle: { opacity: 1 } },
          barMaxWidth: period === "1m" ? 18 : 10,
          barMinHeight: 2,
        };
      });

      chart.setOption({
        backgroundColor: "transparent",
        grid: {
          left: 0,
          right: "2%",
          top: "8%",
          bottom: data.banks.length > 1 ? "18%" : "12%",
          containLabel: true,
        },
        legend: data.banks.length > 1 ? {
          bottom: 0,
          textStyle: { color: T["text-muted"], fontSize: 10, fontFamily: FONT },
          itemWidth: 10,
          itemHeight: 10,
        } : { show: false },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: T["surface-hover"],
          borderColor: T["edge"],
          borderWidth: 1,
          padding: [6, 10],
          textStyle: { color: T["text-base"], fontSize: 11, fontFamily: FONT },
          formatter: function (params) {
            var total = params.reduce(function (s, p) { return s + p.value; }, 0);
            if (total === 0) return null;
            var lines = params
              .filter(function (p) { return p.value > 0; })
              .map(function (p) {
                return p.marker + " " + p.seriesName + " <b>" + p.value + "</b>";
              });
            var suffix = (yMax !== undefined && total > yMax)
              ? "<br><span style='opacity:0.55;font-size:10px'>↑ hors échelle</span>"
              : "";
            return params[0].axisValueLabel + "<br>" + lines.join("<br>") +
              (lines.length > 1 ? "<br><b>Total : " + total + "</b>" : "") + suffix;
          },
        },
        xAxis: {
          type: "category",
          data: bb.labels,
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
          minInterval: 1,
          max: yMax,
          axisLabel: {
            color: T["text-disabled"],
            fontSize: 9,
            fontFamily: FONT,
            formatter: function (v) {
              if (v >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
              return v;
            },
          },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: {
            lineStyle: { color: T["edge"], type: "dashed" },
          },
        },
        series: series,
      }, true);
    }

    // Exposer render pour que les boutons HTML puissent appeler ch.render(p, m)
    chart.renderActivity = render;
    render("1a", "created");
    return chart;
  };
})(window.BricCharts);
