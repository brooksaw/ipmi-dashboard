#!/usr/bin/env python3
"""
web-dashboard.py — Serves the IPMI dashboard as a web page.
Uses Python's built-in http.server — no external dependencies.
"""

import html
import http.server
import os
import subprocess
import socketserver
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


def ipmi(*args):
    """Run ipmitool and return stdout."""
    cmd = [
        "ipmitool", "-I", "lanplus",
        "-H", IPMI_HOST, "-U", IPMI_USER, "-P", IPMI_PASS,
        "-N", "5000", "-R", "2"
    ] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def parse_sdr_line(line):
    """Parse SDR format: 'Name | id | status | type | value'"""
    parts = line.split("|")
    if len(parts) < 5:
        if len(parts) >= 3:
            return parts[0].strip(), parts[2].strip(), parts[-1].strip()
        return None, None, None
    return parts[0].strip(), parts[2].strip(), parts[4].strip()


def color_temp(val_str):
    """Return CSS class for temperature value."""
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
    """Return CSS class and display text for fan."""
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


def build_dashboard():
    """Build the full HTML dashboard."""
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
    fan_modes = {
        "00": "Heavy Duty", "01": "Standard", "02": "Full (100%)",
        "04": "Optimal", "10": "PUE2 (Power Save)"
    }
    fan_mode_name = fan_modes.get(fan_mode_raw, f"Unknown ({fan_mode_raw})")

    # Fan duty
    duty_z0 = ""
    duty_z1 = ""
    raw_z0 = ipmi("raw", "0x30", "0x70", "0x66", "0x00", "0x00").strip().replace(" ", "")
    raw_z1 = ipmi("raw", "0x30", "0x70", "0x66", "0x00", "0x01").strip().replace(" ", "")
    if raw_z0:
        try:
            duty_z0 = f"{int(raw_z0, 16)}%"
        except ValueError:
            duty_z0 = "N/A"
    if raw_z1:
        try:
            duty_z1 = f"{int(raw_z1, 16)}%"
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
        # Extract number from "34 degrees C"
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

    # Build HTML
    now = subprocess.run(["date", "+%Y-%m-%d %H:%M:%S %Z"],
                         capture_output=True, text=True).stdout.strip()

    alert_html = ""
    if not alerts:
        alert_html = '<span class="ok">No alerts — all systems nominal.</span>'
    else:
        for level, msg in alerts:
            css_class = "crit" if level == "CRIT" else "warn"
            alert_html += f'<div class="alert {css_class}">{level}: {html.escape(msg)}</div>'

    temp_rows = ""
    for name, val, css in temps:
        temp_rows += f'<tr><td>{html.escape(name)}</td><td class="{css}">{html.escape(val)}</td></tr>\n'

    fan_rows = ""
    for name, val, css in fans:
        fan_rows += f'<tr><td>{html.escape(name)}</td><td class="{css}">{html.escape(val)}</td></tr>\n'

    volt_rows = ""
    for name, val, css in volts:
        volt_rows += f'<tr><td>{html.escape(name)}</td><td class="{css}">{html.escape(val)}</td></tr>\n'

    sel_html = ""
    for line in sel_lines_list:
        css_class = ""
        lower = line.lower()
        if "fan" in lower:
            css_class = "fan-event"
        elif any(w in lower for w in ["temperature", "crit", "warn"]):
            css_class = "crit"
        elif any(w in lower for w in ["power", "voltage"]):
            css_class = "power-event"
        sel_html += f'<div class="sel-line {css_class}">{html.escape(line)}</div>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IPMI Dashboard — {html.escape(IPMI_HOST)}</title>
<meta http-equiv="refresh" content="{REFRESH}">
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
    background: var(--bg);
    color: var(--text);
    padding: 20px;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{
    color: var(--cyan);
    font-size: 1.4em;
    text-align: center;
    padding: 12px 0;
    border-bottom: 2px solid var(--cyan);
    margin-bottom: 8px;
  }}
  .meta {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.85em;
    margin-bottom: 16px;
  }}
  .meta span {{ margin: 0 12px; }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
  }}
  .card h2 {{
    color: var(--cyan);
    font-size: 1em;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
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
</style>
</head>
<body>

<h1>SUPERMICRO IPMI HEALTH DASHBOARD</h1>
<div class="meta">
  <span>BMC: <strong>{html.escape(IPMI_HOST)}</strong></span>
  <span>Board: <strong>{html.escape(board_model)}</strong></span>
  <span>FW: <strong>{html.escape(firmware)}</strong></span>
  <span>{html.escape(now)}</span>
</div>

<div class="card">
  <h2>Fan Control</h2>
  <table>
    <tr><td>Mode</td><td>{html.escape(fan_mode_name)}</td></tr>
    <tr>
      <td>Duty Cycle</td>
      <td>
        <span class="duty">Zone0: <span class="duty-val">{html.escape(duty_z0 or "N/A")}</span></span>
        <span class="duty">Zone1: <span class="duty-val">{html.escape(duty_z1 or "N/A")}</span></span>
      </td>
    </tr>
  </table>
</div>

<div class="card">
  <h2>Temperatures</h2>
  <table>{temp_rows}</table>
</div>

<div class="card">
  <h2>Fan Speeds</h2>
  <table>{fan_rows}</table>
  <div class="fan-summary">Total: {total_fans} fans, {ok_fans} OK</div>
</div>

<div class="card">
  <h2>Key Voltages</h2>
  <table>{volt_rows}</table>
</div>

<div class="card">
  <h2>Power Status</h2>
  <table>
    <tr><td>Chassis Power</td><td>{html.escape(power_status)}</td></tr>
    <tr><td>Power Draw</td><td>{html.escape(power_watts + "W" if power_watts else "DCMI not active")}</td></tr>
  </table>
</div>

<div class="card">
  <h2>System Event Log (last 50)</h2>
  <div class="sel-header">
    Entries: {html.escape(sel_entries)} | Used: {html.escape(sel_percent)} | Overflow: {html.escape(sel_overflow)}
  </div>
  {"<div class='overflow-warn'>WARNING: SEL overflow — old events being overwritten!</div>" if sel_overflow == "true" else ""}
  {sel_html if sel_html else '<div class="na">No SEL entries found</div>'}
</div>

<div class="card">
  <h2>Alerts</h2>
  {alert_html}
</div>

<div class="refresh">Auto-refresh every {REFRESH}s | IPMI Dashboard v1.0.0</div>

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
