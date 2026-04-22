// BricBudget — Sankey ECharts.
//
// Gère 3 variantes depuis la même fonction :
//   1. Global budget  : income → __pool__ → expense (nœud pool visible)
//   2. Sous-catégories : même structure, données différentes
//   3. Détail catégorie : liens directs, pas de nœud pool
// La présence de "__pool__" dans les nœuds est détectée automatiquement.
//
// Signature :
//   BricCharts.initSankey(el, data, options)
//     el      : élément DOM du conteneur
//     data    : objet { nodes: [...], links: [...] } (parsé depuis json_script Django)
//     options : { onNodeClick: function(nodeData) {} }  — optionnel

window.BricCharts = window.BricCharts || {};

(function (BC) {
  BC.initSankey = function (el, data, options) {
    if (!el || !data) return null;
    options = options || {};

    const T           = BC.T;
    const FONT        = BC.FONT;
    const applyFactor = BC.applyFactor;

    // Copie défensive pour ne pas muter les données originales
    // (réutilisation possible si on reinit le chart avec d'autres filtres)
    const sankeyData = {
      nodes: data.nodes.slice(),
      links: data.links.slice(),
    };

    const sankey = echarts.init(el, null, { renderer: "svg" });

    // ── Couleur de chaque nœud — construit au départ pour les dégradés ────────
    const nodeColorMap = {};
    sankeyData.nodes.forEach(function (n) {
      if (n.itemStyle && n.itemStyle.color) nodeColorMap[n.name] = n.itemStyle.color;
    });

    // ── Détection du mode pool ─────────────────────────────────────────────────
    // Si __pool__ est présent, on applique le positionnement Finary (labels inside).
    // Sinon (détail catégorie), les labels restent en position par défaut.
    const hasPool = sankeyData.nodes.some(function (n) { return n.name === "__pool__"; });

    if (hasPool) {
      // Identifier les nœuds income (→ pool) et expense (pool →)
      const incomeNodes  = new Set();
      const expenseNodes = new Set();
      sankeyData.links.forEach(function (link) {
        if (link.target === "__pool__") incomeNodes.add(link.source);
        if (link.source === "__pool__") expenseNodes.add(link.target);
      });

      // Assigner la position du label par type de nœud :
      //   income  → label à droite de la barre (dans le flux income)
      //   expense → label à gauche de la barre (dans le flux expense, côté pool)
      //   pool    → label masqué
      sankeyData.nodes = sankeyData.nodes.map(function (n) {
        if (n.name === "__pool__") return n;
        const pos = expenseNodes.has(n.name) ? "left" : "right";
        return Object.assign({}, n, { label: { position: pos } });
      });
    }

    // ── Dégradé par lien — toujours visible, sombre → lumineux ───────────────
    // Deux cas :
    //   income→pool : sombre à gauche (0.05), lumineux à droite (0.7)
    //   pool→expense : identique — le pool est au centre donc même sens G→D
    // Sans pool : gradient simple basé sur le nœud source.
    sankeyData.links = sankeyData.links.map(function (link) {
      const isToPool  = link.target === "__pool__";
      const catColor  = isToPool
        ? nodeColorMap[link.source]
        : nodeColorMap[link.target] || nodeColorMap[link.source];
      return Object.assign({}, link, {
        lineStyle: {
          opacity: 0.75,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: applyFactor(catColor, 0.05) },
            { offset: 1, color: applyFactor(catColor, 0.7)  },
          ]),
        },
      });
    });

    // Marges de la série selon le mode :
    // - Avec pool : left=0, right=0 → barres sur les bords, labels à l'intérieur des flux.
    // - Sans pool : marges à 10% pour que les labels ne soient pas rognés sur les côtés.
    const seriesLeft   = hasPool ? 0 : "10%";
    const seriesRight  = hasPool ? 0 : "10%";

    sankey.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 12, fontFamily: FONT },
        formatter: function (params) {
          if (params.dataType === "node") {
            if (params.name === "__pool__") return "";
            const val = Math.round(Math.abs(params.value)).toLocaleString("fr-CH", { maximumFractionDigits: 0 });
            return `<b>${params.name}</b><br />${val} CHF`;
          }
          const val = params.value.toLocaleString("fr-CH", { maximumFractionDigits: 0 });
          return `${params.data.source} → ${params.data.target}<br /><b>${val} CHF</b>`;
        },
      },
      series: [{
        type: "sankey",
        layout: "none",
        orient: "horizontal",
        nodeAlign: "justify",
        // left/right DOIVENT être dans la série (ignorés au niveau racine pour Sankey).
        left: seriesLeft,
        right: seriesRight,
        top: "2%",
        bottom: "2%",
        nodeWidth: 7,
        nodeGap: 10,
        emphasis: {
          focus: "adjacency",
          lineStyle: { opacity: 1 },
        },
        data: sankeyData.nodes,
        links: sankeyData.links,
        lineStyle: { curveness: 0.4 },
        label: {
          fontFamily: FONT,
          fontSize: 10,
          color: T["text-base"],
          formatter: function (params) {
            if (params.name === "__pool__") return "";
            const val = Math.round(Math.abs(params.value))
              .toLocaleString("fr-FR")
              .replace(/ /g, " ");
            return `${params.name}  ${val} CHF`;
          },
        },
        itemStyle: {
          borderRadius: 2,
          borderColor: T["surface-2"],
          borderWidth: 2,
        },
      }],
    });

    // ── Click navigation — optionnel ──────────────────────────────────────────
    // Si options.onNodeClick est fourni, on l'appelle au clic sur un nœud.
    // Le callback reçoit params.data (l'objet nœud complet, avec slug si présent).
    if (options.onNodeClick) {
      sankey.on("click", "series.sankey", function (params) {
        if (params.dataType === "node" && params.name !== "__pool__") {
          options.onNodeClick(params.data);
        }
      });
    }

    window.addEventListener("resize", function () { sankey.resize(); });
    return sankey;
  };
})(window.BricCharts);
