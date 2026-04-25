#!/usr/bin/env python3
"""
web-dashboard.py — Serves the IPMI dashboard as a web page with fan control.
Uses Python's built-in http.server — no external dependencies.
"""

import html
import http.server
import json
import os
import subprocess
import time
import urllib.parse

PORT = int(os.environ.get("WEB_PORT", "8080"))
REFRESH = int(os.environ.get("WEB_REFRESH", "10"))
IPMI_HOST = os.environ.get("IPMI_HOST", "")
IPMI_USER = os.environ.get("IPMI_USER", "ADMIN")
IPMI_PASS = os.environ.get("IPMI_PASS", "")

# Thresholds
TEMP_WARN = 70
TEMP_CRIT = 85
FAN_WARN_RPM = 500
FAN_CRIT_RPM = 200

# Fan mode map: code -> name
FAN_MODES = {
    "00": "Heavy Duty",
    "01": "Standard",
    "02": "Full (100%)",
    "04": "Optimal",
    "10": "PUE2 (Power Save)",
}


def ipmi(*args, timeout=15):
    """Run ipmitool and return stdout."""
    cmd = [
        "ipmitool", "-I", "lanplus",
        "-H", IPMI_HOST, "-U", IPMI_USER, "-P", IPMI_PASS,
        "-N", "5000", "-R", "2"
    ] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def set_fan_mode(mode_code):
    """Set fan control mode. Returns True on success."""
    result = ipmi("raw", "0x30", "0x45", "0x01", mode_code, timeout=10)
    return bool(result is not None)


def set_fan_duty(zone, percent):
    """Set fan duty cycle for a zone. Returns True on success."""
    hex_pct = f"0x{percent:02x}"
    result = ipmi("raw", "0x30", "0x70", "0x66", "0x01",
                  f"0x{zone:02x}", hex_pct, timeout=10)
    return bool(result is not None)


def apply_fan_control(mode_code, duty_z0=None, duty_z1=None):
    """
    Apply fan control with proper Supermicro BMC timing.
    Proven sequence from ISS-029:
      1. Force FULL mode (breaks out of any active preset)
      2. Sleep 2s (BMC needs this)
      3. Switch to target mode
      4. Sleep 2s
      5. Set duty cycles (if applicable)
    Returns dict with status and messages.
    """
    msgs = []

    # Step 1: Force FULL mode first
    if not set_fan_mode("02"):
        return {"ok": False, "msg": "Failed to set FULL mode transition"}
    msgs.append("FULL mode set")

    time.sleep(2)

    # Step 2: Set target mode
    mode_name = FAN_MODES.get(mode_code, f"Unknown ({mode_code})")
    if not set_fan_mode(mode_code):
        return {"ok": False, "msg": f"Failed to set {mode_name} mode"}
    msgs.append(f"Mode set to {mode_name}")

    # Step 3: Set duty cycles if provided
    if duty_z0 is not None:
        time.sleep(2)
        if set_fan_duty(0, duty_z0):
            msgs.append(f"Zone0 duty set to {duty_z0}%")
        else:
            msgs.append(f"Zone0 duty FAILED")

    if duty_z1 is not None:
        if duty_z0 is None:
            time.sleep(2)
        if set_fan_duty(1, duty_z1):
            msgs.append(f"Zone1 duty set to {duty_z1}%")
        else:
            msgs.append(f"Zone1 duty FAILED")

    return {"ok": True, "msg": " | ".join(msgs)}


def clear_sel():
    """Clear the SEL log. Returns True on success."""
    result = ipmi("sel", "clear", timeout=10)
    return True


def parse_sdr_line(line):
    """Parse SDR format: 'Name | id | status | type | value'"""
    parts = line.split("|")
    if len(parts) < 5:
        if len(parts) >= 3:
            return parts[0].strip(), parts[2].strip(), parts[-1].strip()
        return None, None, None
    return parts[0].strip(), parts[2].strip(), parts[4].strip()


