"""Server + alert + fan configuration.

Servers are loaded with this precedence (first non-empty wins):

  1. settings.json under the ``servers`` key (managed by the Settings UI)
  2. YAML file pointed to by ``SERVERS_CONFIG``
  3. Single-server fallback from ``IPMI_HOST`` / ``IPMI_USER`` / ``IPMI_PASS`` envs

The source is recorded in ``SERVERS_SOURCE`` so the Settings UI can show a
banner like "Servers managed via servers.yaml — edit that file to change".
"""

import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

from . import settings_store


_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    """Replace ${VAR} references in strings with env values."""
    if not isinstance(value, str):
        return value
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _normalise_server(sid: str, raw: dict) -> dict:
    """Coerce a raw server dict into the canonical shape used everywhere else
    in the app (host/user/password/board/name)."""
    return {
        "name": raw.get("name") or sid.title(),
        "board": (raw.get("board") or "X11").upper(),
        "host": _expand_env(raw.get("host", "")),
        "user": _expand_env(raw.get("user") or "ADMIN"),
        "password": _expand_env(raw.get("password", "")),
    }


def _load_from_settings_json() -> dict[str, dict]:
    """Read servers from settings.json (managed by the Settings UI). The
    settings tree shape is:

        {"servers": {"<id>": {"name":..., "board":..., "host":..., ...}}}
    """
    raw = settings_store.get("servers")
    if not isinstance(raw, dict) or not raw:
        return {}
    result: dict[str, dict] = {}
    for sid, entry in raw.items():
        if not isinstance(entry, dict) or not entry.get("host"):
            continue  # skip malformed entries silently
        result[sid] = _normalise_server(sid, entry)
    return result


def _load_from_yaml() -> dict[str, dict]:
    config_path = os.environ.get("SERVERS_CONFIG")
    if not config_path or not Path(config_path).exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML required to load SERVERS_CONFIG; pip install pyyaml")
    with open(config_path) as fh:
        doc = yaml.safe_load(fh) or {}
    result: dict[str, dict] = {}
    for entry in doc.get("servers", []):
        sid = entry["id"]
        result[sid] = _normalise_server(sid, {
            "name": entry.get("name"),
            "board": entry.get("board"),
            "host": entry.get("host"),
            "user": entry.get("user"),
            "password": entry.get("password"),
        })
    return result


def _load_from_env() -> dict[str, dict]:
    host = os.environ.get("IPMI_HOST", "").strip()
    if not host:
        return {}
    sid = os.environ.get("IPMI_ID", "server1")
    return {
        sid: _normalise_server(sid, {
            "name": os.environ.get("IPMI_NAME"),
            "board": os.environ.get("IPMI_BOARD"),
            "host": host,
            "user": os.environ.get("IPMI_USER"),
            "password": os.environ.get("IPMI_PASS"),
        })
    }


def _load_servers() -> tuple[dict[str, dict], str]:
    """Return (servers, source) where source is one of:
        'settings.json' | 'yaml' | 'env' | 'none'
    """
    s = _load_from_settings_json()
    if s:
        return s, "settings.json"
    s = _load_from_yaml()
    if s:
        return s, "yaml"
    s = _load_from_env()
    if s:
        return s, "env"
    return {}, "none"


SERVERS, SERVERS_SOURCE = _load_servers()

# Display / runtime tuning. All three are RESTART_REQUIRED — bound at boot
# into closures (poller loop, prune loop, Flask app port). Values read here
# stay fixed for the life of the process; the Settings UI shows a "Restart
# needed" pill when any of these change in settings.json.
POLL_INTERVAL = settings_store.get_int("poll_interval", "POLL_INTERVAL", 30)
HISTORY_RETENTION_DAYS = settings_store.get_int("history_retention_days", "HISTORY_RETENTION_DAYS", 30)

ALERT_THRESHOLDS = {
    "cpu": {
        "warn": float(os.environ.get("CPU_WARN_C", "75")),
        "crit": float(os.environ.get("CPU_CRIT_C", "90")),
    },
    "inlet": {
        "warn": float(os.environ.get("INLET_WARN_C", "45")),
        "crit": None,
    },
    "fan": {
        "min": float(os.environ.get("FAN_MIN_RPM", "500")),
    },
    "disk_temp": {
        "warn": float(os.environ.get("DISK_WARN_C", "40")),
        "crit": float(os.environ.get("DISK_CRIT_C", "50")),
    },
    "disk_capacity": {
        "warn": float(os.environ.get("DISK_CAPACITY_WARN_PCT", "85")),
        "crit": float(os.environ.get("DISK_CAPACITY_CRIT_PCT", "95")),
    },
}

FAN_PRESETS = {
    "auto":        {"zone0": None, "zone1": None},
    "quiet":       {"zone0": 20,   "zone1": 20},
    "balanced":    {"zone0": 40,   "zone1": 50},
    "performance": {"zone0": 70,   "zone1": 80},
    "full":        {"zone0": 100,  "zone1": 100},
}

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////app/data/ipmi_dashboard.db")
FAN_MODE_FILE = os.environ.get("FAN_MODE_FILE", "/app/data/fan_mode.txt")
FAN_STATE_FILE = os.environ.get("FAN_STATE_FILE", "/app/data/fan_state.json")
WEB_PORT = settings_store.get_int("web_port", "WEB_PORT", 8080)
