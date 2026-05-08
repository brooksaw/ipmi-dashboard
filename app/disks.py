"""Disk monitoring for Unraid hosts.

Parses Unraid's `/var/local/emhttp/disks.ini` to extract per-disk:
- name, type (Data/Cache/Parity/Pool/etc.), temperature, capacity percentage,
  spin state (where available), SMART health status (where available).

Two source modes (set DISKS_SOURCE):

  local:  read disks.ini from a path on the host filesystem mounted into the
          container (recommended when the dashboard runs on the same Unraid
          box you want to monitor). Default path: /host/disks.ini.

  ssh:    SSH into a remote Unraid host and `cat` the file. Requires
          DISKS_SSH_HOST / DISKS_SSH_USER and an SSH key mounted at
          DISKS_SSH_KEY (read-only).

Disabled by default. Set DISKS_ENABLED=1 to turn on.
"""

from __future__ import annotations

import configparser
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


# -- config ------------------------------------------------------------------

ENABLED = os.environ.get("DISKS_ENABLED", "0") == "1"
SOURCE = os.environ.get("DISKS_SOURCE", "local").lower()  # local | ssh
LOCAL_PATH = os.environ.get("DISKS_LOCAL_PATH", "/host/disks.ini")
SSH_HOST = os.environ.get("DISKS_SSH_HOST", "")
SSH_USER = os.environ.get("DISKS_SSH_USER", "root")
SSH_KEY = os.environ.get("DISKS_SSH_KEY", "/ssh_key")
SSH_TIMEOUT = int(os.environ.get("DISKS_SSH_TIMEOUT", "8"))


# -- public --------------------------------------------------------------------

def get_disks() -> list[dict]:
    """Return list of disk dicts. Each dict has:
        disk_name, disk_type, temp (°C, float), capacity_pct (float),
        spun_up (bool|None), health (str: PASS|WARN|FAIL|UNKNOWN).
    Empty list on error or when disabled — never raises."""
    if not ENABLED:
        return []
    try:
        if SOURCE == "ssh":
            content = _fetch_via_ssh()
        else:
            content = _fetch_local()
    except Exception as exc:
        log.warning("Disk fetch failed (source=%s): %s", SOURCE, exc)
        return []

    if not content:
        return []

    return _parse(content)


# -- fetch ---------------------------------------------------------------------

def _fetch_local() -> str:
    p = Path(LOCAL_PATH)
    if not p.exists():
        log.warning("DISKS_LOCAL_PATH not found: %s", LOCAL_PATH)
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _fetch_via_ssh() -> str:
    if not SSH_HOST:
        log.warning("DISKS_SSH_HOST not set; disks via ssh disabled")
        return ""
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_TIMEOUT}",
        f"{SSH_USER}@{SSH_HOST}",
        "cat /var/local/emhttp/disks.ini",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT + 5)
    if result.returncode != 0:
        raise RuntimeError(f"ssh exited {result.returncode}: {result.stderr.strip()[:200]}")
    return result.stdout


# -- parse ---------------------------------------------------------------------

def _unquote(val: str) -> str:
    val = (val or "").strip()
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        return val[1:-1]
    return val


def _safe_int(val: str) -> int:
    try:
        return int(_unquote(val))
    except (ValueError, AttributeError, TypeError):
        return 0


def _safe_float(val: str) -> float | None:
    try:
        s = _unquote(val)
        if not s or s == "*":
            return None
        return float(s)
    except (ValueError, AttributeError, TypeError):
        return None


def _parse(content: str) -> list[dict]:
    """Unraid disks.ini uses quoted section headers like ["parity"]; strip
    the quotes so configparser can handle it."""
    cleaned = content.replace('["', '[').replace('"]', ']')

    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read_string(cleaned)
    except configparser.Error as exc:
        log.warning("disks.ini parse error: %s", exc)
        return []

    disks: list[dict] = []
    for section in parser.sections():
        temp = _safe_float(parser.get(section, "temp", fallback=""))
        if temp is None:
            continue  # disk has no temp reading (offline / unsupported)

        name = _unquote(parser.get(section, "name", fallback=section))
        disk_type = _unquote(parser.get(section, "type", fallback=""))

        fs_size = _safe_int(parser.get(section, "fsSize", fallback="0"))
        fs_free = _safe_int(parser.get(section, "fsFree", fallback="0"))
        capacity_pct = round((1 - fs_free / fs_size) * 100, 1) if fs_size > 0 else 0.0

        # Optional fields if Unraid version exposes them
        spun_state = _unquote(parser.get(section, "spundown", fallback=""))
        spun_up: bool | None = None
        if spun_state in ("0", "false"):
            spun_up = True
        elif spun_state in ("1", "true"):
            spun_up = False

        smart_status = _unquote(parser.get(section, "color", fallback="")).lower()
        # Unraid uses CSS color hints: green-on/yellow-on/red-on; map to PASS/WARN/FAIL
        if "green" in smart_status:
            health = "PASS"
        elif "yellow" in smart_status:
            health = "WARN"
        elif "red" in smart_status:
            health = "FAIL"
        else:
            health = "UNKNOWN"

        disks.append({
            "disk_name": name,
            "disk_type": disk_type,
            "temp": temp,
            "capacity_pct": capacity_pct,
            "spun_up": spun_up,
            "health": health,
        })

    return disks
