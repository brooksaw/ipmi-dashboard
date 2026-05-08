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

  function create(canvas, type = "default") {
    const { line, fill } = _color(type);
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