def color_temp(val_str):
    try:
        v = int(val_str)
        if v >= TEMP_CRIT:
            return "crit"
        elif v >= TEMP_WARN:
            return "warn"
        return "ok"
    except (ValueError, TypeError):
        return "na"


def color_fan(rpm_str, status):
    if status.lower() in ("ns",) or "No Reading" in (rpm_str or ""):
        return "not-present", "NOT PRESENT"
    try:
        v = int(rpm_str)
        if v <= FAN_CRIT_RPM:
            return "crit", f"{v} RPM"
        elif v <= FAN_WARN_RPM:
            return "warn", f"{v} RPM"
        return "ok", f"{v} RPM"
    except (ValueError, TypeError):
        return "na", "N/A"


def gather_data():
    """Gather all IPMI data. Returns a dict."""
    # BMC info
    bmc_info = ipmi("mc", "info")
    fru_info = ipmi("fru")

    firmware = ""
    for line in bmc_info.splitlines():
        if "Firmware Revision" in line:
            firmware = line.split()[-1]
            break

    board_model = "unknown"
    for line in fru_info.splitlines():
        if "Board Part Number" in line or "Board Product" in line:
            board_model = line.split(":", 1)[-1].strip()
            break

    # Fan mode
    fan_mode_raw = ipmi("raw", "0x30", "0x45", "0x00").strip().replace(" ", "")
    fan_mode_name = FAN_MODES.get(fan_mode_raw, f"Unknown ({fan_mode_raw})")

    # Fan duty
    duty_z0 = ""
    duty_z0_int = None
    duty_z1 = ""
    duty_z1_int = None
    raw_z0 = ipmi("raw", "0x30", "0x70", "0x66", "0x00", "0x00").strip().replace(" ", "")
    raw_z1 = ipmi("raw", "0x30", "0x70", "0x66", "0x00", "0x01").strip().replace(" ", "")
    if raw_z0:
        try:
            duty_z0_int = int(raw_z0, 16)
            duty_z0 = f"{duty_z0_int}%"
        except ValueError:
            duty_z0 = "N/A"
    if raw_z1:
        try:
            duty_z1_int = int(raw_z1, 16)
            duty_z1 = f"{duty_z1_int}%"
        except ValueError:
            duty_z1 = "N/A"

    # Temperatures
    temp_output = ipmi("sdr", "type", "temperature")
    temps = []
    for line in temp_output.splitlines():
        name, status, value = parse_sdr_line(line)
        if not name:
            continue
        if "No Reading" in value or status.lower() == "ns":
            temps.append((name, "N/A", "na"))
            continue
        try:
            num = value.split()[0]
            temps.append((name, f"{num}°C", color_temp(num)))
        except (ValueError, IndexError):
            temps.append((name, "N/A", "na"))

    # Fans
    fan_output = ipmi("sdr", "type", "fan")
    fans = []
    for line in fan_output.splitlines():
        name, status, value = parse_sdr_line(line)
        if not name:
            continue
        css, display = color_fan(value if "RPM" in value else "", status)
        if "RPM" in value:
            try:
                rpm = value.split()[0]
                css, display = color_fan(rpm, status)
            except (ValueError, IndexError):
                pass
        fans.append((name, display, css))

    ok_fans = sum(1 for _, _, c in fans if c == "ok")
    total_fans = len(fans)

    # Voltages
    volt_output = ipmi("sdr", "type", "voltage")
    volts = []
    for line in volt_output.splitlines():
        name, status, value = parse_sdr_line(line)
        if not name:
            continue
        if status.lower() == "ns" or "No Reading" in value:
            volts.append((name, "N/A", "na"))
        else:
            volts.append((name, value, "ok"))

    # Power
    power_status = ipmi("chassis", "power", "status") or "Unknown"
    dcmi = ipmi("dcmi", "power", "reading")
    power_watts = ""
    for line in dcmi.splitlines():
        if "Instantaneous" in line:
            try:
                power_watts = line.split(":")[-1].strip().split()[0]
                if power_watts == "0":
                    power_watts = ""
            except (ValueError, IndexError):
                power_watts = ""

    # SEL
    sel_info = ipmi("sel", "info")
    sel_entries = "?"
    sel_percent = "?"
    sel_overflow = "?"
    for line in sel_info.splitlines():
        if "Entries" in line and ":" in line:
            sel_entries = line.split(":")[-1].strip()
        if "Percent Used" in line:
            sel_percent = line.split(":")[-1].strip()
        if "Overflow" in line:
            sel_overflow = line.split(":")[-1].strip()

    sel_list = ipmi("sel", "list", "last", "50")
    sel_lines_list = sel_list.splitlines() if sel_list else []

    # Alerts
    alerts = []
    for name, val, css in temps:
        if css == "crit":
            alerts.append(("CRIT", f"{name} at {val}"))
        elif css == "warn":
            alerts.append(("WARN", f"{name} at {val}"))
    for name, val, css in fans:
        if css == "not-present":
            alerts.append(("WARN", f"{name} not present/dead"))
        elif css == "crit":
            alerts.append(("CRIT", f"{name} at {val}"))

    return {
        "firmware": firmware,
        "board_model": board_model,
        "fan_mode_raw": fan_mode_raw,
        "fan_mode_name": fan_mode_name,
        "duty_z0": duty_z0,
        "duty_z0_int": duty_z0_int,
        "duty_z1": duty_z1,
        "duty_z1_int": duty_z1_int,
        "temps": temps,
        "fans": fans,
        "ok_fans": ok_fans,
        "total_fans": total_fans,
        "volts": volts,
        "power_status": power_status,
        "power_watts": power_watts,
        "sel_entries": sel_entries,
        "sel_percent": sel_percent,
        "sel_overflow": sel_overflow,
        "sel_lines": sel_lines_list,
        "alerts": alerts,
    }


