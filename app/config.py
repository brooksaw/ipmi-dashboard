"""Server + alert + fan configuration.

Servers are loaded from SERVERS_CONFIG (YAML file) when set, otherwise from
single-server env vars (IPMI_HOST, IPMI_USER, IPMI_PASS, IPMI_BOARD).
"""

import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    """Replace ${VAR} references in strings with env values."""
    if not isinstance(value, str):
        return value
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _load_servers() -> dict[str, dict]:
    config_path = os.environ.get("SERVERS_CONFIG")
    if config_path and Path(config_path).exists():
        if yaml is None:
            raise RuntimeError("PyYAML required to load SERVERS_CONFIG; pip install pyyaml")
        with open(config_path) as fh:
            doc = yaml.safe_load(fh) or {}
        result = {}
        for entry in doc.get("servers", []):
            sid = entry["id"]
            result[sid] = {
                "name": entry.get("name", sid.title()),
                "board": entry.get("board", "X11").upper(),
                "host": _expand_env(entry["host"]),
                "user": _expand_env(entry.get("user", "ADMIN")),
                "password": _expand_env(entry.get("password", "")),
            }
        if result:
            return result

    # Single-server fallback via env
    host = os.environ.get("IPMI_HOST", "").strip()
    if not host:
        return {}
    sid = os.environ.get("IPMI_ID", "server1")
    return {
        sid: {
            "name": os.environ.get("IPMI_NAME", sid.title()),
            "board": os.environ.get("IPMI_BOARD", "X11").upper(),
            "host": host,
            "user": os.environ.get("IPMI_USER", "ADMIN"),
            "password": os.environ.get("IPMI_PASS", ""),
        }
    }


SERVERS = _load_servers()

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
HISTORY_RETENTION_DAYS = int(os.environ.get("HISTORY_RETENTION_DAYS", "30"))

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
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
