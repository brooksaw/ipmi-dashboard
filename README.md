# Supermicro IPMI Health Dashboard

A lightweight Docker container that connects to any Supermicro server's BMC/IPMI interface and displays a full health dashboard — temperatures, fan speeds, voltages, power status, and the System Event Log (SEL).

Designed for Synology Docker but works anywhere Docker runs.

## What It Shows

```
╔══════════════════════════════════════════════════════════════╗
║          SUPERMICRO IPMI HEALTH DASHBOARD                   ║
╚══════════════════════════════════════════════════════════════╝
  BMC: 192.168.1.100  |  Board: X10SRi-F  |  FW: 3.65
  Time: 2026-04-25 11:20:00 NZT

  Fan Mode: Standard
  Fan Duty: Zone0=64%  Zone1=64%

  ── TEMPERATURES ──────────────────────────────────────────
  CPU Temp                   34°C  OK
  PCH Temp                   39°C  OK
  System Temp                29°C  OK
  Peripheral Temp            32°C  OK
  ...

  ── FAN SPEEDS ────────────────────────────────────────────
  FAN1                  1400 RPM  OK
  FAN2                  1350 RPM  OK
  FANA                  1300 RPM  OK
  Total: 6 fans, 3 OK

  ── KEY VOLTAGES ──────────────────────────────────────────
  12V                       11.87 Volts
  5VCC                       4.95 Volts
  3.3VCC                     3.27 Volts
  VBAT                       3.05 Volts
  ...

  ── POWER STATUS ──────────────────────────────────────────
  Chassis Power: Chassis Power is on
  Power Draw: 85W

  ── SYSTEM EVENT LOG (last 50 entries) ──────────
  Entries: 128  |  Used: 25%  |  Overflow: false
  ...color-coded event log...

  ── ALERTS ───────────────────────────────────────────────
  No alerts — all systems nominal.
```

## Quick Start (Synology)

### 1. SSH into your Synology
```bash
ssh admin@your-synology-ip
```

### 2. Clone this repo
```bash
cd /volume1/docker   # or wherever you keep Docker projects
git clone https://github.com/YOUR-REPO/ipmi-dashboard.git
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
```

### 4. Build and run
```bash
docker compose up --build
```

That's it. You'll see the full health dashboard printed to your terminal.

## Usage Options

### One-shot (run once, print, exit)
```bash
docker compose up --build
```

### Show more SEL log entries (e.g. 100)
Edit `docker-compose.yml`, change the command line:
```yaml
command: ["-l", "100"]
```

### Watch mode (auto-refresh every 10 seconds)
```yaml
command: ["-w", "-i", "10"]
```

### Command-line flags
```
  -H <host>    BMC/IPMI IP address
  -U <user>    IPMI username
  -P <pass>    IPMI password
  -l <lines>   SEL log lines to show (default: 50)
  -w           Watch mode (continuous refresh)
  -i <secs>    Watch interval in seconds (default: 5)
  -v           Version
  -h           Help
```

## Synology Container Manager (GUI)

If you prefer the Synology GUI:

1. Open **Container Manager** in DSM
2. Go to **Project** > **Create**
3. Set project name: `ipmi-dashboard`
4. Set path to the folder containing `docker-compose.yml`
5. Edit the environment variables in the compose file
6. Click **Build and Start**

## Running Without Docker

If you have a Linux machine with `ipmitool` installed:

```bash
# Install ipmitool
sudo apt-get install ipmitool   # Debian/Ubuntu
sudo yum install ipmitool       # RHEL/CentOS

# Run directly
chmod +x ipmi-dashboard.sh
./ipmi-dashboard.sh -H 192.168.1.100 -U ADMIN -P your-password
```

## How It Works

- Uses `ipmitool` over LAN+ (IPMI 2.0) to query the BMC
- Supermicro OEM raw commands for fan mode and duty cycle
- Color-coded output: green=OK, yellow=warning, red=critical
- Alert thresholds: CPU >70°C warning, >85°C critical; fans <500 RPM warning, <200 RPM critical
- SEL events are color-coded by type (fan/temperature/power)

## Compatible Boards

Tested on Supermicro X10SRi-F and X11SSH-F. Should work with any Supermicro board that supports IPMI 2.0 LAN+.

The fan duty cycle and mode commands use Supermicro OEM raw IPMI commands (0x30 0x45 / 0x30 0x70). These are standard across X9/X10/X11/X12 generations.

## Troubleshooting

### "Cannot reach BMC"
- Verify the BMC IP is correct and reachable from your Docker host
- Check that IPMI is enabled in BIOS
- Try: `ping <BMC-IP>`
- Default Supermicro credentials: ADMIN / ADMIN (change this!)

### "ipmitool not found"
- Use the Docker image — it includes ipmitool
- If running bare-metal: `sudo apt-get install ipmitool`

### Fan duty shows N/A
- Some older BMC firmware versions may not support the raw 0x30 0x70 commands
- Fan mode and duty display is cosmetic — temperature and fan readings still work

### No SEL entries
- SEL may have been cleared, or BMC firmware may have a different SEL size
- Try: `docker compose run --rm ipmi-dashboard -l 200` for more entries

## Security Notes

- **Never expose your BMC to the internet** — IPMI is a management protocol, keep it on your LAN
- Change the default ADMIN password on your BMC
- This tool only reads data — it does not modify any settings
- Credentials are passed via environment variables, not stored in the image

## Files

```
ipmi-dashboard/
├── Dockerfile                    # Alpine + ipmitool + bash (~15MB)
├── docker-compose.yml            # Your config (git-ignored)
├── docker-compose.example.yml    # Template to copy
├── ipmi-dashboard.sh             # The main script
├── .dockerignore                 # Keep image lean
└── README.md                     # This file
```

## License

MIT — use it, share it, modify it.
