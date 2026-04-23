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

    // ── Détection pool + __disponible__ ───────────────────────────────────────
    const hasPool = sankeyData.nodes.some(function (n) { return n.name === "__pool__"; });

    // ── Positionnement universel des labels — source RIGHT, target LEFT ────────
    //
    // Principe identique pour les deux variantes de Sankey :
    //   - Sankey global (avec pool)  : income → pool → expense
    //   - Sankey catégorie (sans pool) : category → subcategories
    //
    // Dans les deux cas, les nœuds "source" (colonne gauche) ont leur label à
    // DROITE de leur barre → le label tombe dans l'espace des flux, lisible.
    // Les nœuds "target" (colonne droite) ont leur label à GAUCHE de leur barre
    // → même principe, label dans le flux, pas rogné sur le bord du chart.
    //
    // On détecte source/target via les liens (pas via hasPool) pour que la même
    // logique fonctionne quelle que soit la structure du graphe.
    //
    // Nœuds invisibles (__pool__, __disponible__) → label masqué.
    const HIDDEN_NODES = new Set(["__pool__", "__disponible__"]);
    const targetNodes  = new Set();
    sankeyData.links.forEach(function (link) {
      if (!HIDDEN_NODES.has(link.target)) targetNodes.add(link.target);
    });

    sankeyData.nodes = sankeyData.nodes.map(function (n) {
      if (HIDDEN_NODES.has(n.name)) return n;
      const pos = targetNodes.has(n.name) ? "left" : "right";
      return Object.assign({}, n, { label: { position: pos } });
    });

    // ── Dégradé par lien — utilise la couleur du nœud TARGET ─────────────────
    // Le target est toujours le nœud coloré (sous-catégorie ou expense).
    // Le source peut être le pool invisible → on prend target dans ce cas aussi.
    // Gradient : sombre (factor 0.05) à gauche → lumineux (factor 0.7) à droite.
    // Exception : liens __disponible__ gardent opacity:0 du backend.
    sankeyData.links = sankeyData.links.map(function (link) {
      if (link.target === "__disponible__") return link;
      // On prend toujours la couleur du target (porteur de la couleur distincte).
      // Si le target est le pool (income→pool), on prend le source à la place.
      const linkColor = HIDDEN_NODES.has(link.target)
        ? nodeColorMap[link.source]
        : nodeColorMap[link.target];
      return Object.assign({}, link, {
        lineStyle: {
          opacity: 0.75,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: applyFactor(linkColor, 0.05) },
            { offset: 1, color: applyFactor(linkColor, 0.7)  },
          ]),
        },
      });
    });

    // Marges à 0 dans les deux cas — les labels sont à l'intérieur des flux,
    // pas en dehors du chart, donc pas besoin de marge pour les protéger.
    const seriesLeft  = 0;
    const seriesRight = 0;

    sankey.setOption({
      backgroundColor: "transparent",
      animation: true,
      animationDuration: 400,
      animationEasing: "cubicOut",
      tooltip: {
        trigger: "item",
        backgroundColor: T["surface-hover"],
        borderColor: T["edge"],
        textStyle: { color: T["text-base"], fontSize: 12, fontFamily: FONT },
        formatter: function (params) {
          // Strip U+200B (zero-width space) utilisé pour dédupliquer le nœud
          // source quand catégorie et sous-catégorie portent le même nom.
          if (params.dataType === "node") {
            if (params.name === "__pool__") return "";
            const name = params.name.replace(/​/g, "");
            const val = Math.round(Math.abs(params.value)).toLocaleString("fr-CH", { maximumFractionDigits: 0 });
            return `<b>${name}</b><br />${val} CHF`;
          }
          const val = params.value.toLocaleString("fr-CH", { maximumFractionDigits: 0 });
          const src = params.data.source.replace(/​/g, "");
          const tgt = params.data.target.replace(/​/g, "");
          return `${src} → ${tgt}<br /><b>${val} CHF</b>`;
        },
      },
      series: [{
        type: "sankey",
        animation: true,
        animationDuration: 400,
        animationEasing: "cubicOut",
        orient: "horizontal",
        nodeAlign: "justify",
        // layoutIterations: 0 → désactive l'algorithme de réduction de croisements.
        // Avec la valeur par défaut (32), ECharts réordonne les nœuds verticalement
        // pour minimiser les croisements de flux — mais avec 2 income vs 13 expense,
        // ça place les income en bas et les expenses en haut, ce qui croise tout.
        // À 0 : les nœuds restent dans l'ordre exact du tableau data.
        layoutIterations: 0,
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
            const name = params.name.replace(/​/g, "");
            const val = Math.round(Math.abs(params.value))
              .toLocaleString("fr-FR")
              .replace(/ /g, " ");
            return `${name}  ${val} CHF`;
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
