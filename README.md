# IPMI Dashboard

A self-hosted web UI for monitoring and controlling Supermicro servers over IPMI/BMC. Live sensor readings, 6-hour history charts, alerting, fan control with presets and auto curves, power on/off/cycle/reset, and the System Event Log — all from one Docker container.

Works with any Supermicro X10 or X11 board that supports IPMI 2.0 LAN+. One container can monitor multiple servers.

![dashboard screenshot placeholder](docs/screenshot.png)

---

## What you get

- **Live sensors** — temperatures, fan RPMs, voltages, power state, refreshed every 30s
- **History** — 6h time-series charts per sensor, persisted in SQLite
- **Alerts** — threshold-based, with auto-clear when readings recover
- **Fan control** — Auto/Quiet/Balanced/Performance/Full presets, plus manual zone duty sliders
- **Auto fan curves** — temperature-driven duty cycle with hysteresis (won't thrash)
- **Power control** — on, off, cycle, reset (gated behind a confirmation header)
- **System Event Log** — last 50 entries per server, lazy-loaded
- **Multi-server** — declare any number of servers in a YAML config

---

## Quick start (single server)

```bash
git clone https://github.com/brooksaw/ipmi-dashboard.git
cd ipmi-dashboard
cp .env.example .env
# edit .env with your BMC IP, user, pass, board (X10 or X11)
docker compose up -d
```

Open http://your-host:8080.

That's it. The container will:

1. Connect to the BMC over IPMI LAN+
2. Poll sensors every 30s and write history to `./data/ipmi_dashboard.db`
3. Start the web UI on port 8080
4. Run auto fan control by default — switch to manual via the UI any time

---

## Quick start (multiple servers)

```bash
git clone https://github.com/brooksaw/ipmi-dashboard.git
cd ipmi-dashboard
cp compose.multi.example.yaml compose.yaml
cp servers.example.yaml servers.yaml      # edit for your hosts
cp .env.example .env                      # edit for your passwords
docker compose up -d
```

`servers.yaml` example:

```yaml
servers:
  - id: rack-a
    name: Rack A
    board: X11
    host: 192.168.1.100
    user: ADMIN
    password: ${RACKA_IPMI_PASS}

  - id: rack-b
    name: Rack B
    board: X10
    host: 192.168.1.101
    user: ADMIN
    password: ${RACKB_IPMI_PASS}
```

Set `RACKA_IPMI_PASS` and `RACKB_IPMI_PASS` in `.env` (which is git-ignored).

---

## Synology Container Manager

If you'd rather use the DSM GUI:

1. Open **Container Manager** → **Project** → **Create**
2. Project name: `ipmi-dashboard`
3. Source: **Upload from your computer** — upload this repo as a `.zip`, or **Clone from URL** with `https://github.com/brooksaw/ipmi-dashboard.git`
4. Edit `.env` (or paste env vars in the **Environment** section)
5. **Build and Start**

Open `http://your-synology-ip:8080`.

---

## Configuration reference

All env vars live in `.env`. The example file documents every option.

| Var | Default | Notes |
|-----|---------|-------|
| `IPMI_HOST` | — | BMC IP (single-server mode) |
| `IPMI_USER` | `ADMIN` | IPMI username |
| `IPMI_PASS` | — | IPMI password |
| `IPMI_BOARD` | `X11` | `X11` (two zones) or `X10` (one zone) |
| `IPMI_NAME` | `Server` | Display name in the UI |
| `IPMI_ID` | `server1` | URL-safe id; used in `/api/sensors/<id>` etc. |
| `SERVERS_CONFIG` | unset | Path to a multi-server YAML file (overrides single-server vars) |
| `WEB_PORT` | `8080` | Host port to bind |
| `POLL_INTERVAL` | `30` | Sensor poll interval (seconds) |
| `HISTORY_RETENTION_DAYS` | `30` | Auto-prune history older than this |
| `CPU_WARN_C` | `75` | CPU temp warning threshold (°C) |
| `CPU_CRIT_C` | `90` | CPU temp critical threshold (°C) |
| `INLET_WARN_C` | `45` | Inlet temp warning threshold (°C) |
| `FAN_MIN_RPM` | `500` | Fan stall threshold (RPM) |

---

## API reference

All endpoints return JSON. Errors as `{"error": "..."}`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness check + server list |
| GET | `/api/servers` | Configured servers |
| GET | `/api/sensors/<id>` | Live sensor readings + power state |
| GET | `/api/history/<id>/<sensor_name>?hours=N` | Time-series for a sensor (max 720h) |
| GET | `/api/alerts` | Active (uncleared) alerts |
| GET | `/api/fans/<id>` | Current fan state + mode |
| POST | `/api/fans/<id>` | Apply preset or set zone duty |
| GET | `/api/events/<id>?count=N` | Recent SEL entries (max 200) |
| POST | `/api/power/<id>` | `{"action":"on\|off\|cycle\|reset"}` — requires `X-Confirm: yes` header |

### Examples

```bash
# Switch to "quiet" preset
curl -X POST -H 'Content-Type: application/json' \
  -d '{"preset":"quiet"}' http://localhost:8080/api/fans/server1

# Set zone 0 to 60% manually
curl -X POST -H 'Content-Type: application/json' \
  -d '{"zone":0,"duty":60}' http://localhost:8080/api/fans/server1

# Power cycle (note the X-Confirm header)
curl -X POST -H 'Content-Type: application/json' -H 'X-Confirm: yes' \
  -d '{"action":"cycle"}' http://localhost:8080/api/power/server1
```

---

## Fan control details

**Presets** map to (zone0, zone1) duty pairs:

| Preset | Zone 0 | Zone 1 |
|--------|--------|--------|
| auto | dynamic | dynamic |
| quiet | 20% | 20% |
| balanced | 40% | 50% |
| performance | 70% | 80% |
| full | 100% | 100% |

**Auto curve** (CPU temp → duty):

```
< 30°C → 20%   < 50°C → 50%   < 65°C → 85%
< 35°C → 25%   < 55°C → 60%   ≥ 65°C → 100%
< 40°C → 30%   < 60°C → 75%
< 45°C → 40%
```

5°C hysteresis prevents fan-speed thrashing. Curves and presets live in `app/config.py` and `app/fan_control.py` if you want to tune them.

**X10 vs X11:** X11 boards have two fan zones (CPU + Peripheral). X10 boards have a single zone — `IPMI_BOARD=X10` makes the UI hide zone 1 and the fan-write code use the X10 raw command (`0x30 0x91 ...`) instead of X11's (`0x30 0x70 ...`).

---

## Compatible boards

Tested on **X11SSH-F** and **X11SSH-TF** (X11) and **SYS-5018R-M** (X10). Should work on any Supermicro board with IPMI 2.0 LAN+.

The fan-mode-reset sequence (`raw 0x30 0x45 0x01 0x01` → sleep → `0x00`) is required on most Supermicro boards before manual zone duties stick. The dashboard handles this automatically before each duty write.

---

## Security

- **Never expose your BMC to the internet.** IPMI is a management protocol — keep it on a management VLAN.
- **Change your BMC's default `ADMIN` password.**
- Credentials live only in `.env` (git-ignored) and the running container's environment. They're not written to the database.
- Power actions require an `X-Confirm: yes` HTTP header to prevent accidental triggering.
- This app reads sensors and writes fan/power; it does not modify BIOS, BMC users, or firmware.

If you put this dashboard behind a reverse proxy, **add HTTP basic auth or your own auth layer** — the app itself is unauthenticated by design (the assumption is it lives on a trusted network).

---

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌────────────┐
│  Web UI      │     │  Flask app       │     │  ipmitool  │ ──► BMC (LAN+)
│  (Chart.js)  │ ──► │  + SQLAlchemy    │ ──► │  (subproc) │
└──────────────┘     │  + background    │     └────────────┘
                     │    poller        │
                     │  + SQLite        │
                     └──────────────────┘
```

- `app/ipmi.py` — `ipmitool` wrapper (sensors, power, fan zones, SEL)
- `app/poller.py` — background thread, 30s default poll cycle
- `app/alerts.py` — threshold evaluation, alert lifecycle
- `app/fan_control.py` — auto curve + preset application
- `app/models.py` — SQLAlchemy schema (SensorReading, Alert, PowerEvent, FanControlLog)
- `app/routes/api.py` — REST endpoints
- `app/routes/dashboard.py` — index page (Jinja-driven from server config)
- `templates/index.html` + `static/` — vanilla JS frontend, Chart.js via CDN

---

## Troubleshooting

**"ipmitool exited 1: Unable to establish LAN session"**
The BMC isn't reachable, or creds are wrong. From the host: `ipmitool -I lanplus -H <bmc-ip> -U ADMIN -P <pass> chassis status`. If that fails, the dashboard will too.

**Web UI loads but sensors say "No data"**
Wait 30s for the first poll. Check `docker logs ipmi-dashboard` — you'll see "Poller started" and per-server poll results.

**Fan duty doesn't change**
Check the board: `IPMI_BOARD=X10` for X10/X9 boards uses a different raw command. Some firmware versions don't support manual fan control at all — in that case you'll see the API call return `502` with the ipmitool error.

**"Index of /" or wrong page**
Something else is on port 8080. Change `WEB_PORT` in `.env`.

**SEL is empty**
The BMC's event log was cleared, or the firmware's SEL is at zero. Try `count=200` on `/api/events/<id>?count=200` to be sure.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Related

If you only want a **single-server one-shot CLI** (no web UI, no DB), see the original release in this repo's earlier history (or check the Git tags). This is the larger Docker-based dashboard build.
