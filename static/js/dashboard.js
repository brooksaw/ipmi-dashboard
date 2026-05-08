/**
 * dashboard.js - auto-refresh, compact sensor rendering, dynamic charts.
 */

const Dashboard = (() => {
  const REFRESH_INTERVAL = 30_000;
  const _charts = {};

  // ---- Toast ----
  function toast(msg, type = "ok", duration = 3000) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = `show ${type}`;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.className = ""; }, duration);
  }

  function _fmt(v) {
    if (v === null || v === undefined) return "-";
    return Number.isInteger(v) ? v.toString() : v.toFixed(1);
  }

  function _tileBorderClass(sensorType) {
    if (sensorType === "fan") return "fan-type";
    if (sensorType === "voltage") return "volt-type";
    return "";
  }

  function _renderCompactGrid(containerId, sensors) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = "";
    // Main grid: temps + fans only — voltages render separately in <details>
    const main = [
      ...(sensors.temp || []).map(s => ({...s, _type: "temp"})),
      ...(sensors.fan || []).map(s => ({...s, _type: "fan"})),
    ];
    if (!main.length) {
      el.innerHTML = '<span style="color:var(--muted);font-size:12px">No data</span>';
      return;
    }
    main.forEach(s => {
      const tile = document.createElement("div");
      tile.className = `sensor-tile ${s.status || "ok"} ${_tileBorderClass(s._type)}`;
      tile.innerHTML = `<div class="sensor-name" title="${s.name}">${s.name}</div><div class="sensor-value">${_fmt(s.value)}<span class="unit">${s.unit}</span></div>`;
      el.appendChild(tile);
    });
  }

  function _renderVoltages(serverId, voltages) {
    const el = document.getElementById(`${serverId}-voltages`);
    if (!el) return;
    if (!voltages || !voltages.length) {
      el.innerHTML = '<span style="color:var(--muted);font-size:11px">No voltage data</span>';
      return;
    }
    el.innerHTML = voltages.map(v => `
      <div class="voltage-mini-tile ${v.status || "ok"}">
        <span class="v-name" title="${v.name}">${v.name}</span>
        <span class="v-value">${_fmt(v.value)}<span class="v-unit">${v.unit}</span></span>
      </div>
    `).join("");
  }

  function _chartId(serverId, name) {
    return `chart-${serverId}-${name.replace(/[^a-z0-9]/gi, '-')}`;
  }

  function _getOrCreateChart(canvas, chartType) {
    const key = canvas.id;
    if (!_charts[key]) {
      _charts[key] = Charts.create(canvas, chartType);
    }
    return _charts[key];
  }

  async function _loadChart(serverId, sensorName, chartType) {
    try {
      const res = await fetch(`/api/history/${serverId}/${encodeURIComponent(sensorName)}?hours=6`);
      if (!res.ok) return;
      const data = await res.json();
      const points = data.data || [];
      const canvasId = _chartId(serverId, sensorName);
      const canvas = document.getElementById(canvasId);
      if (!canvas || !points.length) return;
      const chart = _getOrCreateChart(canvas, chartType);
      Charts.update(chart, points.map(p => p.timestamp), points.map(p => p.value));
    } catch (_) {}
  }

  function _buildCharts(serverId, sensors) {
    const container = document.getElementById(`${serverId}-charts`);
    if (!container) return;

    const chartSensors = [
      ...(sensors.temp || []).map(s => ({...s, _chartType: "temp"})),
      ...(sensors.fan || []).map(s => ({...s, _chartType: "fan"})),
    ];

    if (container.childElementCount !== chartSensors.length) {
      container.innerHTML = "";
      chartSensors.forEach(s => {
        const cid = _chartId(serverId, s.name);
        if (!document.getElementById(cid)) {
          const div = document.createElement("div");
          div.innerHTML = `<div class="chart-label">${s.name}</div><div class="chart-wrap"><canvas id="${cid}"></canvas></div>`;
          container.appendChild(div);
        }
      });
    }

    chartSensors.forEach(s => _loadChart(serverId, s.name, s._chartType));
  }

  function _updatePowerBadge(card, power) {
    const badge = card.querySelector(".power-state");
    if (!badge) return;
    badge.className = `power-state ${power}`;
    badge.textContent = power.toUpperCase();
  }

  function _initPowerButtons(serverId) {
    const card = document.querySelector(`[data-server="${serverId}"]`);
    if (!card) return;
    card.querySelectorAll(".btn-power").forEach(btn => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        if (!confirm(`Send "${action}" to ${serverId}?`)) return;
        btn.disabled = true;
        try {
          const res = await fetch(`/api/power/${serverId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Confirm": "yes" },
            body: JSON.stringify({ action }),
          });
          const json = await res.json();
          if (!res.ok) throw new Error(json.error || res.statusText);
          toast(`${serverId}: power ${action} sent`, "ok");
          setTimeout(() => _refreshServer(serverId), 4000);
        } catch (err) {
          toast(`Power error: ${err.message}`, "err");
        } finally { btn.disabled = false; }
      });
    });
  }

  async function _refreshAlerts() {
    try {
      const res = await fetch("/api/alerts");
      if (!res.ok) return;
      const alerts = await res.json();
      const banner = document.getElementById("alert-banner");
      if (!banner) return;
      if (!alerts || !alerts.length) { banner.style.display = "none"; return; }
      const hasCrit = alerts.some(a => a.level === "crit");
      banner.className = hasCrit ? "" : "warn";
      banner.style.display = "block";
      const title = banner.querySelector(".alert-title");
      const list = banner.querySelector("ul");
      if (title) title.textContent = hasCrit ? `CRITICAL - ${alerts.length} alert(s)` : `WARNING - ${alerts.length} alert(s)`;
      if (list) list.innerHTML = alerts.map(a => `<li>${a.server.toUpperCase()} / ${a.sensor_name}: ${_fmt(a.value)} (${a.level})</li>`).join("");
    } catch (_) {}
  }

  async function _refreshServer(serverId) {
    const card = document.querySelector(`[data-server="${serverId}"]`);
    if (!card) return;
    try {
      const res = await fetch(`/api/sensors/${serverId}`);
      if (!res.ok) return;
      const data = await res.json();
      const sensors = data.sensors || {};
      _updatePowerBadge(card, data.power || "unknown");
      _renderCompactGrid(`${serverId}-sensors`, sensors);
      _renderVoltages(serverId, sensors.voltage || []);
      _buildCharts(serverId, sensors);
    } catch (_) {}
  }

  async function _loadFanLog(serverId) {
    const tbody = document.querySelector(`#${serverId}-fan-log tbody`);
    if (!tbody) return;
    try {
      const res = await fetch(`/api/fans/${serverId}/log?count=10`);
      if (!res.ok) return;
      const data = await res.json();
      const logs = data.log || [];
      if (!logs.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">No adjustments yet</td></tr>';
        return;
      }
      tbody.innerHTML = logs.map(l => {
        const dt = new Date(l.timestamp);
        const ts = dt.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'}) +
                   ' ' + dt.toLocaleDateString([], {month:'short', day:'numeric'});
        const cls = l.target_duty > l.prev_duty ? 'duty-up' : 'duty-down';
        const arrow = l.target_duty > l.prev_duty ? '↑' : '↓';
        return `<tr><td>${ts}</td><td>${l.zone}</td><td>${l.source_label}=${_fmt(l.source_temp)}°C</td><td class="${cls}">${l.prev_duty}% ${arrow} ${l.target_duty}%</td></tr>`;
      }).join("");
    } catch (_) {}
  }

  function _serverIds() {
    return Array.from(document.querySelectorAll("[data-server]")).map(c => c.dataset.server);
  }

  // ---- Disks (optional Storage section) ----
  function _diskTempClass(temp) {
    if (temp >= 50) return "crit";
    if (temp >= 40) return "warn";
    return "ok";
  }

  function _capacityClass(pct) {
    if (pct >= 95) return "crit";
    if (pct >= 85) return "warn";
    return "ok";
  }

  function _diskTypeBadge(type) {
    if (!type) return "data";
    const t = type.toLowerCase();
    if (t === "parity")  return "parity";
    if (t === "cache")   return "cache";
    if (t === "pool")    return "pool";
    if (t === "flash")   return "flash";
    return "data";
  }

  async function _refreshDisks() {
    const grid = document.getElementById("disk-grid");
    if (!grid) return;
    try {
      const res = await fetch("/api/disks");
      if (!res.ok) return;
      const payload = await res.json();
      const disks = payload.disks || [];
      const asOf = document.getElementById("storage-as-of");
      if (asOf && payload.as_of) {
        const t = new Date(payload.as_of);
        asOf.textContent = "as of " + t.toLocaleTimeString();
      }
      if (!disks.length) {
        grid.innerHTML = '<span style="color:var(--muted);font-size:12px">No disks reported</span>';
        return;
      }
      grid.innerHTML = disks.map(d => {
        const tCls = _diskTempClass(d.temp);
        const cCls = _capacityClass(d.capacity_pct);
        const typeBadge = _diskTypeBadge(d.disk_type);
        const showCap = d.capacity_pct > 0;
        const healthDot = (d.health || "UNKNOWN").toUpperCase();
        const healthCls = healthDot === "PASS" ? "ok"
                         : healthDot === "WARN" ? "warn"
                         : healthDot === "FAIL" ? "crit"
                         : "ns";
        const spunIcon = d.spun_up === false ? '<span class="disk-spundown" title="Spun down">⏸</span>' : '';
        return `
          <div class="disk-tile ${tCls}">
            <div class="disk-row-top">
              <span class="disk-name" title="${d.disk_name}">${d.disk_name}</span>
              <span class="disk-type-badge ${typeBadge}">${d.disk_type || 'disk'}</span>
            </div>
            <div class="disk-temp">${_fmt(d.temp)}<span class="unit">°C</span> ${spunIcon}</div>
            ${showCap ? `
              <div class="disk-cap-bar">
                <div class="fill ${cCls}" style="width:${Math.min(100, d.capacity_pct)}%"></div>
              </div>
              <div class="disk-cap-label">${d.capacity_pct}% used</div>
            ` : ''}
            <span class="disk-health-dot ${healthCls}" title="SMART: ${healthDot}"></span>
          </div>`;
      }).join("");
    } catch (_) {}
  }

  function init() {
    _serverIds().forEach(sid => {
      FanControl.initServer(sid);
      _initPowerButtons(sid);
    });
    _doRefresh();
    setInterval(_doRefresh, REFRESH_INTERVAL);
  }

  async function _doRefresh() {
    await Promise.all(_serverIds().map(s => _refreshServer(s)));
    _refreshAlerts();
    _refreshDisks();
    const el = document.getElementById("last-updated");
    if (el) el.textContent = "Updated: " + new Date().toLocaleTimeString();
  }

  return { init, toast, loadFanLog: _loadFanLog };
})();

document.addEventListener("DOMContentLoaded", () => Dashboard.init());
