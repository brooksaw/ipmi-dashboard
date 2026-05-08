"""
Alert evaluation and lifecycle management.

evaluate_alerts() compares the latest SensorReadings against ALERT_THRESHOLDS,
opens new Alert rows when a threshold is breached, and clears them when the
reading returns to normal.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .config import ALERT_THRESHOLDS
from .models import Alert, SensorReading

log = logging.getLogger(__name__)


def _threshold_level(sensor_type: str, sensor_name: str, value: float) -> str | None:
    """Return 'crit', 'warn', or None based on thresholds."""
    name_lower = sensor_name.lower()

    # CPU temperature
    if sensor_type == "temp" and any(k in name_lower for k in ("cpu", "processor")):
        cpu = ALERT_THRESHOLDS["cpu"]
        if cpu.get("crit") is not None and value >= cpu["crit"]:
            return "crit"
        if cpu.get("warn") is not None and value >= cpu["warn"]:
            return "warn"

    # Inlet temperature
    elif sensor_type == "temp" and "inlet" in name_lower:
        inlet = ALERT_THRESHOLDS["inlet"]
        if inlet.get("warn") is not None and value >= inlet["warn"]:
            return "warn"

    # Fan RPM — low is bad
    elif sensor_type == "fan":
        fan = ALERT_THRESHOLDS["fan"]
        if fan.get("min") is not None and value < fan["min"]:
            return "crit"

    return None


def evaluate_alerts(server: str, readings: list[dict], session: Session) -> None:
    """Compare *readings* from a poll cycle against thresholds.

    Opens new Alert rows for new breaches; sets cleared_at for resolved ones.
    """
    breaches: dict[str, tuple[str, float]] = {}  # sensor_name -> (level, value)

    for r in readings:
        level = _threshold_level(r["sensor_type"], r["name"], r["value"])
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
        elif existing.level != level:
            # Upgrade/downgrade in place (update level and value)
            existing.level = level
            existing.value = value
            log.warning("Alert UPDATED: %s %s %s=%.1f", server, level.upper(), sensor_name, value)

    # Clear alerts no longer in breach
    for sensor_name, alert in open_by_sensor.items():
        if sensor_name not in breaches:
            alert.cleared_at = now
            log.info("Alert CLEARED: %s %s", server, sensor_name)

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
