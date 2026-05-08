"""REST API blueprint. All endpoints return JSON; errors as {"error": "..."}."""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..alerts import get_active_alerts
from ..config import FAN_PRESETS, SERVERS
from ..fan_control import _save_fan_state, get_fan_state, is_auto_mode, set_fan_mode
from ..ipmi import get_power_status, get_sel_events, get_sensor_data, set_fan_zone, set_power
from ..models import Alert, FanControlLog, PowerEvent, SensorReading
from ..notifications import send_event

log = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")


def _db_session():
    engine = create_engine(
        current_app.config["DATABASE_URL"],
        connect_args={"check_same_thread": False},
    )
    return Session(engine)


def _server_or_404(server_id: str):
    cfg = SERVERS.get(server_id)
    if cfg is None:
        return None, jsonify({"error": f"Unknown server: {server_id}"}), 404
    return cfg, None, None


def _latest_cpu_temp(server_id: str) -> float:
    """Best-effort: get most recent CPU temp reading from DB for the audit log."""
    try:
        with _db_session() as session:
            row = (
                session.query(SensorReading)
                .filter(
                    SensorReading.server == server_id,
                    SensorReading.sensor_type == "temp",
                    SensorReading.sensor_name.ilike("%cpu%"),
                )
                .order_by(SensorReading.timestamp.desc())
                .first()
            )
            return row.value if row else 0.0
    except Exception:
        return 0.0


def _log_fan_change(server_id: str, zone: int, target: int, prev: int, label: str) -> None:
    """Record a manual fan adjustment in fan_control_log."""
    try:
        with _db_session() as session:
            session.add(FanControlLog(
                server=server_id,
                zone=zone,
                source_temp=_latest_cpu_temp(server_id),
                source_label=label,
                target_duty=target,
                prev_duty=prev,
            ))
            session.commit()
    except Exception as exc:
        log.warning("Failed to write fan_control_log entry: %s", exc)


@api.get("/health")
def health():
    return jsonify({
        "ok": True,
        "servers": {sid: {"name": c["name"], "host": c["host"], "board": c["board"]} for sid, c in SERVERS.items()},
    })


@api.get("/servers")
def list_servers():
    return jsonify({
        sid: {"name": c["name"], "host": c["host"], "board": c["board"]}
        for sid, c in SERVERS.items()
    })


