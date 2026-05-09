"""Settings store — JSON-backed runtime config with env fallback.

The dashboard's behavior can be configured three ways, in priority order:

  1. settings.json (written by the UI / API)
  2. Environment variables
  3. Built-in defaults

Most settings hot-reload — read latest values via `get(key, default)`. A few
(server roster, web port) require a container restart; those are tagged
RESTART_REQUIRED here so the UI can display the right hint.

Thread-safe via a single RLock; writes are atomic via temp-file + rename so
a crashed/killed container can't leave a half-written JSON.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

# Path to the settings file. Defaults to data/settings.json next to the SQLite
# DB. Override with SETTINGS_PATH env if you want it elsewhere.
SETTINGS_PATH = Path(os.environ.get("SETTINGS_PATH", "/app/data/settings.json"))

# Settings keys that need a container restart to take effect (poller closures,
# Flask app config, port bindings). Patterns are dotted paths; a path "X" also
# matches any nested path "X.Y.Z" (so "servers" covers servers.{id}.host etc).
RESTART_REQUIRED: set[str] = {
    "servers",
    "web_port",
    "poll_interval",
    "history_retention_days",
    "disks.enabled",
    "disks.source",
    "disks.local_path",
    "disks.ssh.host",
    "disks.ssh.user",
    "disks.ssh.key",
}

# Sensitive paths that should be masked when serializing settings for the API.
# Supports fnmatch globs ("servers.*.password" matches every server's password).
# Non-empty values are replaced with the SECRET_SENTINEL on output; the API
# layer treats the sentinel on input as "leave unchanged" so the UI can
# round-trip without re-entering passwords.
SECRET_SENTINEL = "***SET***"
SENSITIVE_PATHS: tuple[str, ...] = (
    "notifications.webhook_url",
    "disks.ssh.key",
    "servers.*.password",
)

# In-memory cache of the parsed settings dict. Keep behind a lock so the
# poller thread reading thresholds and the Flask thread writing don't race.
_lock = threading.RLock()
_state: dict[str, Any] = {}
_loaded = False
_revision = 0

# Paths from RESTART_REQUIRED that have been changed since this process
# started. Cleared on container restart (the module reinitializes). The UI
# polls this to decide whether to show a "Restart required" pill.
_pending_restart: set[str] = set()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _read_disk() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("settings.json unreadable, treating as empty: %s", exc)
        return {}


def _ensure_loaded() -> None:
    global _state, _loaded
    if not _loaded:
        with _lock:
            if not _loaded:
                _state = _read_disk()
                _loaded = True


def reload() -> None:
    """Force re-read from disk. Increments revision so listeners can detect."""
    global _state, _revision
    with _lock:
        _state = _read_disk()
        _revision += 1
        log.info("settings reloaded from %s (revision %d)", SETTINGS_PATH, _revision)


def revision() -> int:
    """Monotonic counter, bumped on every successful write or reload."""
    _ensure_loaded()
    return _revision


def all_settings() -> dict[str, Any]:
    """Snapshot of all stored settings. Safe to mutate the returned dict."""
    _ensure_loaded()
    with _lock:
        return json.loads(json.dumps(_state))  # deep copy


def get(path: str, default: Any = None) -> Any:
    """Look up a setting by dotted path (e.g. 'alerts.cpu.warn').

    Returns the value from settings.json if set, else default. Does NOT
    fall back to env vars — callers wanting "env-or-json" semantics should
    layer this with their own env reads (see helpers below).
    """
    _ensure_loaded()
    parts = path.split(".")
    with _lock:
        cur: Any = _state
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur


def patch(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge `updates` into the settings tree. Top-level keys are replaced
    wholesale; nested dicts are deep-merged. Lists/strings/numbers replace.

    Atomic: writes to a temp file then renames. On disk write failure the
    in-memory state is rolled back.
    """
    _ensure_loaded()
    with _lock:
        global _state, _revision
        prev = json.loads(json.dumps(_state))  # snapshot for rollback
        _deep_merge(_state, updates)
        try:
            _atomic_write(SETTINGS_PATH, json.dumps(_state, indent=2, sort_keys=True))
            _revision += 1
            log.info("settings patched (revision %d): %s", _revision, list(updates.keys()))
            _track_restart_paths(_iter_dotted_paths(updates), prev=prev, new=_state)
            return json.loads(json.dumps(_state))
        except OSError as exc:
            _state = prev
            log.error("settings write failed, rolled back: %s", exc)
            raise


def replace(new_state: dict[str, Any]) -> dict[str, Any]:
    """Wholesale replace the entire settings tree. Use with care."""
    _ensure_loaded()
    with _lock:
        global _state, _revision
        prev = json.loads(json.dumps(_state))
        _state = json.loads(json.dumps(new_state))
        try:
            _atomic_write(SETTINGS_PATH, json.dumps(_state, indent=2, sort_keys=True))
            _revision += 1
            # On full replace, every RESTART_REQUIRED key is potentially
            # changed; check each against prev to find actual diffs.
            _track_restart_paths(RESTART_REQUIRED, prev=prev, new=_state)
            return json.loads(json.dumps(_state))
        except OSError as exc:
            _state = prev
            log.error("settings replace failed, rolled back: %s", exc)
            raise


