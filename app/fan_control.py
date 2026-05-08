"""Dynamic fan control driven by CPU temperature.

For each configured server, the poller calls apply_fan_control(server_cfg, sensor_data).
A stepped curve maps CPU temp -> duty cycle, with hysteresis to prevent thrashing.
X11 boards have two zones; zone 1 mirrors zone 0 by default.
X10 boards have one zone (zone arg ignored at the ipmitool layer).
"""

import json
import logging
import os
import time

from .config import FAN_MODE_FILE, FAN_STATE_FILE
from .ipmi import _run, set_fan_zone

log = logging.getLogger(__name__)

FAN_CURVE = [
    (30, 20), (35, 25), (40, 30), (45, 40), (50, 50),
    (55, 60), (60, 75), (65, 85), (999, 100),
]

HYSTERESIS = 5

_last_duty: dict[str, dict[int, int]] = {}


def get_fan_state() -> dict:
    try:
        with open(FAN_STATE_FILE) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"mode": "auto"}


def _save_fan_state(**kwargs) -> None:
    state = get_fan_state()
    state.update(kwargs)
    os.makedirs(os.path.dirname(FAN_STATE_FILE), exist_ok=True)
    with open(FAN_STATE_FILE, "w") as fh:
        json.dump(state, fh)


def _get_fan_mode() -> str:
    try:
        with open(FAN_MODE_FILE) as fh:
            return fh.read().strip() or "auto"
    except FileNotFoundError:
        return "auto"


def set_fan_mode(mode: str) -> None:
    os.makedirs(os.path.dirname(FAN_MODE_FILE), exist_ok=True)
    with open(FAN_MODE_FILE, "w") as fh:
        fh.write(mode)
    _save_fan_state(mode=mode)


def is_auto_mode() -> bool:
    return _get_fan_mode() == "auto"


def _lookup_duty(curve, temp):
    for threshold, duty in curve:
        if temp < threshold:
            return duty
    return curve[-1][1]


def _get_cpu_temp(sensor_data):
    for reading in sensor_data.get("temp", []):
        if "cpu" in reading["name"].lower():
            return reading["value"]
    return None


def apply_fan_control(server_cfg: dict, sensor_data: dict) -> list[dict]:
    """Auto fan control for one server. Returns list of log dicts (one per zone changed)."""
    server_id = server_cfg.get("id") or server_cfg.get("name", "server").lower()
    cpu_temp = _get_cpu_temp(sensor_data)
    if cpu_temp is None:
        log.warning("No CPU temp available for %s, skipping fan control", server_id)
        return []

    target = _lookup_duty(FAN_CURVE, cpu_temp)
    board = server_cfg.get("board", "X11").upper()
    zones = (0, 1) if board == "X11" else (0,)

    last = _last_duty.setdefault(server_id, {})
    fan_logs = []

    # Reset to "Full" mode then back to "Standard" — required on Supermicro boards
    # before manual zone duties stick. (Raw 0x30 0x45 0x01 <mode>)
    host, user, password = server_cfg["host"], server_cfg["user"], server_cfg["password"]
    needs_apply = any(
        last.get(z) is None or abs(target - last[z]) >= HYSTERESIS for z in zones
    )
    if not needs_apply:
        log.debug("%s fan: CPU %.0f°C -> %d%% (no change)", server_id, cpu_temp, target)
        return []

    _run(host, user, password, ["raw", "0x30", "0x45", "0x01", "0x01"])
    time.sleep(0.5)
    _run(host, user, password, ["raw", "0x30", "0x45", "0x01", "0x00"])

    for z in zones:
        prev = last.get(z, 0)
        if last.get(z) is None or abs(target - prev) >= HYSTERESIS:
            set_fan_zone(server_cfg, z, target)
            log.info("%s zone %d fan: %.0f°C -> %d%% (was %d%%)", server_id, z, cpu_temp, target, prev)
            fan_logs.append({
                "zone": z,
                "source_temp": cpu_temp,
                "source_label": "cpu_temp",
                "target_duty": target,
                "prev_duty": prev,
            })
            last[z] = target
            _save_fan_state(**{f"{server_id}_zone{z}": target})

    return fan_logs
