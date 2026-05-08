"""
Alert evaluation and lifecycle management.

evaluate_alerts() compares the latest SensorReadings against the active
thresholds (settings.json overrides env vars), opens new Alert rows when
a threshold is breached, and clears them when the reading returns to normal.

Thresholds are read fresh at every poll, so changes via the settings UI
take effect on the next poll cycle (no restart needed).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import settings_store
from .config import ALERT_THRESHOLDS  # used as last-resort defaults
from .models import Alert, SensorReading
from .notifications import send_event

log = logging.getLogger(__name__)


def _live_thresholds() -> dict:
    """Build the active threshold map from settings.json -> env -> defaults."""
    d = ALERT_THRESHOLDS  # built-in defaults from env
    return {
        "cpu": {
            "warn": settings_store.get_float("alerts.cpu.warn", "CPU_WARN_C", d["cpu"]["warn"]),
            "crit": settings_store.get_float("alerts.cpu.crit", "CPU_CRIT_C", d["cpu"]["crit"]),
        },
        "inlet": {
            "warn": settings_store.get_float("alerts.inlet.warn", "INLET_WARN_C", d["inlet"]["warn"]),
            "crit": d["inlet"].get("crit"),
        },
        "fan": {
            "min": settings_store.get_float("alerts.fan.min", "FAN_MIN_RPM", d["fan"]["min"]),
        },
        "disk_temp": {
            "warn": settings_store.get_float("alerts.disk_temp.warn", "DISK_WARN_C", d["disk_temp"]["warn"]),
            "crit": settings_store.get_float("alerts.disk_temp.crit", "DISK_CRIT_C", d["disk_temp"]["crit"]),
        },
        "disk_capacity": {
            "warn": settings_store.get_float("alerts.disk_capacity.warn", "DISK_CAPACITY_WARN_PCT", d["disk_capacity"]["warn"]),
            "crit": settings_store.get_float("alerts.disk_capacity.crit", "DISK_CAPACITY_CRIT_PCT", d["disk_capacity"]["crit"]),
        },
    }


def _threshold_level(sensor_type: str, sensor_name: str, value: float, t: dict) -> str | None:
    """Return 'crit', 'warn', or None based on thresholds (passed in for hot-reload)."""
    name_lower = sensor_name.lower()

    if sensor_type == "temp" and any(k in name_lower for k in ("cpu", "processor")):
        cpu = t["cpu"]
        if cpu.get("crit") is not None and value >= cpu["crit"]:
            return "crit"
        if cpu.get("warn") is not None and value >= cpu["warn"]:
            return "warn"

    elif sensor_type == "temp" and "inlet" in name_lower:
        inlet = t["inlet"]
        if inlet.get("warn") is not None and value >= inlet["warn"]:
            return "warn"

    elif sensor_type == "fan":
        fan = t["fan"]
        if fan.get("min") is not None and value < fan["min"]:
            return "crit"

    return None


def evaluate_alerts(server: str, readings: list[dict], session: Session) -> None:
    """Compare *readings* from a poll cycle against thresholds.

    Opens new Alert rows for new breaches; sets cleared_at for resolved ones.
    """
    breaches: dict[str, tuple[str, float]] = {}  # sensor_name -> (level, value)
    t = _live_thresholds()

    for r in readings:
        level = _threshold_level(r["sensor_type"], r["name"], r["value"], t)
        if level:
            breaches[r["name"]] = (level, r["value"])

    # Fetch currently open (uncleared) alerts for this server
    open_alerts: list[Alert] = (
        session.query(Alert)
        .filter(Alert.server == server, Alert.cleared_at.is_(None))
        .all()
    )
    open_by_sensor: dict[str, Alert] = {a.sensor_name: a for a in open_alerts}

    now = datetime.now(timezone.utc)

    # Open new alerts / upgrade existing ones
    for sensor_name, (level, value) in breaches.items():
        existing = open_by_sensor.get(sensor_name)
        if existing is None:
            alert = Alert(
                server=server,
                sensor_name=sensor_name,
                level=level,
                value=value,
                fired_at=now,
            )
            session.add(alert)
            log.warning("Alert OPENED: %s %s %s=%.1f", server, level.upper(), sensor_name, value)
            send_event("alert.opened", server=server, sensor=sensor_name, level=level, value=value)
        elif existing.level != level:
            # Upgrade/downgrade in place (update level and value)
            old_level = existing.level
            existing.level = level
            existing.value = value
            log.warning("Alert UPDATED: %s %s -> %s %s=%.1f", server, old_level.upper(), level.upper(), sensor_name, value)
            send_event("alert.updated", server=server, sensor=sensor_name, level=level, value=value)

    # Clear alerts no longer in breach
    for sensor_name, alert in open_by_sensor.items():
        if sensor_name not in breaches:
            alert.cleared_at = now
            log.info("Alert CLEARED: %s %s", server, sensor_name)
            send_event("alert.cleared", server=server, sensor=sensor_name, level="info", value=alert.value)

    session.commit()


def evaluate_disk_alerts(disks: list[dict], session: Session) -> None:
    """Open/clear alerts for each monitored disk based on temp, capacity, and SMART health.

    Uses sensor "server" namespace = "_disks" so disks share the same Alert
    table as IPMI sensors but stay segregated from any per-server alerts.
    """
    if not disks:
        return

    DISK_SERVER = "_disks"
    breaches: dict[str, tuple[str, float]] = {}

    t = _live_thresholds()
    temp_t = t["disk_temp"]
    cap_t = t["disk_capacity"]

    for d in disks:
        name = d["disk_name"]
        temp = d.get("temp", 0)
        cap = d.get("capacity_pct", 0)
        health = (d.get("health") or "UNKNOWN").upper()

        # SMART failure trumps everything
        if health == "FAIL":
            breaches[f"{name}::smart"] = ("crit", 0)
        elif health == "WARN":
            breaches[f"{name}::smart"] = ("warn", 0)

        # Temperature
        if temp_t.get("crit") is not None and temp >= temp_t["crit"]:
            breaches[f"{name}::temp"] = ("crit", temp)
        elif temp_t.get("warn") is not None and temp >= temp_t["warn"]:
            breaches[f"{name}::temp"] = ("warn", temp)

        # Capacity (only if reported)
        if cap > 0:
            if cap_t.get("crit") is not None and cap >= cap_t["crit"]:
                breaches[f"{name}::capacity"] = ("crit", cap)
            elif cap_t.get("warn") is not None and cap >= cap_t["warn"]:
                breaches[f"{name}::capacity"] = ("warn", cap)

    open_alerts: list[Alert] = (
        session.query(Alert)
        .filter(Alert.server == DISK_SERVER, Alert.cleared_at.is_(None))
        .all()
    )
    open_by_sensor: dict[str, Alert] = {a.sensor_name: a for a in open_alerts}

    now = datetime.now(timezone.utc)

    for sensor_name, (level, value) in breaches.items():
        existing = open_by_sensor.get(sensor_name)
        if existing is None:
            session.add(Alert(
                server=DISK_SERVER,
                sensor_name=sensor_name,
                level=level,
                value=value,
                fired_at=now,
            ))
            log.warning("Disk alert OPENED: %s %s=%.1f", level.upper(), sensor_name, value)
            send_event("alert.opened", server=DISK_SERVER, sensor=sensor_name, level=level, value=value)
        elif existing.level != level:
            existing.level = level
            existing.value = value
            log.warning("Disk alert UPDATED: %s %s=%.1f", level.upper(), sensor_name, value)
            send_event("alert.updated", server=DISK_SERVER, sensor=sensor_name, level=level, value=value)

    for sensor_name, alert in open_by_sensor.items():
        if sensor_name not in breaches:
            alert.cleared_at = now
            log.info("Disk alert CLEARED: %s", sensor_name)
            send_event("alert.cleared", server=DISK_SERVER, sensor=sensor_name, level="info", value=alert.value)

    session.commit()


def get_active_alerts(session: Session) -> list[dict]:
    """Return all uncleared alerts as a list of dicts."""
    alerts = (
        session.query(Alert)
        .filter(Alert.cleared_at.is_(None))
        .order_by(Alert.fired_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "server": a.server,
            "sensor_name": a.sensor_name,
            "level": a.level,
            "value": a.value,
            "fired_at": a.fired_at.isoformat(),
        }
        for a in alerts
    ]
