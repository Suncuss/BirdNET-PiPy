"""Runtime settings utilities with lightweight cache and change classification."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from config.settings import USER_SETTINGS_PATH, SettingsUnreadable, load_user_settings
from core.native_lock import native_lock

logger = logging.getLogger(__name__)

# Native lock: taken from request greenlets AND from the DB-lane worker
# (cache builders call load_user_settings) — a patched lock loses wakeups
# across that boundary (see core/native_lock.py). Guards only the cache
# check/assignments; file parsing and validation (which can log) run
# outside it, because nothing that can log
# or block may run under a native lock.
_settings_lock = native_lock()
_cached_settings: dict[str, Any] | None = None
_cached_mtime = None
_cached_path = None
_file_seen = False
_INVALIDATED = object()
# Bumped by invalidate_runtime_settings_cache(); a reload that started before
# an invalidation must not publish over it (its mtime could coarsely equal the
# new file's, which would pin stale data past the very race invalidation
# exists to catch).
_settings_generation = 0


def _safe_mtime(path: str):
    """Identity of a settings file, including atomic replacement at equal mtime."""
    try:
        stat = os.stat(path)
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None


def _load_cached_settings(force_reload: bool = False, *, fallback=True) -> dict[str, Any]:
    """Publish only stable reads; fallback serves the last good snapshot when
    the file is unreadable. Parsing and logging stay outside the native lock.
    """
    global _cached_settings, _cached_mtime, _cached_path, _file_seen
    with _settings_lock:
        if _cached_path != USER_SETTINGS_PATH:
            _cached_settings = None
            _cached_mtime = None
            _cached_path = USER_SETTINGS_PATH
            _file_seen = False
    for _ in range(3):
        with _settings_lock:
            generation = _settings_generation
            previous = _cached_settings
        try:
            before = _safe_mtime(USER_SETTINGS_PATH)
            with _settings_lock:
                if not force_reload and previous is not None and _cached_mtime == before:
                    return previous
            if before is None and _file_seen:
                raise SettingsUnreadable("Saved settings file is missing")
            fresh = load_user_settings(strict=True, persist_migrations=False)
            after = _safe_mtime(USER_SETTINGS_PATH)
        except (OSError, ValueError, TypeError):
            if previous is not None and fallback:
                return previous
            raise
        if before != after:
            continue
        with _settings_lock:
            if _settings_generation == generation:
                _cached_settings = fresh
                _cached_mtime = after
                _file_seen = _file_seen or after is not None
            return fresh
    if previous is not None and fallback:
        return previous
    raise SettingsUnreadable("Settings changed during reading; please retry")


def get_runtime_settings(force_reload: bool = False) -> dict[str, Any]:
    """An independent snapshot of the settings in force.

    Never raises once a document has loaded: an unreadable file keeps the
    last good snapshot. Raises SettingsUnreadable only when nothing has ever
    loaded, which stops a starting process loudly rather than on defaults.
    """
    return copy.deepcopy(_load_cached_settings(force_reload))


def read_saved_settings(force_reload: bool = False) -> dict[str, Any]:
    """An independent snapshot of what is on disk right now.

    For writes and status: raises SettingsUnreadable instead of serving a
    remembered document, so a broken file is reported and never overwritten.
    """
    return copy.deepcopy(_load_cached_settings(force_reload, fallback=False))


def get_runtime_setting(path: str, default: Any = None) -> Any:
    """Read one setting by dotted path without get_runtime_settings' deep copy.

    For hot per-request/per-file paths (e.g. the anonymous access flag checked
    on every media fetch) where deep-copying the whole settings dict per read
    is measurable on a Pi. Returns the cached object itself for container
    values — treat the result as read-only.
    """
    value: Any = _load_cached_settings()
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def resolve_source_label(source_id: str, fallback: str = '') -> str:
    """Look up human-readable label for a source ID from runtime settings."""
    try:
        settings = get_runtime_settings()
        for source in settings.get('audio', {}).get('sources', []):
            if source.get('id') == source_id:
                return source.get('label', fallback)
    except Exception:
        logger.debug("Failed to resolve source label", extra={'source_id': source_id})
    return fallback


def invalidate_runtime_settings_cache() -> None:
    """Force the next read to reload from disk."""
    global _cached_mtime, _settings_generation
    with _settings_lock:
        _cached_mtime = _INVALIDATED
        _settings_generation += 1


def deep_merge_settings(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Deep merge updates into base settings and return the merged dict."""
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_settings(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _flatten_leaf_paths(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict into dotted leaf-path map."""
    if not isinstance(data, dict):
        return {prefix: data} if prefix else {}

    flattened: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(_flatten_leaf_paths(value, path))
        else:
            flattened[path] = value
    return flattened


def get_setting_differences(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return sorted dotted leaf paths whose values changed."""
    old_flat = _flatten_leaf_paths(old)
    new_flat = _flatten_leaf_paths(new)
    all_paths = set(old_flat.keys()) | set(new_flat.keys())
    changed = [path for path in all_paths if old_flat.get(path) != new_flat.get(path)]
    return sorted(changed)


def _sources_only_labels_changed(
    old_settings: dict[str, Any], new_settings: dict[str, Any]
) -> bool:
    """Check if audio sources differ only by their label fields."""
    old_sources = old_settings.get("audio", {}).get("sources", [])
    new_sources = new_settings.get("audio", {}).get("sources", [])

    if len(old_sources) != len(new_sources):
        return False

    old_by_id = {s.get("id"): s for s in old_sources}
    new_by_id = {s.get("id"): s for s in new_sources}

    if set(old_by_id) != set(new_by_id):
        return False

    for sid in old_by_id:
        old_no_label = {k: v for k, v in old_by_id[sid].items() if k != "label"}
        new_no_label = {k: v for k, v in new_by_id[sid].items() if k != "label"}
        if old_no_label != new_no_label:
            return False

    return True


def classify_setting_changes(
    changed_paths: list[str],
    old_settings: dict[str, Any] | None = None,
    new_settings: dict[str, Any] | None = None,
) -> dict[str, list[str] | bool]:
    """Classify changed setting paths by apply strategy.

    Categories:
    - hot_reload_paths: read live at the next request, clip, event or cycle
    - component_restarts: in-process component restart/rebind needed
    - full_restart_paths: requires full service restart

    When old_settings and new_settings are provided, source label-only
    changes are classified as hot_reload_paths instead of requiring a restart.
    """
    full_restart_exact = {"model.type"}
    component_prefixes = ("audio.sources",)
    component_exact = {"audio.recording_length"}

    sources_label_only = (
        old_settings is not None
        and new_settings is not None
        and _sources_only_labels_changed(old_settings, new_settings)
    )

    full_restart_paths: list[str] = []
    component_restarts: list[str] = []
    hot_reload_paths: list[str] = []

    for path in changed_paths:
        if path in full_restart_exact:
            full_restart_paths.append(path)
            continue
        if path.startswith("audio.sources") and sources_label_only:
            hot_reload_paths.append(path)
            continue
        if path in component_exact or path.startswith(component_prefixes):
            component_restarts.append(path)
            continue
        hot_reload_paths.append(path)

    return {
        "hot_reload_paths": sorted(hot_reload_paths),
        "component_restarts": sorted(component_restarts),
        "full_restart_paths": sorted(full_restart_paths),
        "full_restart_required": bool(full_restart_paths),
    }