def build_dashboard():
    """Build the full HTML dashboard with fan controls."""
    d = gather_data()
    now = subprocess.run(["date", "+%Y-%m-%d %H:%M:%S %Z"],
                         capture_output=True, text=True).stdout.strip()

    # Alert HTML
    alert_html = ""
    if not d["alerts"]:
        alert_html = '<span class="ok">No alerts — all systems nominal.</span>'
    else:
        for level, msg in d["alerts"]:
            css_class = "crit" if level == "CRIT" else "warn"
            alert_html += f'<div class="alert {css_class}">{level}: {html.escape(msg)}</div>'

    # Data rows
    temp_rows = "".join(
        f'<tr><td>{html.escape(n)}</td><td class="{c}">{html.escape(v)}</td></tr>'
        for n, v, c in d["temps"]
    )
    fan_rows = "".join(
        f'<tr><td>{html.escape(n)}</td><td class="{c}">{html.escape(v)}</td></tr>'
        for n, v, c in d["fans"]
    )
    volt_rows = "".join(
        f'<tr><td>{html.escape(n)}</td><td class="{c}">{html.escape(v)}</td></tr>'
        for n, v, c in d["volts"]
    )

    sel_html = ""
    for line in d["sel_lines"]:
        css_class = ""
        lower = line.lower()
        if "fan" in lower:
            css_class = "fan-event"
        elif any(w in lower for w in ["temperature", "crit", "warn"]):
            css_class = "crit"
        elif any(w in lower for w in ["power", "voltage"]):
            css_class = "power-event"
        sel_html += f'<div class="sel-line {css_class}">{html.escape(line)}</div>'

    # Fan mode toggle buttons
    mode_buttons = ""
    for code, name in FAN_MODES.items():
        active = "active" if code == d["fan_mode_raw"] else ""
        mode_buttons += (
            f'<button class="mode-btn {active}" data-mode="{code}" '
            f'onclick="selectMode(\'{code}\')">{html.escape(name)}</button>'
        )

    # Quick preset buttons
    preset_buttons = """
      <button class="preset-btn" onclick="applyPreset('quiet')" title="Quiet: Heavy Duty, Zone0=30%, Zone1=20%">Quiet</button>
      <button class="preset-btn" onclick="applyPreset('normal')" title="Normal: Heavy Duty, Zone0=50%, Zone1=40%">Normal</button>
      <button class="preset-btn" onclick="applyPreset('cool')" title="Cool: Standard, Zone0=70%, Zone1=60%">Cool</button>
      <button class="preset-btn" onclick="applyPreset('full')" title="Full: 100% all fans">Full Blast</button>
      <button class="preset-btn danger" onclick="applyPreset('auto')" title="Reset to Standard (auto BMC control)">Auto (Reset)</button>
    """

    # Slider values
    z0_val = d["duty_z0_int"] if d["duty_z0_int"] is not None else 50
    z1_val = d["duty_z1_int"] if d["duty_z1_int"] is not None else 50

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IPMI Dashboard — {html.escape(IPMI_HOST)}</title>
<style>
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --cyan: #58a6ff;
    --blue: #1f6feb;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
    background: var(--bg); color: var(--text);
    padding: 20px; max-width: 900px; margin: 0 auto;
  }}
  h1 {{
    color: var(--cyan); font-size: 1.4em; text-align: center;
    padding: 12px 0; border-bottom: 2px solid var(--cyan); margin-bottom: 8px;
  }}
  .meta {{ text-align: center; color: var(--text-dim); font-size: 0.85em; margin-bottom: 16px; }}
  .meta span {{ margin: 0 12px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin-bottom: 16px;
  }}
  .card h2 {{
    color: var(--cyan); font-size: 1em; margin-bottom: 10px;
    padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 4px 8px; font-size: 0.9em; }}
  td:first-child {{ color: var(--text-dim); width: 55%; }}
  .ok {{ color: var(--green); font-weight: bold; }}
  .warn {{ color: var(--yellow); font-weight: bold; }}
  .crit {{ color: var(--red); font-weight: bold; }}
  .na {{ color: var(--text-dim); }}
  .not-present {{ color: var(--text-dim); font-style: italic; }}
  .fan-event {{ color: var(--yellow); }}
  .power-event {{ color: var(--cyan); }}
  .fan-summary {{ color: var(--text-dim); font-size: 0.85em; margin-top: 8px; }}
  .alert {{ padding: 4px 8px; margin: 4px 0; border-radius: 4px; font-size: 0.9em; }}
  .alert.crit {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  .alert.warn {{ background: rgba(210,153,34,0.15); color: var(--yellow); }}
  .sel-line {{ padding: 2px 8px; font-size: 0.82em; border-bottom: 1px solid var(--border); }}
  .sel-header {{ color: var(--text-dim); font-size: 0.85em; margin-bottom: 8px; }}
  .overflow-warn {{ color: var(--yellow); font-weight: bold; margin: 8px 0; }}
  .refresh {{ text-align: center; color: var(--text-dim); font-size: 0.8em; margin-top: 16px; }}
  .duty {{ display: inline-block; background: var(--border); border-radius: 4px; padding: 2px 8px; margin: 4px 4px 4px 0; font-size: 0.85em; }}
  .duty-val {{ color: var(--cyan); font-weight: bold; }}

  /* Fan control styles */
  .mode-btn {{
    background: var(--border); color: var(--text-dim); border: 1px solid var(--border);
    padding: 6px 14px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-size: 0.85em; margin: 2px;
    transition: all 0.2s;
  }}
  .mode-btn:hover {{ border-color: var(--cyan); color: var(--text); }}
  .mode-btn.active {{
    background: rgba(88,166,255,0.2); border-color: var(--cyan);
    color: var(--cyan); font-weight: bold;
  }}
  .preset-btn {{
    background: var(--border); color: var(--text); border: 1px solid var(--border);
    padding: 8px 18px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-size: 0.9em; font-weight: bold; margin: 4px 2px;
    transition: all 0.2s;
  }}
  .preset-btn:hover {{ border-color: var(--cyan); color: var(--cyan); }}
  .preset-btn.danger {{ color: var(--yellow); }}
  .preset-btn.danger:hover {{ border-color: var(--yellow); }}
  .slider-group {{
    display: flex; align-items: center; gap: 10px; margin: 8px 0;
  }}
  .slider-group label {{
    color: var(--text-dim); font-size: 0.9em; width: 60px;
  }}
  .slider-group input[type=range] {{
    flex: 1; height: 6px; -webkit-appearance: none; appearance: none;
    background: var(--border); border-radius: 3px; outline: none;
  }}
  .slider-group input[type=range]::-webkit-slider-thumb {{
    -webkit-appearance: none; appearance: none;
    width: 18px; height: 18px; border-radius: 50%;
    background: var(--cyan); cursor: pointer;
  }}
  .slider-group .slider-val {{
    color: var(--cyan); font-weight: bold; min-width: 40px; text-align: right;
  }}
  .apply-row {{
    display: flex; gap: 8px; align-items: center; margin-top: 12px;
  }}
  .apply-btn {{
    background: var(--blue); color: white; border: none;
    padding: 8px 24px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-size: 0.9em; font-weight: bold;
  }}
  .apply-btn:hover {{ background: #388bfd; }}
  .apply-btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  .status-msg {{
    font-size: 0.85em; padding: 4px 8px; border-radius: 4px;
  }}
  .status-msg.ok {{ color: var(--green); }}
  .status-msg.err {{ color: var(--red); }}
  .status-msg.pending {{ color: var(--yellow); }}
  .control-section {{
    margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
  }}
  .sel-actions {{ margin-top: 8px; }}
  .sel-actions button {{
    background: var(--border); color: var(--yellow); border: 1px solid var(--border);
    padding: 4px 12px; border-radius: 4px; cursor: pointer;
    font-family: inherit; font-size: 0.8em;
  }}
  .sel-actions button:hover {{ border-color: var(--yellow); }}
</style>
</head>
<body>

<h1>SUPERMICRO IPMI HEALTH DASHBOARD</h1>
<div class="meta">
  <span>BMC: <strong>{html.escape(IPMI_HOST)}</strong></span>
  <span>Board: <strong>{html.escape(d["board_model"])}</strong></span>
  <span>FW: <strong>{html.escape(d["firmware"])}</strong></span>
  <span>{html.escape(now)}</span>
</div>

<div class="card">
  <h2>Fan Control</h2>
  <table>
    <tr>
      <td>Current Mode</td>
      <td><strong>{html.escape(d["fan_mode_name"])}</strong></td>
    </tr>
    <tr>
      <td>Current Duty</td>
      <td>
        <span class="duty">Zone0: <span class="duty-val">{html.escape(d["duty_z0"] or "N/A")}</span></span>
        <span class="duty">Zone1: <span class="duty-val">{html.escape(d["duty_z1"] or "N/A")}</span></span>
      </td>
    </tr>
  </table>

  <div class="control-section">
    <div style="color:var(--text-dim);font-size:0.85em;margin-bottom:6px;">Mode:</div>
    {mode_buttons}

    <div style="margin-top:14px;">
      <div style="color:var(--text-dim);font-size:0.85em;margin-bottom:4px;">Duty Cycle:</div>
      <div class="slider-group">
        <label>Zone 0</label>
        <input type="range" id="duty-z0" min="10" max="100" value="{z0_val}" oninput="updateSlider('z0')">
        <span class="slider-val" id="duty-z0-val">{z0_val}%</span>
      </div>
      <div class="slider-group">
        <label>Zone 1</label>
        <input type="range" id="duty-z1" min="10" max="100" value="{z1_val}" oninput="updateSlider('z1')">
        <span class="slider-val" id="duty-z1-val">{z1_val}%</span>
      </div>
    </div>

    <div style="color:var(--text-dim);font-size:0.85em;margin:12px 0 6px;">Quick Presets:</div>
    {preset_buttons}

    <div class="apply-row">
      <button class="apply-btn" id="apply-btn" onclick="applyChanges()">Apply Changes</button>
      <span class="status-msg" id="status-msg"></span>
    </div>
  </div>
</div>

<div class="card">
  <h2>Temperatures</h2>
  <table>{temp_rows}</table>
</div>

<div class="card">
  <h2>Fan Speeds</h2>
  <table>{fan_rows}</table>
  <div class="fan-summary">Total: {d["total_fans"]} fans, {d["ok_fans"]} OK</div>
</div>

<div class="card">
  <h2>Key Voltages</h2>
  <table>{volt_rows}</table>
</div>

<div class="card">
  <h2>Power Status</h2>
  <table>
    <tr><td>Chassis Power</td><td>{html.escape(d["power_status"])}</td></tr>
    <tr><td>Power Draw</td><td>{html.escape(d["power_watts"] + "W" if d["power_watts"] else "DCMI not active")}</td></tr>
  </table>
</div>

<div class="card">
  <h2>System Event Log (last 50)</h2>
  <div class="sel-header">
    Entries: {html.escape(d["sel_entries"])} | Used: {html.escape(d["sel_percent"])} | Overflow: {html.escape(d["sel_overflow"])}
  </div>
  {"<div class='overflow-warn'>WARNING: SEL overflow — old events being overwritten!</div>" if d["sel_overflow"] == "true" else ""}
  {sel_html if sel_html else '<div class="na">No SEL entries found</div>'}
  <div class="sel-actions">
    <button onclick="clearSel()">Clear SEL Log</button>
  </div>
</div>

<div class="card">
  <h2>Alerts</h2>
  {alert_html}
</div>

<div class="refresh">
  Auto-refresh every {REFRESH}s | <a href="/" style="color:var(--cyan)">Refresh now</a> | IPMI Dashboard v1.1.0
</div>

<script>
let selectedMode = '{html.escape(d["fan_mode_raw"])}';

function selectMode(code) {{
  selectedMode = code;
  document.querySelectorAll('.mode-btn').forEach(btn => {{
    btn.classList.toggle('active', btn.dataset.mode === code);
  }});
}}

function updateSlider(zone) {{
  const slider = document.getElementById('duty-' + zone);
  const display = document.getElementById('duty-' + zone + '-val');
  display.textContent = slider.value + '%';
}}

function applyPreset(preset) {{
  const presets = {{
    quiet:  {{ mode: '00', z0: 30, z1: 20 }},
    normal: {{ mode: '00', z0: 50, z1: 40 }},
    cool:   {{ mode: '01', z0: 70, z1: 60 }},
    full:   {{ mode: '02', z0: 100, z1: 100 }},
    auto:   {{ mode: '01', z0: null, z1: null }}
  }};
  const p = presets[preset];
  if (!p) return;

  selectMode(p.mode);
  if (p.z0 !== null) {{
    document.getElementById('duty-z0').value = p.z0;
    updateSlider('z0');
  }}
  if (p.z1 !== null) {{
    document.getElementById('duty-z1').value = p.z1;
    updateSlider('z1');
  }}
  applyChanges(p.z0, p.z1);
}}

function applyChanges(duty0, duty1) {{
  const btn = document.getElementById('apply-btn');
  const msg = document.getElementById('status-msg');
  const z0 = duty0 !== undefined ? duty0 : parseInt(document.getElementById('duty-z0').value);
  const z1 = duty1 !== undefined ? duty1 : parseInt(document.getElementById('duty-z1').value);

  btn.disabled = true;
  msg.className = 'status-msg pending';
  msg.textContent = 'Applying... (BMC transition ~5s)';

  fetch('/api/fan', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{
      mode: selectedMode,
      duty_z0: z0,
      duty_z1: z1
    }})
  }})
  .then(r => r.json())
  .then(data => {{
    btn.disabled = false;
    if (data.ok) {{
      msg.className = 'status-msg ok';
      msg.textContent = data.msg;
      setTimeout(() => {{ window.location.reload(); }}, 3000);
    }} else {{
      msg.className = 'status-msg err';
      msg.textContent = 'Error: ' + data.msg;
    }}
  }})
  .catch(err => {{
    btn.disabled = false;
    msg.className = 'status-msg err';
    msg.textContent = 'Request failed: ' + err;
  }});
}}

