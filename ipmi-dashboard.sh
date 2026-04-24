#!/bin/bash
# =============================================================================
# ipmi-dashboard.sh — Supermicro IPMI Health Dashboard
# =============================================================================
# Displays CPU/Peripheral temps, fan RPMs, and SEL event log summary
# for any Supermicro server with IPMI/BMC access over LAN+.
#
# Usage:
#   ./ipmi-dashboard.sh                          # interactive (prompts for creds)
#   ./ipmi-dashboard.sh -H <IP> -U <USER> -P <PASS>  # non-interactive
#
# Environment variables (override with - flags):
#   IPMI_HOST, IPMI_USER, IPMI_PASS
#
# Requires: ipmitool
# =============================================================================

set -euo pipefail

VERSION="1.0.0"

# ── Color definitions ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'  # No Color

# ── Default thresholds ──────────────────────────────────────────────────────
TEMP_WARN=70
TEMP_CRIT=85
FAN_WARN_RPM=500     # Below this = warning
FAN_CRIT_RPM=200     # Below this = critical

# ── Parse arguments ─────────────────────────────────────────────────────────
IPMI_HOST="${IPMI_HOST:-}"
IPMI_USER="${IPMI_USER:-}"
IPMI_PASS="${IPMI_PASS:-}"
SEL_LINES=50
WATCH_MODE=false
INTERVAL=5

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -H <host>    BMC/IPMI IP address"
    echo "  -U <user>    IPMI username"
    echo "  -P <pass>    IPMI password"
    echo "  -l <lines>   SEL log lines to show (default: 50)"
    echo "  -w           Watch mode (refresh every 5s)"
    echo "  -i <secs>    Watch interval in seconds (default: 5)"
    echo "  -v           Version"
    echo "  -h           This help"
    echo ""
    echo "Environment: IPMI_HOST, IPMI_USER, IPMI_PASS"
}

while getopts "H:U:P:l:wi:vh" opt; do
    case $opt in
        H) IPMI_HOST="$OPTARG" ;;
        U) IPMI_USER="$OPTARG" ;;
        P) IPMI_PASS="$OPTARG" ;;
        l) SEL_LINES="$OPTARG" ;;
        w) WATCH_MODE=true ;;
        i) INTERVAL="$OPTARG" ;;
        v) echo "ipmi-dashboard v${VERSION}"; exit 0 ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

# ── Prompt for missing credentials ──────────────────────────────────────────
if [[ -z "$IPMI_HOST" ]]; then
    read -rp "BMC IP Address: " IPMI_HOST
fi
if [[ -z "$IPMI_USER" ]]; then
    read -rp "IPMI Username [ADMIN]: " IPMI_USER
    IPMI_USER="${IPMI_USER:-ADMIN}"
fi
if [[ -z "$IPMI_PASS" ]]; then
    read -rsp "IPMI Password: " IPMI_PASS
    echo ""
fi

# ── Validate ────────────────────────────────────────────────────────────────
if [[ -z "$IPMI_HOST" || -z "$IPMI_USER" || -z "$IPMI_PASS" ]]; then
    echo -e "${RED}ERROR: Host, username, and password are required.${NC}"
    exit 1
fi

if ! command -v ipmitool &>/dev/null; then
    echo -e "${RED}ERROR: ipmitool not found. Install it first:${NC}"
    echo "  Debian/Ubuntu: sudo apt-get install ipmitool"
    echo "  Alpine:        sudo apk add ipmitool"
    echo "  Synology:      Use the Docker image (includes ipmitool)"
    exit 1
fi

# ── IPMI command wrapper ────────────────────────────────────────────────────
ipmi() {
    ipmitool -I lanplus -H "$IPMI_HOST" -U "$IPMI_USER" -P "$IPMI_PASS" \
        -N 5000 -R 2 "$@" 2>/dev/null
}

