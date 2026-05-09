"""Settings REST API blueprint.

Backs the Settings modal in the dashboard UI. All endpoints return JSON;
errors come back as ``{"error": "..."}`` with a non-2xx status.

Endpoints (all under ``/api/settings``):

    GET    /                          full settings tree (secrets masked)
    PATCH  /                          partial update (deep-merge)
    DELETE /<path:dotted_key>         clear a single setting back to env/default
    POST   /reload                    re-read settings.json from disk
    GET    /restart-required          paths whose change needs a container restart
    POST   /test/server               probe a BMC with proposed creds
    POST   /test/webhook              send a one-shot test webhook

Sensitive paths (notifications.webhook_url, disks.ssh.key, servers.*.password)
are returned as ``"***SET***"`` on GET. PATCH bodies that round-trip the
sentinel back are stripped of those leaves so the real secret is preserved.

No auth — the dashboard runs LAN-only. Token auth is on the v3.1 roadmap.
"""

import logging
import os

from flask import Blueprint, jsonify, request

from .. import settings_store
from ..config import HISTORY_RETENTION_DAYS, POLL_INTERVAL, SERVERS, SERVERS_SOURCE, WEB_PORT
from ..disks import ENABLED as DISKS_ENABLED, SOURCE as DISKS_SOURCE, test_source as test_disk_source
from ..ipmi import test_connection
from ..notifications import send_test as send_test_webhook

log = logging.getLogger(__name__)
settings_api = Blueprint("settings_api", __name__, url_prefix="/api/settings")


