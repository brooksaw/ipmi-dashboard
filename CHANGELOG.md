# Changelog

All notable changes to this project will be documented here.

## v2.2.0 — Settings UI

### Added
- **Settings modal** behind a gear icon in the topbar. Six tabs:
  - **Servers** — add / edit / delete BMCs with **Test Connection** before save
    (runs `ipmitool mc info` against the proposed credentials).
  - **Disks** — toggle Unraid disk monitoring, switch source between local file
    mount and SSH, with **Test Source** to validate before save.
  - **Alerts** — tune all 8 thresholds (CPU warn/crit, inlet warn, fan min,
    disk temp warn/crit, disk capacity warn/crit). **Hot-reload — no restart.**
  - **Notifications** — webhook URL + format dropdown (generic / Discord /
    Slack / ntfy) with **Test Webhook**. Per-event mute toggles for
    `alert.opened` / `alert.updated` / `alert.cleared` / `power.action` /
    `power.failed`.
  - **Display** — poll interval, history retention. Web port shown read-only.
  - **About** — version, build SHA, repo links, license, active config
    snapshot.
- **Settings store** — `app/settings_store.py` — JSON-backed, thread-safe,
  atomic writes, hot-reload helpers, secret masking with sentinel round-trip
  (so the UI can resave without re-typing passwords).
- **Settings REST API** — under `/api/settings`:
  - `GET /api/settings` — full state with secrets masked
  - `PATCH /api/settings` — partial deep-merge update
  - `DELETE /api/settings/<dotted.path>` — clear a single setting back to env/default
  - `POST /api/settings/reload` — re-read settings.json from disk
  - `GET /api/settings/restart-required` — pending list of paths needing restart
  - `POST /api/settings/test/server` — probe a BMC with proposed creds
  - `POST /api/settings/test/disks` — probe an Unraid disks.ini source
  - `POST /api/settings/test/webhook` — fire a one-shot test webhook
- **Pending-restart tracking** — settings_store records which RESTART_REQUIRED
  paths have changed since the container started. The modal header shows a
  "Restart needed" pill so users know when their save needs a docker restart
  vs takes effect immediately.
- **Layered config precedence** — settings.json (UI-managed) overrides env
  vars overrides built-in defaults. Settings keys for `servers`, `web_port`,
  `poll_interval`, `history_retention_days`, `disks.*` and `disks.ssh.*` are
  flagged RESTART_REQUIRED. Threshold settings (`alerts.*`) and webhook
  settings (`notifications.*`) hot-reload.
- **`APP_VERSION` and `APP_REVISION` env vars** — Dockerfile sets these from
  the `VERSION` / `REVISION` build args so the About tab can display the
  running version.

### Changed
- `app/notifications.py` refactored — body builder now takes an explicit
  `fmt` arg so `send_test()` can override the saved format.
- `app/disks.py` — `_fetch_local()` and `_fetch_via_ssh()` take their config
  as args; new `test_source()` helper calls them with proposed config without
  persisting.
- `app/ipmi.py` — new `test_connection()` helper for the BMC probe endpoint.
- `app/config.py` — `POLL_INTERVAL`, `HISTORY_RETENTION_DAYS`, `WEB_PORT` all
  read through `settings_store.get_int()` (settings.json -> env -> default).
- Dockerfile description expanded to mention the Settings UI.
- README — new "What's new" section, Settings UI bullet, hot-reload note.

### Internal
- 113 unit + Flask-test-client integration tests across the new code paths.
- No new runtime dependencies; same Python 3.12-slim base, same wheels.

---

## v2.1.1 — settings store backend

### Added
- `app/settings_store.py` — JSON-backed runtime config foundation (no UI yet).
- `app/alerts.py::_live_thresholds()` — reads thresholds fresh every poll
  cycle so settings.json edits take effect without restart.
- `app/notifications.py` — webhook URL + format read fresh on every send.
- `docs/screenshots/` directory + capture guide.

---

## v2.1.0 — Disk monitoring (Unraid)

### Added
- Unraid `disks.ini` parser (`app/disks.py`) — local file mount or SSH source.
- Per-disk: name, type, temp, capacity %, SMART health (PASS/WARN/FAIL),
  spin state where reported.
- Disk-temp + disk-capacity threshold alerts.
- Storage card on the dashboard with a tile-grid view.
- API endpoints `/api/disks` and `/api/disks/history/<name>`.

---

## v2.0.6 — OCI image labels

OCI standard labels (`org.opencontainers.image.*`) baked at build time so
Unraid's Docker UI shows the version + GHCR offers update detection.

## v2.0.5 — Chart Y-axis hints

Per-sensor-type Y-axis hints in `static/js/charts.js` so RPM jitter on a
1600-RPM fan doesn't auto-zoom into a wild oscillation.

## v2.0.4 — App icon

1254×1254 PNG icon for Unraid's Docker UI.

## v2.0.3 — CA structure

Restructure for Unraid Community Applications submission. Adds
`templates/ipmi-dashboard.xml` at the canonical CA-template path.

## v2.0.2 — Unraid managed-app template

Adds `net.unraid.docker.managed=dockerman` and related labels so the
container shows as a managed app (no "3rd Party" badge), with Autostart and
Edit support. GHCR auto-publish workflow lands.

## v2.0.1 — Fan command fallback + manual fan log + webhooks

- X11-style fan command tried first, X10 legacy on fallback (handles X10SRi
  boards that accept the X11 syntax).
- Manual fan adjustments logged alongside auto-curve adjustments.
- Webhook notifications for `alert.opened` / `alert.updated` / `alert.cleared`
  / `power.action` / `power.failed`.

## v2.0.0 — Full rewrite

Multi-server Flask web UI for Supermicro BMCs. Replaces the earlier
Windows-only Python script with a Docker-deployable web app:
- 6h sensor history with auto-prune
- Alert lifecycle (open/update/clear)
- Fan curve with hysteresis
- SEL log viewer
- Power control (on/off/cycle/reset, X-Confirm gated)