# ── Test connectivity ───────────────────────────────────────────────────────
if ! ipmi mc info &>/dev/null; then
    echo -e "${RED}ERROR: Cannot reach BMC at ${IPMI_HOST}.${NC}"
    echo "  - Check IP address"
    echo "  - Verify network connectivity (ping ${IPMI_HOST})"
    echo "  - Confirm IPMI/LAN+ is enabled in BIOS"
    echo "  - Check username/password"
    exit 1
fi

# ── Helper: colorize temperature ────────────────────────────────────────────
colorize_temp() {
    local temp="$1"
    local label="$2"
    if [[ "$temp" =~ ^[0-9]+$ ]]; then
        if (( temp >= TEMP_CRIT )); then
            printf "  %-25s ${RED}%3d°C  CRITICAL${NC}\n" "$label" "$temp"
        elif (( temp >= TEMP_WARN )); then
            printf "  %-25s ${YELLOW}%3d°C  WARNING${NC}\n" "$label" "$temp"
        else
            printf "  %-25s ${GREEN}%3d°C  OK${NC}\n" "$label" "$temp"
        fi
    else
        printf "  %-25s ${DIM}%s${NC}\n" "$label" "N/A"
    fi
}

# ── Helper: colorize fan RPM ────────────────────────────────────────────────
colorize_fan() {
    local name="$1"
    local rpm="$2"
    local status="$3"

    if [[ "$status" =~ "Device Not Present" ]] || [[ "$status" =~ "Not Present" ]]; then
        printf "  %-20s ${DIM}NOT PRESENT${NC}\n" "$name"
    elif [[ "$rpm" == "na" || -z "$rpm" ]]; then
        printf "  %-20s ${YELLOW}N/A (no reading)${NC}\n" "$name"
    elif [[ "$rpm" =~ ^[0-9]+$ ]]; then
        if (( rpm <= FAN_CRIT_RPM )); then
            printf "  %-20s ${RED}%5d RPM  CRITICAL${NC}\n" "$name" "$rpm"
        elif (( rpm <= FAN_WARN_RPM )); then
            printf "  %-20s ${YELLOW}%5d RPM  WARNING${NC}\n" "$name" "$rpm"
        else
            printf "  %-20s ${GREEN}%5d RPM  OK${NC}\n" "$name" "$rpm"
        fi
    else
        printf "  %-20s %s\n" "$name" "$rpm"
    fi
}

# ── Main dashboard function ─────────────────────────────────────────────────
ALERTS=""
ALERT_COUNT=0

