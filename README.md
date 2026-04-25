# Supermicro IPMI Fan Churn Fix

## The Problem

If you have a Supermicro server (X9/X10/X11/X12) and your fans keep ramping up and down — spinning fast, then slow, then fast again every few seconds — that's **fan churning**. It's loud, annoying, and wears out your fans.

This happens because Supermicro's **Heavy Duty** fan mode targets an airflow curve that assumes all fan slots are populated. If you have empty slots (common in home labs), the BMC can't hit its target and oscillates — ramp up, overshoot, ramp down, undershoot, repeat.

## The Fix

Switch to **Standard mode** with a fixed duty cycle. Standard mode lets the BMC auto-manage but uses your duty cycle as a baseline. No more oscillation.

This tool gives you two ways to do it:

| Option | Best for | Requirements |
|--------|----------|-------------|
| **Python Script** | Windows/Mac/Linux, run once | Python 3, ipmitool auto-downloaded on Windows |
| **Docker Dashboard** | Always-on web UI with live monitoring | Docker on any host |

---

## Option 1: Python Script (Windows/Mac/Linux)

The quickest fix. Run it once, pick a preset, done.

### Download

Download [`ipmi-fan-control.py`](https://github.com/brooksaw/ipmi-dashboard/raw/main/ipmi-fan-control.py) or clone the repo:

```bash
git clone https://github.com/brooksaw/ipmi-dashboard.git
```

### Configure

Open `ipmi-fan-control.py` in any text editor and edit the three values at the top:

```python
BMC_IP       = "192.168.1.100"   # Your BMC/IPMI IP address
BMC_USER     = "ADMIN"           # Your IPMI username
BMC_PASSWORD = "your-password"   # Your IPMI password
```

Your BMC IP is the address you use to access the Supermicro IPMI web interface. Default credentials are usually `ADMIN` / `ADMIN` (change this in BIOS!).

### Run

```bash
python ipmi-fan-control.py
```

On first run on Windows, it auto-downloads `ipmitool.exe` from the [GitHub Releases](https://github.com/brooksaw/ipmi-dashboard/releases) page (cross-compiled from official source). On Linux/Mac, it auto-installs via `apt` or `brew`.

### Pick a Preset

```
  QUICK PRESETS:
    [q] Quiet    — Standard, 40%/30% duty (stops churning)
    [n] Normal   — Standard, 50%/40% duty (balanced)
    [c] Cool     — Standard, 70%/60% duty (more airflow)
    [f] Full     — 100% all fans (max cooling)
    [r] Reset    — Standard mode, BMC auto-manages
```

Press **q** or **n** — that's it. Churning stops immediately.

### What It Shows

```
  TEMPERATURES:
    [OK ] CPU Temp                25.0°C
    [OK ] PCH Temp                30.0°C
    [OK ] System Temp             19.0°C
    [OK ] Peripheral Temp         22.0°C

  FANS:
    [OK ] FAN1                       800 RPM
    [OK ] FANA                      1100 RPM

  FAN CONTROL:
    Mode:     1 (Standard)
    Zone 0:   50%
    Zone 1:   40%
```

### Fan Zones

- **Zone 0** — CPU fans (FAN1–FAN4)
- **Zone 1** — Peripheral/case fans (FANA–FANB)

### Manual Control

Press **m** to pick any mode and duty cycle yourself. Duty range is 10–100%.

The five modes:
| Code | Mode | Description |
|------|------|-------------|
| 00 | Heavy Duty | ⚠️ Causes churning on boards with empty fan slots |
| 01 | Standard | ✅ Recommended — auto-manages with duty guidance |
| 02 | Full | All fans at 100% |
| 04 | Optimal | BMC balanced mode |
| 10 | PUE2 | Power save mode |

---

## Option 2: Docker Web Dashboard

An always-on dark-themed web dashboard with live monitoring and fan control. Runs on any Docker host — Synology, Unraid, Linux, whatever.

### Quick Start

```bash
git clone https://github.com/brooksaw/ipmi-dashboard.git
cd ipmi-dashboard
cp docker-compose.example.yml docker-compose.yml
```

Edit `docker-compose.yml` — fill in your BMC details:
```yaml
environment:
  - IPMI_HOST=192.168.1.100
  - IPMI_USER=ADMIN
  - IPMI_PASS=your-password
```

Build and run:
```bash
docker compose up --build -d
```

Open `http://your-host-ip:8080` in your browser.

### Dashboard Features

- **Live temperatures** — CPU, PCH, System, Peripheral, VRM, DIMMs
- **Fan speeds** — all detected fans with RPM and health status
- **Fan control** — mode selector, duty cycle sliders, quick presets
- **Voltages** — 12V, 5V, 3.3V, VBAT, CPU, DIMM rails
- **Power status** — chassis power and wattage draw
- **System Event Log** — last 50 entries, color-coded
- **Alerts** — temp/fan warnings and critical alerts
- **Auto-refresh** — 10 second intervals, pauses during interaction

### Portainer

If you use Portainer:

1. **Stacks** → **Add stack**
2. Name: `ipmi-dashboard`
3. Build method: **Repository**
4. URL: `https://github.com/brooksaw/ipmi-dashboard.git`
5. Compose path: `docker-compose.example.yml`
6. Environment variables (**Advanced Mode**):
```
IPMI_HOST=192.168.1.100
IPMI_USER=ADMIN
IPMI_PASS=your-password
WEB_PORT=8080
WEB_REFRESH=10
```
7. **Deploy the stack**

To update: Stacks → ipmi-dashboard → Pull and redeploy

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IPMI_HOST` | *(required)* | BMC/IPMI IP address |
| `IPMI_USER` | `ADMIN` | IPMI username |
| `IPMI_PASS` | *(required)* | IPMI password |
| `WEB_PORT` | `8080` | Web dashboard port |
| `WEB_REFRESH` | `10` | Auto-refresh interval (seconds) |

---

## How It Works

The fix uses Supermicro OEM raw IPMI commands:

| Command | NetFn | Cmd | Data | Purpose |
|---------|-------|-----|------|---------|
| Read mode | 0x30 | 0x45 | 0x00 | Get current fan mode |
| Set mode | 0x30 | 0x45 | 0x01, mode | Set fan mode |
| Read duty | 0x30 | 0x70 | 0x66, 0x00, zone | Get zone duty % |
| Set duty | 0x30 | 0x70 | 0x66, 0x01, zone, % | Set zone duty % |

Mode transitions require a two-step sequence with 2-second delays:
1. Force **Full mode** (breaks out of any active algorithm)
2. Wait 2 seconds
3. Set **target mode**
4. Wait 2 seconds
5. Set duty cycles

These are standard across all Supermicro X9/X10/X11/X12 generations.

## Compatible Boards

Tested on:
- **X10SRi-F** — confirmed churning fix with Standard mode
- **X11SSH-F** — confirmed working

Should work with any Supermicro board that supports IPMI 2.0.

## Troubleshooting

### Fans still churning after applying a preset
- Make sure you're using **Standard mode** (01), not Heavy Duty (00)
- Try **Normal** (50/40%) instead of Quiet (40/30%)
- Some boards need duty above 40% on Zone 0 to stop oscillating
- Check if all your fan slots are populated — empty slots make it worse

### "Cannot reach BMC"
- Verify BMC IP: `ping your-bmc-ip`
- Check IPMI is enabled in BIOS
- Default Supermicro credentials: ADMIN / ADMIN
- Docker: must use `network_mode: host`

### Docker shows blank page or "Index of /"
- Container exits immediately if `IPMI_HOST` is empty
- Make sure environment variables are actually set (check Portainer Advanced Mode)
- Check nothing else is using port 8080 (change `WEB_PORT`)

### Python script: "Download failed: binary not available yet"
- The GitHub Actions build needs to run first — go to the [Actions tab](https://github.com/brooksaw/ipmi-dashboard/actions) and trigger "Build ipmitool.exe" manually
- Or download `ipmitool.exe` from the [Releases page](https://github.com/brooksaw/ipmi-dashboard/releases) and place it next to the script

### Python script won't connect
- `ipmitool.exe` is auto-downloaded from GitHub Releases on first run
- If behind a proxy/firewall: download `ipmitool.exe` manually from [Releases](https://github.com/brooksaw/ipmi-dashboard/releases) and place next to the script
- Or install via Chocolatey: `choco install ipmitool`
- Or install via WSL: `sudo apt install ipmitool`
- Check Windows Firewall isn't blocking outbound UDP 623 (RMCP port)

## Security

- **Never expose BMC to the internet** — IPMI is a LAN-only management protocol
- Change the default ADMIN password in BIOS
- The web dashboard has no authentication — only use on trusted networks
- Credentials are passed via environment variables, never stored in images

## Files

```
ipmi-dashboard/
├── ipmi-fan-control.py           # Standalone Python script (Windows/Mac/Linux)
├── web-dashboard.py              # Web dashboard + fan control server
├── ipmi-dashboard.sh             # Terminal dashboard script
├── Dockerfile                    # Alpine + ipmitool + python3 (~15MB)
├── docker-compose.example.yml    # Docker compose template
├── .gitignore                    # Keeps creds out of git
├── .dockerignore                 # Keeps image lean
└── README.md
```

## License

MIT — use it, share it, fix your fans.
