/* CPI dashboard chart bootstrapping.
   Reads window.__CHARTS__ = { canvasId: {type, data, opts} } and renders each
   canvas present on the page. Formatting hints in `opts` keep the inlined JSON
   free of JS functions; this file turns them into Chart.js options. */
(function () {
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Manrope', sans-serif";
  Chart.defaults.color = "#404243";
  Chart.defaults.borderColor = "#E8F0F7";
  var LIGHT = "#E8F0F7";

  function tick(kind) {
    if (kind === "pct") return function (v) { return v + "%"; };
    if (kind === "money") return function (v) { return "$" + Number(v).toLocaleString(); };
    return function (v) { return v; };
  }

  var specs = window.__CHARTS__ || {};
  Object.keys(specs).forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    var spec = specs[id];
    var o = spec.opts || {};
    var scales = {};

    if (o.dual) {
      scales.y1 = { type: "linear", position: "left", beginAtZero: true,
        ticks: { callback: tick(o.y_fmt), font: { size: 11 } }, grid: { color: LIGHT } };
      scales.y2 = { type: "linear", position: "right", beginAtZero: true,
        ticks: { callback: tick(o.y2_fmt), font: { size: 11 } }, grid: { display: false } };
      scales.x = { ticks: { font: { size: 11 } }, grid: { display: false } };
    } else {
      var valAxis = { beginAtZero: true, stacked: !!o.stacked,
        ticks: { callback: tick(o.y_fmt), font: { size: 11 } }, grid: { color: LIGHT } };
      var catAxis = { stacked: !!o.stacked, ticks: { font: { size: 11 } }, grid: { display: false } };
      if (o.indexAxis === "y") { scales.x = valAxis; scales.y = catAxis; }
      else { scales.y = valAxis; scales.x = catAxis; }
    }

    var plugins = {
      legend: { display: o.legend !== false, position: "bottom",
        labels: { boxWidth: 10, padding: 12, font: { size: 11 } } }
    };
    if (o.tt_pct) {
      plugins.tooltip = { callbacks: { label: function (c) {
        return c.raw != null ? (c.dataset.label ? c.dataset.label + ": " : "") + c.raw + "%" : "TBD";
      } } };
    }

    new Chart(el, {
      type: spec.type,
      data: spec.data,
      options: {
        maintainAspectRatio: false,
        indexAxis: o.indexAxis || "x",
        interaction: { mode: "index", intersect: false },
        plugins: plugins,
        scales: scales
      }
    });
  });
})();