@api.get("/sensors/<server_id>")
def get_sensors(server_id: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code
    try:
        data = get_sensor_data(cfg)
    except Exception as exc:
        log.error("get_sensor_data failed for %s: %s", server_id, exc)
        return jsonify({"error": str(exc)}), 502

    try:
        power = get_power_status(cfg)
    except Exception as exc:
        log.warning("get_power_status failed for %s: %s", server_id, exc)
        power = "unknown"

    return jsonify({"server": server_id, "power": power, "sensors": data})


@api.get("/history/<server_id>/<path:sensor_name>")
def get_history(server_id: str, sensor_name: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code

    try:
        hours = int(request.args.get("hours", 24))
    except ValueError:
        return jsonify({"error": "hours must be an integer"}), 400
    hours = max(1, min(hours, 720))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with _db_session() as session:
        rows = (
            session.query(SensorReading)
            .filter(
                SensorReading.server == server_id,
                SensorReading.sensor_name == sensor_name,
                SensorReading.timestamp >= cutoff,
            )
            .order_by(SensorReading.timestamp.asc())
            .all()
        )

    return jsonify({
        "server": server_id,
        "sensor_name": sensor_name,
        "hours": hours,
        "data": [
            {
                "timestamp": r.timestamp.isoformat(),
                "value": r.value,
                "unit": r.unit,
                "status": r.status,
            }
            for r in rows
        ],
    })


@api.get("/alerts")
def list_alerts():
    with _db_session() as session:
        alerts = get_active_alerts(session)
    return jsonify(alerts)


@api.post("/power/<server_id>")
def power_action(server_id: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code

    confirm = request.headers.get("X-Confirm", "").lower()
    if confirm != "yes":
        return jsonify({"error": "Missing or invalid X-Confirm: yes header"}), 400

    body = request.get_json(silent=True) or {}
    action = body.get("action", "").lower()
    valid_actions = {"on", "off", "cycle", "reset"}
    if action not in valid_actions:
        return jsonify({"error": f"action must be one of: {sorted(valid_actions)}"}), 400

    try:
        set_power(cfg, action)
    except Exception as exc:
        log.error("set_power %s on %s failed: %s", action, server_id, exc)
        with _db_session() as session:
            session.add(PowerEvent(server=server_id, action=action, success=False))
            session.commit()
        send_event("power.failed", server=server_id, sensor=action, level="crit",
                   message=f"Power {action} on {server_id} FAILED: {exc}")
        return jsonify({"error": str(exc)}), 502

    with _db_session() as session:
        session.add(PowerEvent(server=server_id, action=action, success=True))
        session.commit()

    send_event("power.action", server=server_id, sensor=action, level="warn",
               message=f"Power {action.upper()} sent to {server_id}")
    return jsonify({"server": server_id, "action": action, "success": True})


@api.route("/fans/<server_id>", methods=["GET", "POST"])
def fan_control(server_id: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code

    if request.method == "GET":
        state = get_fan_state()
        state["mode"] = "auto" if is_auto_mode() else "manual"
        return jsonify({"server": server_id, **state})

    body = request.get_json(silent=True) or {}
    preset = body.get("preset")
    zone = body.get("zone")
    duty = body.get("duty")

    if preset is not None:
        if preset not in FAN_PRESETS:
            return jsonify({"error": f"Unknown preset {preset!r}; valid: {list(FAN_PRESETS)}"}), 400
        settings = FAN_PRESETS[preset]
        if preset == "auto":
            set_fan_mode("auto")
            _log_fan_change(server_id, zone=-1, target=-1, prev=-1, label=f"manual_preset:auto")
            return jsonify({"server": server_id, "preset": "auto", "mode": "dynamic"})
        set_fan_mode("manual")
        prev_state = get_fan_state()
        try:
            set_fan_zone(cfg, 0, settings["zone0"])
            if cfg.get("board", "X11").upper() == "X11":
                set_fan_zone(cfg, 1, settings["zone1"])
        except Exception as exc:
            log.error("Fan preset %s on %s failed: %s", preset, server_id, exc)
            return jsonify({"error": str(exc)}), 502
        # Log manual changes to fan_control_log so users see history
        _log_fan_change(server_id, zone=0,
                        target=settings["zone0"],
                        prev=prev_state.get(f"{server_id}_zone0", 0),
                        label=f"manual_preset:{preset}")
        if cfg.get("board", "X11").upper() == "X11":
            _log_fan_change(server_id, zone=1,
                            target=settings["zone1"],
                            prev=prev_state.get(f"{server_id}_zone1", 0),
                            label=f"manual_preset:{preset}")
        _save_fan_state(**{f"{server_id}_zone0": settings["zone0"], f"{server_id}_zone1": settings["zone1"]})
        return jsonify({"server": server_id, "preset": preset, "settings": settings})

    if zone is not None and duty is not None:
        try:
            zone_int = int(zone)
            duty_int = int(duty)
        except (TypeError, ValueError):
            return jsonify({"error": "zone and duty must be integers"}), 400
        if zone_int not in (0, 1):
            return jsonify({"error": "zone must be 0 or 1"}), 400
        if not 0 <= duty_int <= 100:
            return jsonify({"error": "duty must be 0-100"}), 400

        set_fan_mode("manual")
        prev_state = get_fan_state()
        prev_duty = prev_state.get(f"{server_id}_zone{zone_int}", 0)
        try:
            set_fan_zone(cfg, zone_int, duty_int)
        except Exception as exc:
            log.error("Fan zone %d duty %d on %s failed: %s", zone_int, duty_int, server_id, exc)
            return jsonify({"error": str(exc)}), 502
        _save_fan_state(**{f"{server_id}_zone{zone_int}": duty_int})
        _log_fan_change(server_id, zone=zone_int, target=duty_int, prev=prev_duty,
                        label="manual_zone")
        return jsonify({"server": server_id, "zone": zone_int, "duty": duty_int})

    return jsonify({"error": "Provide either 'preset' or both 'zone' and 'duty'"}), 400


@api.get("/fans/<server_id>/log")
def fan_log(server_id: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code
    try:
        count = int(request.args.get("count", 20))
        count = max(1, min(count, 200))
    except ValueError:
        return jsonify({"error": "count must be an integer"}), 400

    with _db_session() as session:
        rows = (
            session.query(FanControlLog)
            .filter(FanControlLog.server == server_id)
            .order_by(FanControlLog.timestamp.desc())
            .limit(count)
            .all()
        )

    return jsonify({
        "server": server_id,
        "log": [
            {
                "timestamp": r.timestamp.isoformat(),
                "zone": r.zone,
                "source_temp": r.source_temp,
                "source_label": r.source_label,
                "target_duty": r.target_duty,
                "prev_duty": r.prev_duty,
            }
            for r in rows
        ],
    })


@api.get("/events/<server_id>")
def sel_events(server_id: str):
    cfg, err, code = _server_or_404(server_id)
    if err:
        return err, code

    try:
        count = int(request.args.get("count", 50))
        count = max(1, min(count, 200))
    except ValueError:
        return jsonify({"error": "count must be an integer"}), 400

    try:
        events = get_sel_events(cfg, count)
    except Exception as exc:
        log.error("get_sel_events failed for %s: %s", server_id, exc)
        return jsonify({"error": str(exc)}), 502

    return jsonify({"server": server_id, "events": events})
