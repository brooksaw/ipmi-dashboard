# IPMI Dashboard

A self-hosted web UI for monitoring and controlling Supermicro servers over IPMI/BMC. Live sensor readings, 6-hour history charts, alerting, fan control with presets and auto curves, power on/off/cycle/reset, the System Event Log, plus optional Unraid disk monitoring and webhook notifications — all from one Docker container.

Works with any Supermicro X10 / X11 / X12 / X13 / H11 / H12 board that speaks IPMI 2.0 LAN+. One container can monitor multiple servers.

![Dashboard overview](docs/screenshots/dashboard-overview.png)

<details>
<summary>More screenshots</summary>

### Storage / disk health (optional Unraid plugin)
![Disk monitoring](docs/screenshots/storage.png)

### Fan control with hysteresis curve + adjustment log
![Fan control](docs/screenshots/fan-control.png)

### System Event Log
![SEL log](docs/screenshots/sel-log.png)

### Multi-server fleet view
![Multi server](docs/screenshots/multi-server.png)

</details>

---

## What's new in v2.2.0

A **Settings modal** lives behind the gear icon (top-right of the dashboard). Configure everything from the browser:

- **Servers** — add/edit/delete BMCs with a Test Connection button (runs `ipmitool mc info` against the credentials you typed before saving)
- **Disks** — toggle Unraid disk monitoring on/off, swap between local file mount and SSH source, with a Test Source button
- **Alerts** — tune CPU/inlet/fan/disk thresholds with **hot reload** (changes apply on the next poll cycle, no restart needed)
- **Notifications** — set a webhook URL + format, mute individual events, send a test webhook
- **Display** — poll interval and history retention
- **About** — version, repo links, active config snapshot

Settings persist in `data/settings.json` and layer over env vars at startup. A "Restart needed" pill in the modal header tells you which changes need a container restart vs which apply immediately.

---

## What you get