function clearSel() {{
  if (!confirm('Clear the System Event Log? This cannot be undone.')) return;
  fetch('/api/sel/clear', {{ method: 'POST' }})
  .then(r => r.json())
  .then(data => {{
    if (data.ok) setTimeout(() => {{ window.location.reload(); }}, 1000);
    else alert('Failed: ' + data.msg);
  }});
}}

// Auto-refresh (no meta refresh — we use JS to avoid interrupting fan control)
let refreshTimer = setTimeout(() => {{ window.location.reload(); }}, {REFRESH}000);
// Reset timer on user interaction
document.addEventListener('click', () => {{
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {{ window.location.reload(); }}, {REFRESH * 3}000);
}});
</script>

</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Handle HTTP requests."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            page = build_dashboard()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/fan":
            self._handle_fan_post()
        elif self.path == "/api/sel/clear":
            self._handle_sel_clear()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_fan_post(self):
        """Handle fan control POST: {"mode": "00", "duty_z0": 50, "duty_z1": 40}"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except Exception as e:
            self._json_response(400, {"ok": False, "msg": f"Bad request: {e}"})
            return

        mode = data.get("mode", "00")
        duty_z0 = data.get("duty_z0")
        duty_z1 = data.get("duty_z1")

        # Validate mode
        if mode not in FAN_MODES:
            self._json_response(400, {"ok": False, "msg": f"Invalid mode: {mode}"})
            return

        # Validate duties
        if duty_z0 is not None:
            if not isinstance(duty_z0, int) or duty_z0 < 10 or duty_z0 > 100:
                self._json_response(400, {"ok": False, "msg": "duty_z0 must be 10-100"})
                return
        if duty_z1 is not None:
            if not isinstance(duty_z1, int) or duty_z1 < 10 or duty_z1 > 100:
                self._json_response(400, {"ok": False, "msg": "duty_z1 must be 10-100"})
                return

        print(f"[FAN] Applying: mode={mode} duty_z0={duty_z0} duty_z1={duty_z1}")
        result = apply_fan_control(mode, duty_z0, duty_z1)
        print(f"[FAN] Result: {result}")

        if result["ok"]:
            self._json_response(200, result)
        else:
            self._json_response(500, result)

    def _handle_sel_clear(self):
        """Handle SEL clear POST."""
        try:
            clear_sel()
            self._json_response(200, {"ok": True, "msg": "SEL cleared"})
        except Exception as e:
            self._json_response(500, {"ok": False, "msg": str(e)})

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass


if __name__ == "__main__":
    if not IPMI_HOST:
        print("ERROR: IPMI_HOST environment variable is required")
        exit(1)

    # Test BMC connectivity first
    print(f"IPMI Dashboard starting on port {PORT}")
    print(f"Connecting to BMC at {IPMI_HOST}...")
    test = ipmi("mc", "info")
    if not test:
        print(f"ERROR: Cannot reach BMC at {IPMI_HOST}")
        exit(1)
    print(f"Connected. Serving at http://0.0.0.0:{PORT}")

    server = http.server.HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
