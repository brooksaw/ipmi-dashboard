"""Background poller — collects sensor readings every POLL_INTERVAL seconds."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from .alerts import evaluate_alerts, evaluate_disk_alerts
from .config import HISTORY_RETENTION_DAYS, POLL_INTERVAL, SERVERS
from .disks import ENABLED as DISKS_ENABLED, get_disks
from .fan_control import apply_fan_control, is_auto_mode
from .ipmi import get_sensor_data
from .models import Base, DiskReading, FanControlLog, SensorReading

log = logging.getLogger(__name__)

_stop_event = threading.Event()


def _flatten_readings(server: str, sensor_data: dict) -> list[dict]:
    flat = []
    for sensor_type, readings in sensor_data.items():
        for r in readings:
            flat.append({
                "server": server,
                "sensor_type": sensor_type,
                "name": r["name"],
                "value": r["value"],
                "unit": r["unit"],
                "status": r["status"],
            })
    return flat


def _poll_once(db_url: str) -> None:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        fan_logs: list[tuple[str, dict]] = []

        for server_id, server_cfg in SERVERS.items():
            try:
                sensor_data = get_sensor_data(server_cfg)
            except Exception as exc:
                log.error("Failed to poll %s: %s", server_id, exc)
                continue

            flat = _flatten_readings(server_id, sensor_data)
            for r in flat:
                session.add(SensorReading(
                    server=r["server"],
                    timestamp=now,
                    sensor_type=r["sensor_type"],
                    sensor_name=r["name"],
                    value=r["value"],
                    unit=r["unit"],
                    status=r["status"],
                ))
            session.flush()

            try:
                evaluate_alerts(server_id, flat, session)
            except Exception as exc:
                log.error("Alert evaluation failed for %s: %s", server_id, exc)

            if is_auto_mode():
                try:
                    cfg_with_id = {**server_cfg, "id": server_id}
                    logs = apply_fan_control(cfg_with_id, sensor_data)
                    for fl in logs:
                        fan_logs.append((server_id, fl))
                except Exception as exc:
                    log.error("Fan control failed for %s: %s", server_id, exc)

        for server_id, fl in fan_logs:
            session.add(FanControlLog(
                timestamp=now,
                server=server_id,
                zone=fl["zone"],
                source_temp=fl["source_temp"],
                source_label=fl["source_label"],
                target_duty=fl["target_duty"],
                prev_duty=fl["prev_duty"],
            ))

        # ---- Disk monitoring (optional plugin) ------------------------------
        if DISKS_ENABLED:
            try:
                disks = get_disks()
                for d in disks:
                    session.add(DiskReading(
                        disk_name=d["disk_name"],
                        disk_type=d["disk_type"],
                        temp=d["temp"],
                        capacity_pct=d["capacity_pct"],
                        health=d["health"],
                        spun_up=d.get("spun_up"),
                        timestamp=now,
                    ))
                if disks:
                    try:
                        evaluate_disk_alerts(disks, session)
                    except Exception as exc:
                        log.error("Disk alert evaluation failed: %s", exc)
            except Exception as exc:
                log.error("Disk poll failed: %s", exc)

        session.commit()

        cutoff = now - timedelta(days=HISTORY_RETENTION_DAYS)
        for Model in (SensorReading, FanControlLog, DiskReading):
            try:
                session.execute(delete(Model).where(Model.timestamp < cutoff))
            except Exception:
                pass
        session.commit()


def _poller_loop(db_url: str) -> None:
    log.info("Poller started — interval %ds, servers: %s", POLL_INTERVAL, list(SERVERS))
    while not _stop_event.is_set():
        try:
            _poll_once(db_url)
        except Exception as exc:
            log.exception("Unexpected error in poll cycle: %s", exc)
        _stop_event.wait(timeout=POLL_INTERVAL)
    log.info("Poller stopped")


def start_poller(db_url: str) -> threading.Thread:
    _stop_event.clear()
    thread = threading.Thread(
        target=_poller_loop,
        args=(db_url,),
        daemon=True,
        name="ipmi-poller",
    )
    thread.start()
    return thread


def stop_poller() -> None:
    _stop_event.set()


def init_db(db_url: str) -> None:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    log.info("Database initialised at %s", db_url)