- **Settings UI** — gear icon → 6-tab modal, browser-based configuration, hot-reload for thresholds + webhooks
- **Live sensors** — temperatures, fan RPMs, voltages, power state, refreshed every 30s
- **History** — 6h time-series charts per sensor, persisted in SQLite
- **Alerts** — threshold-based, with auto-clear when readings recover
- **Fan control** — Auto/Quiet/Balanced/Performance/Full presets, plus manual zone duty sliders
- **Auto fan curves** — temperature-driven duty cycle with hysteresis (won't thrash)
- **Power control** — on, off, cycle, reset (gated behind a confirmation header)
- **System Event Log** — last 50 entries per server, lazy-loaded
- **Disk health** — Unraid disks.ini integration, per-disk temp + capacity + SMART
- **Webhook notifications** — Discord, Slack, ntfy, or custom JSON; per-event mute toggles
- **Multi-server** — add via Settings UI or declare in a YAML config

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

## Unraid

### Option A — Install via Community Applications (recommended)

Once this repo is listed in [Community Applications](https://forums.unraid.net/topic/38582-plug-in-community-applications/):

1. **Apps** tab → search **`ipmi-dashboard`**
2. Click **Install** → fill in `IPMI_HOST`, `IPMI_USER`, `IPMI_PASS`
3. **Apply**

Auto-update via [CA Auto Update Applications](https://forums.unraid.net/topic/47689-plugin-ca-auto-update-applications/) plugin (Apps → Search "auto update" → install → enable for ipmi-dashboard).

### Option B — Manual template (works today, before CA approval)

```bash
# SSH into Unraid
wget -O /boot/config/plugins/dockerMan/templates-user/my-ipmi-dashboard.xml \
  https://raw.githubusercontent.com/brooksaw/ipmi-dashboard/main/templates/ipmi-dashboard.xml
```

Then in Unraid web UI → **Docker** tab → **Add Container** → **Template** dropdown → pick `ipmi-dashboard` from bottom of list. Fill in vars + Apply.

The container shows up as a managed app — no "3rd Party" badge, Autostart checkbox works, image pulls from `ghcr.io/brooksaw/ipmi-dashboard:latest`.

### For maintainers — submit to Community Applications

This repo is already structured for CA. To get listed:

1. Make sure the GHCR image exists at `ghcr.io/brooksaw/ipmi-dashboard:latest` (built by GH Actions)
2. Make the GHCR package **public** at https://github.com/users/brooksaw/packages
3. Open a PR to [Squidly271/AppFeed](https://github.com/Squidly271/AppFeed) — add `https://github.com/brooksaw/ipmi-dashboard` to `repositoryList.json`
4. Once merged (1-3 days), CA scrapes our `templates/` folder and the app shows up in everyone's CA Apps tab.

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

## Disk monitoring (optional, Unraid)

Set `DISKS_ENABLED=1` and the dashboard polls disk health in addition to BMC sensors. A "Storage" card appears below your servers showing per-disk temp, capacity, type (Data / Cache / Parity / Pool), spin state, and SMART health (PASS / WARN / FAIL).

### Source mode A — local file mount (recommended for Unraid hosts running this dashboard)

```bash
# .env
DISKS_ENABLED=1
DISKS_SOURCE=local
DISKS_LOCAL_PATH=/host/disks.ini
```

Mount Unraid's live disk-state file into the container in your `compose.yaml` or Unraid Docker template:

```yaml
volumes:
  - /var/local/emhttp/disks.ini:/host/disks.ini:ro
```

Zero credentials, zero SSH, no privileged mode required. Works for the Unraid box hosting the dashboard.

### Source mode B — remote Unraid host via SSH

```bash
# .env
DISKS_ENABLED=1
DISKS_SOURCE=ssh
DISKS_SSH_HOST=10.0.0.5
DISKS_SSH_USER=root
DISKS_SSH_KEY=/ssh_key
```

Mount your SSH key:
```yaml
volumes:
  - /path/to/your/ssh-key:/ssh_key:ro
```

The remote Unraid host's `~root/.ssh/authorized_keys` must contain the matching public key.

### Alert thresholds

| Var | Default | Meaning |
|---|---|---|
| `DISK_WARN_C` | `40` | Per-disk temp warning |
| `DISK_CRIT_C` | `50` | Per-disk temp critical |
| `DISK_CAPACITY_WARN_PCT` | `85` | Per-disk capacity used % warning |
| `DISK_CAPACITY_CRIT_PCT` | `95` | Per-disk capacity used % critical |

Webhook events `alert.opened` / `alert.cleared` fire under `server: "_disks"` with sensor name like `parity::temp` or `cache::smart`.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/disks` | Latest reading per disk |
| GET | `/api/disks/history/<disk_name>?hours=N` | Time-series temp + capacity for one disk |

When `DISKS_ENABLED` is unset/0, both endpoints return `{"enabled": false, "disks": []}`.

---

## Notifications

Set `NOTIFY_WEBHOOK_URL` in `.env` to get pushed when something interesting happens. Works with any webhook-accepting service.

```bash
# Discord
NOTIFY_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
NOTIFY_WEBHOOK_FORMAT=discord

# Slack
NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
NOTIFY_WEBHOOK_FORMAT=slack

# ntfy.sh (free push to phone)
NOTIFY_WEBHOOK_URL=https://ntfy.sh/your-topic
NOTIFY_WEBHOOK_FORMAT=ntfy

# Anything else (custom endpoint, n8n, Home Assistant)
NOTIFY_WEBHOOK_URL=https://your-host/hook
NOTIFY_WEBHOOK_FORMAT=generic   # default JSON shape
```

Events fired:

| Event | When |
|-------|------|
| `alert.opened` | Sensor breached `CPU_WARN_C` / `CPU_CRIT_C` / `INLET_WARN_C` / `FAN_MIN_RPM` |
| `alert.updated` | Existing alert escalated (`warn` → `crit`) or de-escalated |
| `alert.cleared` | Sensor returned to normal |
| `power.action` | Manual power command (`on`/`off`/`cycle`/`reset`) succeeded |
| `power.failed` | Power command failed |

Generic JSON body:
```json
{
  "event": "alert.opened",
  "server": "rack-a",
  "sensor": "CPU Temp",
  "level": "crit",
  "value": 92.0,
  "message": "[rack-a] CPU Temp = 92.0 (CRIT) — alert.opened",
  "timestamp": "2026-05-08T18:55:12.345678+00:00"
}
```

Webhook delivery is best-effort and never blocks the dashboard — failures are logged at WARNING.

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
