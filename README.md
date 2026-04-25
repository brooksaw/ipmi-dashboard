# Supermicro IPMI Health Dashboard

A lightweight Docker container that connects to any Supermicro server's BMC/IPMI interface and displays a full health dashboard with **fan control** — temperatures, fan speeds, voltages, power status, and the System Event Log (SEL).

Designed for Synology Docker but works anywhere Docker runs.

## What It Shows

![Dashboard](https://img.shields.io/badge/Web_UI-Dark_Theme-0d1117?style=flat-square)

```
╔══════════════════════════════════════════════════════════════╗
║          SUPERMICRO IPMI HEALTH DASHBOARD                   ║
╚══════════════════════════════════════════════════════════════╝
  BMC: 192.168.1.100  |  Board: X10SRi-F  |  FW: 3.65

  ── FAN CONTROL ───────────────────────────────────────────
  Current Mode: Standard
  Current Duty: Zone0=64%  Zone1=64%

  Mode: [Heavy Duty] [Standard*] [Full] [Optimal] [PUE2]

  Duty Cycle:
    Zone 0 ═══════════════●═══  50%
    Zone 1 ═══════════════●═══  50%

  Quick Presets:
    [Quiet] [Normal] [Cool] [Full Blast] [Auto (Reset)]

  [Apply Changes]

  ── TEMPERATURES ──────────────────────────────────────────
  CPU Temp                   34°C  OK
  PCH Temp                   39°C  OK
  System Temp                29°C  OK
  Peripheral Temp            32°C  OK

  ── FAN SPEEDS ────────────────────────────────────────────
  FAN1                  1400 RPM  OK
  FAN2                  1350 RPM  OK
  FANA                  1300 RPM  OK

  ── KEY VOLTAGES ──────────────────────────────────────────
  12V                       11.87 Volts
  5VCC                       4.95 Volts
  3.3VCC                     3.27 Volts
  VBAT                       3.05 Volts

  ── POWER STATUS ──────────────────────────────────────────
  Chassis Power: on | Power Draw: 85W

  ── SYSTEM EVENT LOG (last 50) ────────────────────────────
  Entries: 128 | Used: 25% | Overflow: false
  [Clear SEL Log]

  ── ALERTS ───────────────────────────────────────────────
  No alerts — all systems nominal.
```

## Fan Control

### Quick Presets

| Preset | Mode | Zone 0 | Zone 1 | Description |
|--------|------|--------|--------|-------------|
| **Quiet** | Heavy Duty | 30% | 20% | Near-silent, low airflow |
| **Normal** | Heavy Duty | 50% | 40% | Balanced quiet/cool |
| **Cool** | Standard | 70% | 60% | Higher airflow |
| **Full Blast** | Full | 100% | 100% | Maximum cooling |
| **Auto (Reset)** | Standard | — | — | Return to BMC auto control |

### Manual Control
1. Select a **mode** using the toggle buttons
2. Adjust **Zone 0** and **Zone 1** duty cycle sliders (10-100%)
3. Click **Apply Changes**

The BMC requires a brief transition through Full mode when switching — this is handled automatically with proper timing.

### Fan Zones
- **Zone 0** — CPU fans (FAN1-FAN4 on most boards)
- **Zone 1** — Peripheral/case fans (FANA-FANB on most boards)

## Quick Start (Synology)

### 1. SSH into your Synology
```bash
ssh admin@your-synology-ip
```

### 2. Clone this repo
```bash
cd /volume1/docker   # or wherever you keep Docker projects
git clone https://github.com/brooksaw/ipmi-dashboard.git
cd ipmi-dashboard
```

### 3. Configure your BMC credentials
```bash
cp docker-compose.example.yml docker-compose.yml
```

Edit `docker-compose.yml` and fill in your BMC details:
```yaml
environment:
  - IPMI_HOST=192.168.1.100    # Your BMC/IPMI IP address
  - IPMI_USER=ADMIN            # Your IPMI username (default: ADMIN)
  - IPMI_PASS=your-password    # Your IPMI password
  - WEB_PORT=8080              # Web UI port (default: 8080)
  - WEB_REFRESH=10             # Auto-refresh interval in seconds (default: 10)
```

### 4. Build and run
```bash
docker compose up --build -d
```

### 5. Open the dashboard
Point your browser at: `http://your-synology-ip:8080`

## Synology Container Manager (GUI)

If you prefer the Synology GUI:

1. Open **Container Manager** in DSM
2. Go to **Project** > **Create**
3. Set project name: `ipmi-dashboard`
4. Set path to the folder containing `docker-compose.yml`
5. Edit the environment variables in the compose file
6. Click **Build and Start**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IPMI_HOST` | *(required)* | BMC/IPMI IP address |
| `IPMI_USER` | `ADMIN` | IPMI username |
| `IPMI_PASS` | *(required)* | IPMI password |
| `WEB_PORT` | `8080` | Web dashboard port |
| `WEB_REFRESH` | `10` | Auto-refresh interval (seconds) |

## How It Works

- Uses `ipmitool` over LAN+ (IPMI 2.0) to query the BMC
- Supermicro OEM raw commands for fan mode (`0x30 0x45`) and duty cycle (`0x30 0x70 0x66`)
- Dark-themed web UI with Python's built-in http.server — no external dependencies
- Fan control uses a proven 2-step transition sequence:
  1. Force FULL mode (breaks out of any active preset)
  2. Wait 2 seconds (BMC timing requirement)
  3. Switch to target mode
  4. Wait 2 seconds
  5. Set duty cycles
- Auto-refresh pauses during user interaction (clicking, adjusting sliders)
- Color-coded alerts: green=OK, yellow=warning, red=critical
- Thresholds: CPU >70°C warning, >85°C critical; fans <500 RPM warning, <200 RPM critical

## Compatible Boards

Tested on Supermicro X10SRi-F and X11SSH-F. Should work with any Supermicro board that supports IPMI 2.0 LAN+.

The fan duty cycle and mode commands use Supermicro OEM raw IPMI commands. These are standard across X9/X10/X11/X12 generations.

## Troubleshooting

### "Cannot reach BMC"
- Verify the BMC IP is correct and reachable from your Docker host
- Check that IPMI is enabled in BIOS
- Try: `ping <BMC-IP>`
- Default Supermicro credentials: ADMIN / ADMIN (change this!)
- **Important:** `network_mode: host` is required in Docker for BMC LAN access

### Fan duty shows N/A
- Some older BMC firmware versions may not support the raw 0x30 0x70 commands
- Temperature and fan readings still work regardless

### Fan control not taking effect
- The BMC needs ~6 seconds to transition between modes (handled automatically)
- Some modes override duty cycles (e.g., Full mode runs all fans at 100%)
- Try applying a preset first, then fine-tune with sliders

### No SEL entries
- SEL may have been cleared, or BMC firmware may have a different SEL size

## Security Notes

- **Never expose your BMC to the internet** — IPMI is a management protocol, keep it on your LAN
- Change the default ADMIN password on your BMC
- Fan control modifies BMC settings — use responsibly
- Credentials are passed via environment variables, not stored in the image
- The web UI has no authentication — run on a trusted LAN only

## Files

```
ipmi-dashboard/
├── Dockerfile                    # Alpine 3.19 + ipmitool + bash + python3 (~15MB)
├── docker-compose.yml            # Your config (git-ignored)
├── docker-compose.example.yml    # Template to copy
├── ipmi-dashboard.sh             # Terminal dashboard script
├── web-dashboard.py              # Web UI + fan control server
├── .dockerignore                 # Keep image lean
├── .gitignore                    # Keep creds out of git
└── README.md                     # This file
```

## License

MIT — use it, share it, modify it.
