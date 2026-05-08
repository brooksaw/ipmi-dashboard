"""
ipmitool -I lanplus wrapper.

All IPMI interactions go through this module. Functions return plain Python
dicts/lists so callers never need to know about subprocess details.
"""

import logging
import re
import shlex
import subprocess
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(host: str, user: str, password: str, args: list[str], timeout: int = 10) -> str:
    """Execute an ipmitool command and return stdout as a string.

    Raises RuntimeError on non-zero exit or timeout.
    """
    cmd = [
        "ipmitool",
        "-I", "lanplus",
        "-H", host,
        "-U", user,
        "-P", password,
    ] + args

    # Log command with password redacted
    safe_cmd = cmd.copy()
    if "-P" in safe_cmd:
        idx = safe_cmd.index("-P")
        safe_cmd[idx + 1] = "***"
    log.debug("Running: %s", shlex.join(safe_cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ipmitool timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ipmitool not found — install it first") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"ipmitool exited {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout


def _server_args(server_cfg: dict) -> tuple[str, str, str]:
    return server_cfg["host"], server_cfg["user"], server_cfg["password"]


# ---------------------------------------------------------------------------
# Sensor parsing helpers
# ---------------------------------------------------------------------------

# SDR elist full line format:
# <Name>              | <ID> | <Type>      | <Bus> | <Addr> | <Value>         | <Status>
# The value column looks like "23.000 degrees C" or "1800.000 RPM" or "1.080 Volts"
_SDR_LINE_RE = re.compile(
    r"^(?P<name>[^|]+)\|[^|]+\|[^|]+\|[^|]+\|[^|]+\|"
    r"\s*(?P<value>[0-9.]+)\s+(?P<unit>[^|]+?)\s*\|"
    r"\s*(?P<status>[^\r\n]+)",
    re.MULTILINE,
)

_SENSOR_TYPE_MAP = {
    "degrees c": "temp",
    "rpm": "fan",
    "volts": "voltage",
    "watts": "power",
    "amps": "power",
}


def _classify_sensor(name_lower: str, unit_lower: str) -> str:
    for key, stype in _SENSOR_TYPE_MAP.items():
        if key in unit_lower:
            return stype
    # Fallback by name hints
    for keyword in ("fan", "blower"):
        if keyword in name_lower:
            return "fan"
    for keyword in ("temp", "cpu", "inlet", "exhaust", "pcb", "mb", "system"):
        if keyword in name_lower:
            return "temp"
    return "other"


def _parse_sdr_output(raw: str) -> dict[str, list[dict[str, Any]]]:
    """Parse `ipmitool sdr elist full` output into categorised sensor dicts."""
    sensors: dict[str, list[dict]] = {
        "temp": [],
        "fan": [],
        "voltage": [],
        "power": [],
        "other": [],
    }

    for line in raw.splitlines():
        parts = [p.strip() for p in line.split("|")]
        # sdr elist full: name | id_hex | status | entity_id | value_and_unit
        if len(parts) < 5:
            continue

        name = parts[0].strip()
        status = parts[2].strip().lower()
        value_raw = parts[4].strip()

        # Skip disabled / no-reading sensors
        if value_raw.lower() in ("no reading", "disabled", "not present", "n/a"):
            continue

        # Extract numeric value and unit from value_raw
        m = re.match(r"([0-9.]+)\s*(.*)", value_raw)
        if not m:
            continue

        try:
            value = float(m.group(1))
        except ValueError:
            continue

        unit = m.group(2).strip()
        sensor_type = _classify_sensor(name.lower(), unit.lower())

        sensors[sensor_type].append({
            "name": name,
            "value": value,
            "unit": unit,
            "status": status if status in ("ok", "warn", "crit", "ns") else "ok",
        })

    return sensors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_sensor_data(server_cfg: dict) -> dict[str, list[dict]]:
    """Return all sensor readings grouped by type (temp/fan/voltage/power).

    Raises RuntimeError if ipmitool fails.
    """
    host, user, password = _server_args(server_cfg)
    raw = _run(host, user, password, ["sdr", "elist", "full"])
    return _parse_sdr_output(raw)


def get_power_status(server_cfg: dict) -> str:
    """Return 'on' or 'off' (lower-cased)."""
    host, user, password = _server_args(server_cfg)
    raw = _run(host, user, password, ["power", "status"])
    # Output: "Chassis Power is on" / "Chassis Power is off"
    if "on" in raw.lower():
        return "on"
    return "off"


def set_power(server_cfg: dict, action: str) -> None:
    """Issue a power action.  action must be one of: on, off, cycle, reset."""
    valid = {"on", "off", "cycle", "reset"}
    if action not in valid:
        raise ValueError(f"Invalid power action {action!r}; must be one of {valid}")
    host, user, password = _server_args(server_cfg)
    _run(host, user, password, ["power", action])
    log.info("Power %s issued to %s (%s)", action, server_cfg.get("name"), host)


def set_fan_zone(server_cfg: dict, zone: int, duty: int) -> None:
    """Set fan zone duty cycle.

    Supports both X11 and X10 board generations.

    X11: ipmitool raw 0x30 0x70 0x66 0x01 <zone> <duty_hex>
    X10: ipmitool raw 0x30 0x91 0x5A 0x03 0x10 <duty_hex>
         (X10 only has one zone; zone arg is accepted but ignored for zone 1)
    """
    duty = max(0, min(100, int(duty)))
    duty_hex = hex(duty)
    board = server_cfg.get("board", "X11").upper()
    host, user, password = _server_args(server_cfg)

    if board == "X11":
        zone_byte = hex(int(zone))
        args = ["raw", "0x30", "0x70", "0x66", "0x01", zone_byte, duty_hex]
    else:
        # X10 — single zone command; zone arg is cosmetic here
        args = ["raw", "0x30", "0x91", "0x5A", "0x03", "0x10", duty_hex]

    _run(host, user, password, args)
    log.info(
        "Fan zone %d duty set to %d%% on %s (%s board)",
        zone, duty, server_cfg.get("name"), board,
    )


def get_sel_events(server_cfg: dict, count: int = 50) -> list[dict]:
    """Return the last *count* SEL (System Event Log) entries as dicts."""
    host, user, password = _server_args(server_cfg)
    raw = _run(host, user, password, ["sel", "elist", "last", str(count)])

    events = []
    for line in raw.splitlines():
        # Format: <id> | <date> | <time> | <desc> | <type> | <direction> | <assertion>
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        events.append({
            "id": parts[0],
            "date": parts[1],
            "time": parts[2],
            "description": parts[3],
            "type": parts[4],
            "direction": parts[5],
            "assertion": parts[6],
        })

    return list(reversed(events))  # newest first
