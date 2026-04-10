"""Runtime settings utilities with lightweight cache and change classification."""

from __future__ import annotations

import copy
import logging
import os
import threading
from typing import Any

from config.settings import USER_SETTINGS_PATH, load_user_settings

logger = logging.getLogger(__name__)

_settings_lock = threading.Lock()
_cached_settings: dict[str, Any] | None = None
_cached_mtime: float | None = None


def _safe_mtime(path: str) -> float | None:
    """Get file mtime if the file exists."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def get_runtime_settings(force_reload: bool = False) -> dict[str, Any]:
    """Get settings with mtime-based caching.

    Returns a deep copy so callers can mutate safely.
    """
    global _cached_settings, _cached_mtime

    file_mtime = _safe_mtime(USER_SETTINGS_PATH)
    with _settings_lock:
        needs_reload = (
            force_reload
            or _cached_settings is None
            or _cached_mtime != file_mtime
        )
        if needs_reload:
            _cached_settings = load_user_settings()
            _cached_mtime = _safe_mtime(USER_SETTINGS_PATH)

        # load_user_settings() always returns a dict, but keep this guard for safety
        return copy.deepcopy(_cached_settings or {})


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
    global _cached_settings, _cached_mtime
    with _settings_lock:
        _cached_settings = None
        _cached_mtime = None


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
    - hot_applied: takes effect immediately
    - component_restarts: in-process component restart/rebind needed
    - full_restart_paths: requires full service restart

    When old_settings and new_settings are provided, source label-only
    changes are classified as hot_applied instead of requiring a restart.
    """
    full_restart_exact = {"model.type"}
    full_restart_prefixes = ("audio.sources", "audio.next_source_id")
    component_prefixes = ("audio.",)
    component_exact = {"birdweather.id", "location.configured"}

    sources_label_only = (
        old_settings is not None
        and new_settings is not None
        and _sources_only_labels_changed(old_settings, new_settings)
    )

    full_restart_paths: list[str] = []
    component_restarts: list[str] = []
    hot_applied: list[str] = []

    for path in changed_paths:
        if path in full_restart_exact:
            full_restart_paths.append(path)
            continue
        if path.startswith(full_restart_prefixes):
            # Source label-only edits are cosmetic — no restart needed
            if sources_label_only and path.startswith("audio.sources"):
                hot_applied.append(path)
                continue
            full_restart_paths.append(path)
            continue
        if path in component_exact or path.startswith(component_prefixes):
            component_restarts.append(path)
            continue
        hot_applied.append(path)

    return {
        "hot_applied": sorted(hot_applied),
        "component_restarts": sorted(component_restarts),
        "full_restart_paths": sorted(full_restart_paths),
        "full_restart_required": bool(full_restart_paths),
    }
