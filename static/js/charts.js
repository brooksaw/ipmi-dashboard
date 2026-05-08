/**
 * charts.js — thin Chart.js wrapper for history sparklines.
 *
 * Usage:
 *   const chart = Charts.create(canvasEl, "temp");
 *   Charts.update(chart, timestamps, values);
 */

const Charts = (() => {
  const COLORS = {
    temp:    { line: "#f97316", fill: "rgba(249,115,22,.15)" },
    fan:     { line: "#58a6ff", fill: "rgba(88,166,255,.15)" },
    voltage: { line: "#bc8cff", fill: "rgba(188,140,255,.15)" },
    power:   { line: "#3fb950", fill: "rgba(63,185,80,.15)"  },
    default: { line: "#768390", fill: "rgba(118,131,144,.1)" },
  };

  function _color(type) {
    return COLORS[type] || COLORS.default;
  }

  // Per-type Y-axis floor / suggested-min so 100 RPM of jitter on a 1600 RPM
  // fan doesn't get auto-zoomed into looking like wild oscillation.
  const Y_HINT = {
    temp:    { suggestedMin: 20, suggestedMax: 50 },   // typical idle temps
    fan:     { suggestedMin: 0,  suggestedMax: 2000 }, // anchored to 0
    voltage: { /* let it auto-scale; voltages are tightly regulated */ },
    power:   { suggestedMin: 0 },
  };

  function create(canvas, type = "default") {
    const { line, fill } = _color(type);
    const yHint = Y_HINT[type] || {};
    return new Chart(canvas, {
      type: "line",
      data: {
        labels: [],
        datasets: [{
          data: [],
          borderColor: line,
          backgroundColor: fill,
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false }, tooltip: {
          mode: "index",
          intersect: false,
          callbacks: {
            title: items => new Date(items[0].label).toLocaleTimeString(),
          },
        }},
        scales: {
          x: {
            display: false,
            type: "category",
          },
          y: {
            display: true,
            grid: { color: "#2d333b" },
            ticks: {
              color: "#768390",
              font: { size: 10 },
              maxTicksLimit: 4,
            },
            border: { display: false },
            ...yHint,
          },
        },
      },
    });
  }

  function update(chart, timestamps, values) {
    chart.data.labels = timestamps;
    chart.data.datasets[0].data = values;
    chart.update("none");
  }

  return { create, update };
})();
