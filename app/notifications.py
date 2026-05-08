"""Webhook notifications for events users may want to know about.

Set NOTIFY_WEBHOOK_URL to a URL that accepts JSON POSTs (Discord webhook,
Slack incoming webhook, ntfy.sh, Mattermost, custom endpoint, etc.).

Optional NOTIFY_WEBHOOK_FORMAT controls the JSON body shape:
  - "generic" (default) — flat JSON with event, server, sensor, level, value, message
  - "discord"           — Discord webhook with embeds
  - "slack"             — Slack incoming webhook with blocks
  - "ntfy"              — ntfy.sh format (X-Title header + plain body)

All sends are best-effort and never raise.
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)

WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()
WEBHOOK_FORMAT = os.environ.get("NOTIFY_WEBHOOK_FORMAT", "generic").lower()
WEBHOOK_TIMEOUT = int(os.environ.get("NOTIFY_WEBHOOK_TIMEOUT", "5"))


def _format_message(event: str, server: str, sensor: str, level: str, value: float) -> str:
    parts = [f"[{server}]"]
    if sensor:
        parts.append(sensor)
    if value is not None:
        parts.append(f"= {value}")
    if level:
        parts.append(f"({level.upper()})")
    parts.append(f"— {event}")
    return " ".join(parts)


def _build_body(event: str, server: str, sensor: str = "", level: str = "",
                value: float = None, message: str = "") -> dict:
    msg = message or _format_message(event, server, sensor, level, value or 0)
    payload = {
        "event": event,
        "server": server,
        "sensor": sensor,
        "level": level,
        "value": value,
        "message": msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if WEBHOOK_FORMAT == "discord":
        color = {"crit": 0xCF222E, "warn": 0x9A6700}.get(level, 0x0969DA)
        return {
            "embeds": [{
                "title": f"IPMI Dashboard — {event}",
                "description": msg,
                "color": color,
                "fields": [
                    {"name": "Server", "value": server or "-", "inline": True},
                    {"name": "Sensor", "value": sensor or "-", "inline": True},
                    {"name": "Level", "value": level or "info", "inline": True},
                ],
                "timestamp": payload["timestamp"],
            }]
        }

    if WEBHOOK_FORMAT == "slack":
        emoji = {"crit": ":rotating_light:", "warn": ":warning:"}.get(level, ":information_source:")
        return {"text": f"{emoji} {msg}"}

    if WEBHOOK_FORMAT == "ntfy":
        return {"_ntfy_body": msg, "_ntfy_title": f"IPMI {event}"}

    return payload


def send_event(event: str, server: str = "", sensor: str = "", level: str = "",
               value: float = None, message: str = "") -> None:
    """Fire a notification webhook for the given event. Never raises."""
    if not WEBHOOK_URL:
        return

    body = _build_body(event, server, sensor, level, value, message)

    try:
        if WEBHOOK_FORMAT == "ntfy":
            data = body.pop("_ntfy_body", "").encode()
            headers = {"X-Title": body.pop("_ntfy_title", "IPMI")}
            req = urllib.request.Request(WEBHOOK_URL, data=data, headers=headers, method="POST")
        else:
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                WEBHOOK_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            log.debug("Webhook sent: %s -> HTTP %d", event, resp.status)
    except Exception as exc:
        log.warning("Webhook send failed (%s): %s", event, exc)