run_dashboard() {
    ALERTS=""
    ALERT_COUNT=0

    # ── BMC Info ────────────────────────────────────────────────────────────
    local bmc_info board_info
    bmc_info=$(ipmi mc info 2>/dev/null)
    board_info=$(ipmi fru 2>/dev/null)

    local firmware=""
    if [[ "$bmc_info" =~ "Firmware Revision" ]]; then
        firmware=$(echo "$bmc_info" | grep "Firmware Revision" | head -1 | awk '{print $NF}')
    fi

    local board_model=""
    if echo "$board_info" | grep -q "Board Part Number"; then
        board_model=$(echo "$board_info" | grep "Board Part Number" | head -1 | sed 's/Board Part Number\s*:* *\s*//' | xargs)
    elif echo "$board_info" | grep -q "Board Product"; then
        board_model=$(echo "$board_info" | grep "Board Product" | head -1 | sed 's/Board Product\s*:*\s*//' | xargs)
    fi

    local board_serial=""
    if echo "$board_info" | grep -q "Board Serial"; then
        board_serial=$(echo "$board_info" | grep "Board Serial" | head -1 | sed 's/Board Serial\s*//' | xargs)
    fi

    # ── Header ──────────────────────────────────────────────────────────────
    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║          SUPERMICRO IPMI HEALTH DASHBOARD                   ║${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo -e "  BMC: ${BOLD}${IPMI_HOST}${NC}  |  Board: ${board_model:-unknown}  |  FW: ${firmware:-unknown}"
    echo -e "  Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo ""

    # ── Fan Control Mode ────────────────────────────────────────────────────
    local fan_mode_raw
    fan_mode_raw=$(ipmi raw 0x30 0x45 0x00 2>/dev/null | tr -d ' ' || echo "unknown")
    local fan_mode_name="Unknown"
    case "$fan_mode_raw" in
        00) fan_mode_name="Heavy Duty" ;;
        01) fan_mode_name="Standard" ;;
        02) fan_mode_name="Full (100%)" ;;
        04) fan_mode_name="Optimal" ;;
        10) fan_mode_name="PUE2 (Power Save)" ;;
        *)  fan_mode_name="Unknown ($fan_mode_raw)" ;;
    esac

    # Fan duty cycles
    local duty_z0_raw duty_z1_raw duty_z0="" duty_z1=""
    duty_z0_raw=$(ipmi raw 0x30 0x70 0x66 0x00 0x00 2>/dev/null | tr -d ' ' || echo "")
    duty_z1_raw=$(ipmi raw 0x30 0x70 0x66 0x00 0x01 2>/dev/null | tr -d ' ' || echo "")
    if [[ -n "$duty_z0_raw" ]]; then
        # Convert hex to decimal percentage
        duty_z0=$((16#$duty_z0_raw))"%"
    fi
    if [[ -n "$duty_z1_raw" ]]; then
        duty_z1=$((16#$duty_z1_raw))"%"
    fi

    echo -e "  ${BOLD}Fan Mode:${NC} $fan_mode_name"
    echo -n -e "  ${BOLD}Fan Duty:${NC} Zone0=${duty_z0:-N/A}"
    echo -e "  Zone1=${duty_z1:-N/A}"
    echo ""

    # ── Temperatures ────────────────────────────────────────────────────────
    echo -e "  ${BOLD}── TEMPERATURES ──────────────────────────────────────────${NC}"

    local temp_output
    temp_output=$(ipmi sdr type temperature 2>/dev/null)

    if [[ -n "$temp_output" ]]; then
        while IFS= read -r line; do
            local name temp_val status_text
            # Parse SDR format: "CPU Temp | 01h | ok | 3.1 | 34 degrees C"
            name=$(echo "$line" | cut -d'|' -f1 | xargs 2>/dev/null)
            status_text=$(echo "$line" | cut -d'|' -f3 | xargs 2>/dev/null)
            temp_val=$(echo "$line" | sed -n 's/.*| \([0-9][0-9]*\) degrees C.*/\1/p')
            # If no match, try second field format or mark na
            if [[ -z "$temp_val" ]]; then
                temp_val="na"
            fi

            # Handle "No Reading" sensors
            if echo "$line" | grep -q "No Reading"; then
                temp_val="na"
            fi

            [[ -z "$name" ]] && continue

            colorize_temp "$temp_val" "$name"

            # Check thresholds
            if [[ "$temp_val" =~ ^[0-9]+$ ]]; then
                if [[ "$temp_val" -ge $TEMP_CRIT ]]; then
                    ALERTS="${ALERTS}CRIT: ${name} at ${temp_val}°C. "
                    ALERT_COUNT=$((ALERT_COUNT + 1))
                elif [[ "$temp_val" -ge $TEMP_WARN ]]; then
                    ALERTS="${ALERTS}WARN: ${name} at ${temp_val}°C. "
                    ALERT_COUNT=$((ALERT_COUNT + 1))
                fi
            fi
        done <<< "$temp_output"
    else
        echo -e "  ${DIM}No temperature sensors found${NC}"
    fi

    echo ""

    # ── Fan Speeds ──────────────────────────────────────────────────────────
    echo -e "  ${BOLD}── FAN SPEEDS ────────────────────────────────────────────${NC}"

    local fan_output
    fan_output=$(ipmi sdr type fan 2>/dev/null)

    local total_fans=0
    local ok_fans=0

    if [[ -n "$fan_output" ]]; then
        while IFS= read -r line; do
            local name rpm_val status_text
            # Parse SDR format: "FAN1 | 41h | ok | 29.1 | 1400 RPM"
            name=$(echo "$line" | cut -d'|' -f1 | xargs 2>/dev/null)
            status_text=$(echo "$line" | cut -d'|' -f3 | xargs 2>/dev/null)
            rpm_val=$(echo "$line" | sed -n 's/.*| \([0-9][0-9]*\) RPM.*/\1/p')
            if [[ -z "$rpm_val" ]]; then
                rpm_val="na"
            fi

            [[ -z "$name" ]] && continue

            # Detect not present or no reading
            if echo "$line" | grep -q "No Reading"; then
                status_text="Not Present"
                rpm_val="na"
            elif echo "$status_text" | grep -qi "ns"; then
                status_text="Not Present"
            fi

            colorize_fan "$name" "$rpm_val" "$status_text"
            total_fans=$((total_fans + 1))

            if [[ "$status_text" == "Not Present" ]]; then
                ALERTS="${ALERTS}WARN: ${name} not present/dead. "
                ALERT_COUNT=$((ALERT_COUNT + 1))
            elif [[ "$rpm_val" =~ ^[0-9]+$ ]] && [[ "$rpm_val" -gt $FAN_CRIT_RPM ]]; then
                ok_fans=$((ok_fans + 1))
            elif [[ "$rpm_val" == "na" || -z "$rpm_val" ]]; then
                ALERTS="${ALERTS}WARN: ${name} has no reading. "
                ALERT_COUNT=$((ALERT_COUNT + 1))
            elif [[ "$rpm_val" =~ ^[0-9]+$ ]] && [[ "$rpm_val" -le $FAN_CRIT_RPM ]]; then
                ALERTS="${ALERTS}CRIT: ${name} at ${rpm_val} RPM (near stall). "
                ALERT_COUNT=$((ALERT_COUNT + 1))
            fi
        done <<< "$fan_output"

        echo -e "  ${DIM}Total: ${total_fans} fans, ${ok_fans} OK${NC}"
    else
        echo -e "  ${DIM}No fan sensors found${NC}"
    fi

    echo ""

    # ── Voltages (quick summary) ────────────────────────────────────────────
    echo -e "  ${BOLD}── KEY VOLTAGES ──────────────────────────────────────────${NC}"
    local volt_output
    volt_output=$(ipmi sdr type voltage 2>/dev/null)

    if [[ -n "$volt_output" ]]; then
        echo "$volt_output" | while IFS= read -r line; do
            local name volt_val status_text
            # Parse SDR format: "12V | 14h | ok | 10.1 | 11.87 Volts"
            name=$(echo "$line" | cut -d'|' -f1 | xargs 2>/dev/null)
            status_text=$(echo "$line" | cut -d'|' -f3 | xargs 2>/dev/null)
            volt_val=$(echo "$line" | cut -d'|' -f5 | xargs 2>/dev/null)
            [[ -z "$name" ]] && continue

            if echo "$status_text" | grep -qi "ns" || echo "$volt_val" | grep -qi "no reading"; then
                printf "  %-25s ${DIM}%s${NC}\n" "$name" "N/A"
            else
                printf "  %-25s %s\n" "$name" "$volt_val"
            fi
        done
    else
        echo -e "  ${DIM}No voltage sensors found${NC}"
    fi

    echo ""

    # ── Power ───────────────────────────────────────────────────────────────
    echo -e "  ${BOLD}── POWER STATUS ──────────────────────────────────────────${NC}"
    local power_status
    power_status=$(ipmi chassis power status 2>/dev/null || echo "Unknown")
    echo "  Chassis Power: $power_status"

    local dcmi_power
    dcmi_power=$(ipmi dcmi power reading 2>/dev/null || true)
    if echo "$dcmi_power" | grep -q "Instantaneous"; then
        local watts
        watts=$(echo "$dcmi_power" | grep "Instantaneous" | sed -n 's/.*: *\([0-9][0-9]*\) Watts.*/\1/p')
        if [[ -n "$watts" && "$watts" != "0" ]]; then
            echo "  Power Draw: ${watts}W"
        else
            echo "  Power Draw: DCMI not active"
        fi
    fi

    echo ""

    # ── SEL Log ─────────────────────────────────────────────────────────────
    echo -e "  ${BOLD}── SYSTEM EVENT LOG (last ${SEL_LINES} entries) ──────────${NC}"

    local sel_info
    sel_info=$(ipmi sel info 2>/dev/null || echo "UNREACHABLE")

    if echo "$sel_info" | grep -q "UNREACHABLE"; then
        echo -e "  ${DIM}SEL unreachable${NC}"
    else
        local sel_entries sel_percent sel_overflow
        sel_entries=$(echo "$sel_info" | grep "Entries" | awk '{print $NF}' || echo "?")
        sel_percent=$(echo "$sel_info" | grep "Percent Used" | awk -F': ' '{print $2}' || echo "?")
        sel_overflow=$(echo "$sel_info" | grep "Overflow" | awk -F': ' '{print $2}' || echo "?")

        echo -e "  Entries: ${sel_entries}  |  Used: ${sel_percent}  |  Overflow: ${sel_overflow}"

        if [[ "$sel_overflow" == "true" ]]; then
            echo -e "  ${YELLOW}WARNING: SEL overflow — old events are being overwritten!${NC}"
        fi

        echo ""

        local sel_list
        sel_list=$(ipmi sel list last "$SEL_LINES" 2>/dev/null || echo "")

        if [[ -n "$sel_list" ]]; then
            echo "$sel_list" | while IFS= read -r line; do
                # Color-code event types
                if echo "$line" | grep -qi "fan"; then
                    echo -e "  ${YELLOW}${line}${NC}"
                elif echo "$line" | grep -qi "temperature\|crit\|warn"; then
                    echo -e "  ${RED}${line}${NC}"
                elif echo "$line" | grep -qi "power\|voltage"; then
                    echo -e "  ${CYAN}${line}${NC}"
                else
                    echo -e "  ${line}"
                fi
            done
        else
            echo -e "  ${DIM}No SEL entries found${NC}"
        fi

        # SEL event summary
        if [[ -n "$sel_list" ]]; then
            echo ""
            echo -e "  ${BOLD}SEL Event Summary:${NC}"
            echo "$sel_list" | awk '{
                # Extract the event description (everything after the sensor name/type)
                for(i=5;i<=NF;i++) printf "%s ", $i
                print ""
            }' | sort | uniq -c | sort -rn | head -10 | while read count event; do
                printf "    %4dx  %s\n" "$count" "$event"
            done
        fi
    fi

    echo ""

    # ── Alerts Summary ──────────────────────────────────────────────────────
    echo -e "  ${BOLD}── ALERTS ───────────────────────────────────────────────${NC}"
    if [[ $ALERT_COUNT -eq 0 ]]; then
        echo -e "  ${GREEN}No alerts — all systems nominal.${NC}"
    else
        echo -e "  ${YELLOW}${ALERT_COUNT} alert(s) detected:${NC}"
        echo "$ALERTS" | tr '.' '\n' | grep -v '^$' | while read alert; do
            if echo "$alert" | grep -q "CRIT"; then
                echo -e "    ${RED}${alert}${NC}"
            else
                echo -e "    ${YELLOW}${alert}${NC}"
            fi
        done
    fi

    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# ── Run ─────────────────────────────────────────────────────────────────────
if $WATCH_MODE; then
    while true; do
        clear
        run_dashboard
        echo -e "  ${DIM}Refreshing in ${INTERVAL}s... (Ctrl+C to exit)${NC}"
        sleep "$INTERVAL"
    done
else
    run_dashboard
fi