def _envelope() -> dict:
    """Standard response envelope for state-returning endpoints."""
    return {
        "settings": settings_store.mask_secrets(settings_store.all_settings()),
        "revision": settings_store.revision(),
        "pending_restart": settings_store.pending_restart(),
        "secret_sentinel": settings_store.SECRET_SENTINEL,
        # Live runtime info — what's actually loaded into SERVERS, not what's
        # in settings.json. Lets the UI distinguish "unsaved settings" from
        # "currently running" and warn when a YAML/env mount is masking changes.
        "runtime": {
            "servers_source": SERVERS_SOURCE,
            "servers_running": {
                sid: {"name": cfg["name"], "host": cfg["host"], "board": cfg["board"]}
                for sid, cfg in SERVERS.items()
            },
            "disks_enabled": DISKS_ENABLED,
            "disks_source": DISKS_SOURCE,
            "poll_interval": POLL_INTERVAL,
            "history_retention_days": HISTORY_RETENTION_DAYS,
            "web_port": WEB_PORT,
            # Build metadata baked into the image at CI time. "dev" when
            # running from source / docker-compose without build args.
            "version":  os.environ.get("APP_VERSION", "dev"),
            "revision": os.environ.get("APP_REVISION", "unknown"),
        },
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@settings_api.get("")
@settings_api.get("/")
def get_settings():
    return jsonify(_envelope())


@settings_api.get("/restart-required")
def restart_required():
    return jsonify({
        "pending_restart": settings_store.pending_restart(),
        "revision": settings_store.revision(),
    })


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

@settings_api.patch("")
@settings_api.patch("/")
def patch_settings():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Body must be a JSON object"}), 400
    if not body:
        # Empty patch is a no-op — return current state without bumping rev.
        return jsonify(_envelope())

    cleaned = settings_store.unmask_into(body)
    try:
        settings_store.patch(cleaned)
    except OSError as exc:
        return jsonify({"error": f"Disk write failed: {exc}"}), 500
    except Exception as exc:
        log.error("settings PATCH failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify(_envelope())


@settings_api.delete("/<path:dotted_key>")
def delete_setting(dotted_key: str):
    if not dotted_key:
        return jsonify({"error": "Path is required"}), 400
    try:
        existed = settings_store.delete(dotted_key)
    except OSError as exc:
        return jsonify({"error": f"Disk write failed: {exc}"}), 500

    return jsonify({"deleted": existed, "path": dotted_key, **_envelope()})


@settings_api.post("/reload")
def reload_settings():
    """Force a fresh read of settings.json from disk. Useful when the file
    was edited out-of-band."""
    try:
        settings_store.reload()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(_envelope())


# ---------------------------------------------------------------------------
# Test endpoints
# ---------------------------------------------------------------------------

@settings_api.post("/test/server")
def test_server():
    """Probe a BMC with the supplied credentials. Body fields:
        host:     required, IPv4/hostname of the BMC
        user:     required, IPMI username
        password: required, IPMI password
        timeout:  optional, seconds (default 5, max 20)

    Returns ``{ok: true, summary: "..."}`` on success, ``{ok: false, error}``
    on failure. Always 200 — the test result is in the body, not the HTTP code.
    """
    body = request.get_json(silent=True) or {}
    host = (body.get("host") or "").strip()
    user = (body.get("user") or "").strip()
    password = body.get("password") or ""

    if not host or not user:
        return jsonify({"ok": False, "error": "host and user are required"}), 400

    try:
        timeout = int(body.get("timeout") or 5)
        timeout = max(1, min(timeout, 20))
    except (TypeError, ValueError):
        timeout = 5

    ok, detail = test_connection(host, user, password, timeout=timeout)
    return jsonify({"ok": ok, "summary" if ok else "error": detail})


@settings_api.post("/test/disks")
def test_disks():
    """Probe a proposed disk-source config. Body fields:
        source:     required, "local" or "ssh"
        local_path: required when source=local
        ssh:        required when source=ssh; object with host, user, key, timeout

    Returns ``{ok: true, detail, disks_found}`` on success, ``{ok: false, error}``
    on failure. Always 200.
    """
    body = request.get_json(silent=True) or {}
    source = (body.get("source") or "local").lower()
    if source not in ("local", "ssh"):
        return jsonify({"ok": False, "error": f"unknown source: {source}"}), 400

    local_path = body.get("local_path") or "/host/disks.ini"
    ssh = body.get("ssh") or {}

    # If the SSH key field arrived as the SECRET_SENTINEL, swap in the saved value
    # so users can hit Test without retyping a path they didn't change.
    ssh_key = ssh.get("key") or ""
    if ssh_key == settings_store.SECRET_SENTINEL:
        ssh_key = settings_store.get_str("disks.ssh.key", "DISKS_SSH_KEY", "/ssh_key")
    elif not ssh_key:
        ssh_key = "/ssh_key"

    try:
        timeout = int(ssh.get("timeout") or 8)
        timeout = max(1, min(timeout, 60))
    except (TypeError, ValueError):
        timeout = 8

    ok, detail, count = test_disk_source(
        source,
        local_path=local_path,
        ssh_host=ssh.get("host") or "",
        ssh_user=ssh.get("user") or "root",
        ssh_key=ssh_key,
        ssh_timeout=timeout,
    )
    return jsonify({
        "ok": ok,
        ("detail" if ok else "error"): detail,
        "disks_found": count,
    })


@settings_api.post("/test/webhook")
def test_webhook():
    """Send a one-shot test webhook with the supplied URL + format. Body:
        url:    required
        format: optional, one of "generic"|"discord"|"slack"|"ntfy"
        timeout: optional, seconds (default 5, max 30)

    Returns ``{ok: true, detail}`` or ``{ok: false, error}``. Always 200.
    """
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    fmt = (body.get("format") or "generic").strip().lower()

    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    if fmt not in ("generic", "discord", "slack", "ntfy"):
        return jsonify({"ok": False, "error": f"unknown format: {fmt}"}), 400

    try:
        timeout = int(body.get("timeout") or 5)
        timeout = max(1, min(timeout, 30))
    except (TypeError, ValueError):
        timeout = 5

    ok, detail = send_test_webhook(url, fmt, timeout=timeout)
    return jsonify({"ok": ok, "detail" if ok else "error": detail})
