// BricBudget — Activity chart (imports/upload.html).
//
// Bar chart empilé : transactions par date réelle, filtrable par période et métrique.
// Les barres représentent l'activité financière réelle (Transaction.date),
// pas la date d'import. Des marqueurs verticaux indiquent les dates d'import.
//
// Signature :
//   var ch = BricCharts.initActivity(el, data)
//   ch.render(period, metric)   — rafraîchit le graphique (appelé par les boutons HTML)
//
//   el   : élément DOM conteneur
//   data : {
//     banks          : ["Yuh", "UBS", "CIC", ...]
//     logs           : [{ date: "YYYY-MM-DD", bank: "Yuh", created: N, total: N }, ...]
//     import_markers : [{ date: "YYYY-MM-DD", filename: "yuh.csv", total: N, bank: "Yuh" }, ...]
//   }
//
// Périodes :
//   1m → 1 barre par jour  (30 barres)
//   3m → 1 barre par semaine (13 barres)
//   1y → 1 barre par semaine (52 barres)
//
// Métrique : "created" (nouvelles tx)
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
    function buildBuckets(period, offset) {
      var today = new Date();
      today.setHours(0, 0, 0, 0);
      // Décaler la date de référence selon l'offset et la taille de la fenêtre
      var windowDays = period === "1m" ? 30 : period === "3m" ? 91 : 365; // 1y
      today.setDate(today.getDate() - (offset || 0) * windowDays);
      var keys   = [];
      var labels = [];

      if (period === "1m") {
        // 30 jours — label tous les 7 jours (≈ 5 labels réguliers)
        for (var i = 29; i >= 0; i--) {
          var d = new Date(today);
          d.setDate(today.getDate() - i);
          keys.push(bucketKey(d, "day"));
          labels.push(i % 7 === 0
            ? d.getDate() + " " + d.toLocaleString("fr", { month: "short" })
            : "");
        }
      } else if (period === "3m") {
        // 13 semaines — label toutes les 2 semaines (≈ 7 labels réguliers)
        var weeks = 13;
        var start = monday(today);
        start.setDate(start.getDate() - (weeks - 1) * 7);
        for (var i = 0; i < weeks; i++) {
          var d = new Date(start);
          d.setDate(start.getDate() + i * 7);
          keys.push(bucketKey(d, "week"));
          labels.push(i % 2 === 0
            ? d.getDate() + " " + d.toLocaleString("fr", { month: "short" })
            : "");
        }
      } else {
        // 1y = 52 semaines — 1 label par mois (≈ 12 labels réguliers)
        // Premier lundi d'un nouveau mois = le label affiché.
        var weeks = 52;
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
            ? d.toLocaleString("fr", { month: "short" }).replace(/^./, function (c) { return c.toUpperCase(); })
            : "");
        }
      }
      return { keys: keys, labels: labels };
    }

    // ── Rendu principal ─────────────────────────────────────────────────────
    function render(period, metric, offset) {
      var gran = period === "1m" ? "day" : "week"; // 1y and 3m use weekly buckets
      var bb   = buildBuckets(period, offset);

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

      // ── Lookup marqueurs d'import par bucket ────────────────────────────────
      // Pour chaque bucket de l'axe X, on mémorise les imports qui tombent dedans.
      // Utilisé par le tooltip (info textuelle) et la markLine (ligne verticale).
      var markersByKey = {};
      if (data.import_markers) {
        data.import_markers.forEach(function (m) {
          var k = bucketKey(parseLocal(m.date), gran);
          if (!markersByKey[k]) markersByKey[k] = [];
          markersByKey[k].push(m);
        });
      }

      // ── Y max — 90e percentile pour absorber les pics d'activité ────────────
      // Si un mois a une activité anormalement haute (soldes rattrapés, corrections),
      // le p90 × 1.5 empêche l'axe de s'écraser. Le tooltip affiche toujours la vraie valeur.
      var bucketTotals = bb.keys.map(function (k) {
        return data.banks.reduce(function (s, b) { return s + counts[b][k]; }, 0);
      });
      var nonZero = bucketTotals.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
      // niceMax : arrondit vers le haut à la valeur "ronde" suivante pour que
      // l'axe Y affiche des graduations propres (ex: 0/5/10/15 et non 0/4/8/12).
      function niceMax(val) {
        if (val <= 0) return 10;
        var mag = Math.pow(10, Math.floor(Math.log10(val)));
        var n   = val / mag;
        var nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
        return nice * mag;
      }
      var yMax;
      if (nonZero.length > 1) {
        var p90 = nonZero[Math.floor(nonZero.length * 0.9)];
        yMax = niceMax(Math.max(p90 * 1.5, 5));
      }
      // nonZero.length <= 1 → undefined → ECharts auto-scale

      var series = data.banks.map(function (bank, i) {
        var isTop = i === data.banks.length - 1; // série empilée du dessus
        var s = {
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
          barMaxWidth: period === "1m" ? 18 : 10, // 1y and 3m are narrower
          barMinHeight: 2,
        };
        // Marqueurs d'import sur la dernière série (une seule markLine par graphique).
        // Ligne verticale pointillée à chaque date d'import dans la fenêtre.
        if (isTop) {
          var markerData = [];
          bb.keys.forEach(function (k) {
            if (markersByKey[k]) {
              markerData.push({ xAxis: k });
            }
          });
          if (markerData.length) {
            s.markLine = {
              silent: true,
              symbol: ["none", "none"],
              data: markerData,
              lineStyle: {
                type: "dashed",
                color: T["text-disabled"],
                width: 1,
                opacity: 0.45,
              },
              label: { show: false },
            };
          }
        }
        return s;
      });

      chart.setOption({
        animation: true,
        animationDuration: 300,
        animationDurationUpdate: 150,
        animationEasing: "cubicOut",
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
            // Marqueurs d'import sur ce bucket — affichés même si total = 0
            var key = bb.keys[params[0].dataIndex];
            var markers = markersByKey[key] || [];
            if (total === 0 && markers.length === 0) return null;
            var lines = params
              .filter(function (p) { return p.value > 0; })
              .map(function (p) {
                return p.marker + " " + p.seriesName + " <b>" + p.value + "</b>";
              });
            var suffix = (yMax !== undefined && total > yMax)
              ? "<br><span style='opacity:0.55;font-size:10px'>↑ hors échelle</span>"
              : "";
            if (markers.length) {
              var mLines = markers.map(function (m) {
                var d = parseLocal(m.date);
                var dateStr = d.getDate() + " " + d.toLocaleString("fr", { month: "short" }) + " " + d.getFullYear();
                return "<span style='opacity:0.6;font-size:10px'>↓ import " + m.bank + " — " + m.filename + " — " + m.total + " tx (" + dateStr + ")</span>";
              });
              suffix += (lines.length ? "<br>" : "") + mLines.join("<br>");
            }
            if (total === 0) return suffix.replace(/^<br>/, "");
            return params[0].axisValueLabel + "<br>" + lines.join("<br>") +
              (lines.length > 1 ? "<br><b>Total : " + total + "</b>" : "") + suffix;
          },
        },
        xAxis: {
          type: "category",
          // bb.keys (YYYY-MM-DD) comme données — permet markLine par date string.
          // Le formatter restitue les labels visuels calculés dans bb.labels.
          data: bb.keys,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: T["text-disabled"],
            fontSize: 9,
            fontFamily: FONT,
            // interval:0 = montrer tous les ticks, le formatter filtre les vides.
            // Cela garantit un placement régulier calculé dans buildBuckets.
            interval: 0,
            formatter: function (value, index) {
              return bb.labels[index] || "";
            },
          },
          splitLine: { show: false },
        },
        yAxis: {
          type: "value",
          show: true,
          position: "left",
          minInterval: 1,
          max: yMax,
          // splitNumber : suggestion ECharts pour le nb de graduations.
          // ECharts ajuste pour tomber sur des valeurs rondes.
          splitNumber: 4,
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

    // Exposer render pour que les boutons HTML puissent appeler ch.renderActivity(p, m, offset)
    chart.renderActivity = render;
    render("1y", "created", 0);
    return chart;
  };
})(window.BricCharts);
