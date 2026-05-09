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

from . import settings_store

log = logging.getLogger(__name__)


def _webhook_url() -> str:
    return settings_store.get_str("notifications.webhook_url", "NOTIFY_WEBHOOK_URL", "").strip()


def _webhook_format() -> str:
    return settings_store.get_str("notifications.webhook_format", "NOTIFY_WEBHOOK_FORMAT", "generic").lower()


def _webhook_timeout() -> int:
    return settings_store.get_int("notifications.webhook_timeout", "NOTIFY_WEBHOOK_TIMEOUT", 5)


def _event_enabled(event_name: str) -> bool:
    """Per-event enable flag. Defaults all events on. Set to false in
    settings.json under notifications.events.<event_name>=false to mute.

    Note: event names contain dots ("alert.opened", "power.action") so we
    can't use ``settings_store.get(f"notifications.events.{event_name}")`` —
    that would split the dot-in-key as a path segment. Instead, fetch the
    events dict and do a literal lookup.
    """
    events = settings_store.get("notifications.events") or {}
    if not isinstance(events, dict):
        return True
    val = events.get(event_name)
    return False if val is False else True


# Back-compat: legacy module-level constants kept for any external imports.
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
                value: float = None, message: str = "", fmt: str | None = None) -> dict:
    """Build the webhook body for the given event in the requested format.

    `fmt` overrides the saved format (used by send_test() to test an unsaved
    config). When None, falls back to the saved setting.
    """
    msg = message or _format_message(event, server, sensor, level, value or 0)
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "event": event,
        "server": server,
        "sensor": sensor,
        "level": level,
        "value": value,
        "message": msg,
        "timestamp": timestamp,
    }

    fmt = (fmt or _webhook_format()).lower()
    if fmt == "discord":
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
                "timestamp": timestamp,
            }]
        }

    if fmt == "slack":
        emoji = {"crit": ":rotating_light:", "warn": ":warning:"}.get(level, ":information_source:")
        return {"text": f"{emoji} {msg}"}

    if fmt == "ntfy":
        return {"_ntfy_body": msg, "_ntfy_title": f"IPMI {event}"}

    return payload


def _post_webhook(url: str, fmt: str, body: dict, timeout: int) -> tuple[int, str]:
    """Low-level POST. Returns (http_status, response_text). Raises on
    network/transport failures."""
    if fmt == "ntfy":
        data = body.pop("_ntfy_body", "").encode()
        headers = {"X-Title": body.pop("_ntfy_title", "IPMI")}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    else:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(256).decode("utf-8", errors="replace")


def send_event(event: str, server: str = "", sensor: str = "", level: str = "",
               value: float = None, message: str = "") -> None:
    """Fire a notification webhook for the given event. Never raises."""
    url = _webhook_url()
    if not url:
        return

    if not _event_enabled(event):
        log.debug("Webhook event muted by settings: %s", event)
        return

    fmt = _webhook_format()
    body = _build_body(event, server, sensor, level, value, message, fmt=fmt)
    timeout = _webhook_timeout()

    try:
        status, _ = _post_webhook(url, fmt, body, timeout)
        log.debug("Webhook sent: %s -> HTTP %d", event, status)
    except Exception as exc:
        log.warning("Webhook send failed (%s): %s", event, exc)


def send_test(url: str, fmt: str = "generic", timeout: int = 5) -> tuple[bool, str]:
    """Send a one-shot test notification with the given (typically unsaved)
    URL + format. Used by the Settings UI's Test Webhook button.

    Returns:
        (True,  "HTTP 204")              on success
        (False, "URL is empty")          on missing URL
        (False, "HTTP 401: ...")         on non-2xx response
        (False, "<network error>")       on transport failure

    Never raises.
    """
    if not url:
        return False, "URL is empty"
    fmt = (fmt or "generic").lower()

    body = _build_body(
        event="test",
        server="ipmi-dashboard",
        sensor="webhook-test",
        level="info",
        value=None,
        message="Test webhook from IPMI Dashboard. If you can read this, your webhook is wired correctly.",
        fmt=fmt,
    )

    try:
        status, resp_text = _post_webhook(url, fmt, body, timeout)
    except Exception as exc:
        log.warning("Test webhook failed: %s", exc)
        return False, str(exc)

    if 200 <= status < 300:
        return True, f"HTTP {status}"
    return False, f"HTTP {status}: {resp_text[:200]}"