def delete(path: str) -> bool:
    """Remove a setting by dotted path. Returns True if it existed."""
    _ensure_loaded()
    parts = path.split(".")
    with _lock:
        global _revision
        prev = json.loads(json.dumps(_state))
        cur = _state
        for p in parts[:-1]:
            if not isinstance(cur, dict) or p not in cur:
                return False
            cur = cur[p]
        if not isinstance(cur, dict) or parts[-1] not in cur:
            return False
        del cur[parts[-1]]
        _atomic_write(SETTINGS_PATH, json.dumps(_state, indent=2, sort_keys=True))
        _revision += 1
        _track_restart_paths([path], prev=prev, new=_state)
        return True


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Pending-restart tracking
# ---------------------------------------------------------------------------

def _iter_dotted_paths(d: dict[str, Any], prefix: str = "") -> Iterator[str]:
    """Yield every leaf path in a nested dict as 'a.b.c'. Empty dicts yield
    their parent path so deletions still register."""
    if not d:
        if prefix:
            yield prefix
        return
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            yield from _iter_dotted_paths(v, path)
        else:
            yield path


def _path_get(d: dict[str, Any], path: str) -> Any:
    """Walk dict via dotted path. Returns None if any segment missing."""
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _track_restart_paths(touched: Iterator[str], *, prev: dict, new: dict) -> None:
    """For every touched path, if it (or an ancestor) is in RESTART_REQUIRED
    AND the value actually changed between prev and new, record it.

    Caller holds _lock.
    """
    for path in touched:
        match = _matched_restart_root(path)
        if match is None:
            continue
        if _path_get(prev, match) != _path_get(new, match):
            _pending_restart.add(match)
            log.info("Restart-required setting changed: %s", match)


def _matched_restart_root(path: str) -> str | None:
    """If `path` matches a RESTART_REQUIRED entry exactly or as a descendant,
    return that entry. Otherwise None."""
    for required in RESTART_REQUIRED:
        if path == required or path.startswith(required + "."):
            return required
    return None


def pending_restart() -> list[str]:
    """Sorted list of restart-required keys whose value differs from disk
    state at process start. Empty if nothing requires a restart."""
    _ensure_loaded()
    with _lock:
        return sorted(_pending_restart)


def clear_pending_restart() -> None:
    """Reset the pending-restart set. Called rarely — normally the set is
    cleared by the container restart itself (module reinitializes)."""
    with _lock:
        _pending_restart.clear()


# ---------------------------------------------------------------------------
# Secret masking (for serializing settings to the API)
# ---------------------------------------------------------------------------

def _path_is_sensitive(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in SENSITIVE_PATHS)


def mask_secrets(state: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied state with sensitive paths redacted.

    - Empty/falsy values stay empty (so the UI can show "not configured").
    - Non-empty values become SECRET_SENTINEL.
    - Structural keys (dicts) are walked recursively.
    """
    return _mask_recurse(json.loads(json.dumps(state)), prefix="")


def _mask_recurse(node: Any, prefix: str) -> Any:
    if isinstance(node, dict):
        return {k: _mask_recurse(v, f"{prefix}.{k}" if prefix else k) for k, v in node.items()}
    if _path_is_sensitive(prefix) and node:
        return SECRET_SENTINEL
    return node


def unmask_into(updates: dict[str, Any]) -> dict[str, Any]:
    """Strip SECRET_SENTINEL values from a partial-update payload so a PATCH
    that round-trips a masked GET doesn't overwrite the real secret with the
    sentinel. Returns a deep-copied dict with sentinel leaves removed."""
    cleaned = json.loads(json.dumps(updates))
    _strip_sentinels(cleaned, prefix="")
    return cleaned


def _strip_sentinels(node: Any, prefix: str) -> None:
    if not isinstance(node, dict):
        return
    drop = []
    for k, v in list(node.items()):
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _strip_sentinels(v, path)
            if not v:  # cleaned-out subtree, drop it
                drop.append(k)
        elif _path_is_sensitive(path) and v == SECRET_SENTINEL:
            drop.append(k)
    for k in drop:
        del node[k]


# ---------------------------------------------------------------------------
# Layered helpers — settings.json overrides env, env overrides default
# ---------------------------------------------------------------------------

def get_int(json_path: str, env_var: str, default: int) -> int:
    val = get(json_path)
    if val is not None:
        try:
            return int(val)
        except (TypeError, ValueError):
            log.warning("settings %s not an int, using env/default", json_path)
    env = os.environ.get(env_var)
    if env is not None:
        try:
            return int(env)
        except ValueError:
            log.warning("env %s not an int, using default", env_var)
    return default


def get_float(json_path: str, env_var: str, default: float) -> float:
    val = get(json_path)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            log.warning("settings %s not a float, using env/default", json_path)
    env = os.environ.get(env_var)
    if env is not None:
        try:
            return float(env)
        except ValueError:
            log.warning("env %s not a float, using default", env_var)
    return default


def get_str(json_path: str, env_var: str, default: str = "") -> str:
    val = get(json_path)
    if isinstance(val, str):
        return val
    return os.environ.get(env_var, default)


def get_bool(json_path: str, env_var: str, default: bool = False) -> bool:
    val = get(json_path)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    env = os.environ.get(env_var)
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return default
