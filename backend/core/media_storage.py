"""Media storage target resolution with optional external-drive preference.

This module keeps internal storage as the default while allowing users to
select a mounted external volume for bulky media files such as recordings,
extracted audio clips, and spectrograms. If the preferred external target is
missing or not writable, writes automatically fall back to internal storage.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from config.settings import (
    BASE_DIR,
    EXTRACTED_AUDIO_DIR,
    RECORDING_DIR,
    SPECTROGRAM_DIR,
)
from core.logging_config import get_logger
from core.runtime_config import get_runtime_settings

logger = get_logger(__name__)

MEDIA_TARGET_INTERNAL = "internal"
EXTERNAL_MEDIA_APP_DIR = "BirdNET-PiPy"
EXTERNAL_MEDIA_ROOTS = ("/external-media", "/managed-media")

_INTERNAL_MEDIA_ROOT = os.path.join(BASE_DIR, "data")


def _external_media_configured() -> bool:
    return os.getenv("BIRDNET_EXTERNAL_MEDIA_CONFIGURED", "").lower() in {
        "1", "true", "yes", "on"
    }


def _disk_usage_for_path(path: str):
    """Return usage for path, or its nearest existing parent."""
    candidate = os.path.realpath(path)
    while not os.path.exists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return shutil.disk_usage(candidate)


def _internal_target_info() -> dict[str, Any]:
    usage = _disk_usage_for_path(_INTERNAL_MEDIA_ROOT)
    return {
        "id": MEDIA_TARGET_INTERNAL,
        "label": "Internal storage (SD card)",
        "mount_path": _INTERNAL_MEDIA_ROOT,
        "writable": True,
        "available": True,
        "filesystem": None,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "source": "internal",
    }


def _iter_candidate_dirs(root: str, filesystems: dict[str, str]) -> list[str]:
    """Return the configured root and direct child mount points.

    The host still controls the visibility boundary through BIRDNET_MEDIA_PATH.
    If that path is a single drive, only the root is returned. If it is a
    parent containing several mounted drives, direct child mounts become
    individually selectable without treating ordinary folders as drives.
    """
    if not os.path.isdir(root):
        return []

    real_root = os.path.realpath(root)
    child_mounts = []
    for mount_path in filesystems:
        real_mount = os.path.realpath(mount_path)
        if os.path.dirname(real_mount) != real_root:
            continue
        if os.path.isdir(real_mount):
            child_mounts.append(real_mount)
    return child_mounts or [real_root]


def _mount_filesystems() -> dict[str, str]:
    filesystems: dict[str, str] = {}
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    filesystems[parts[1]] = parts[2]
    except OSError:
        return filesystems
    return filesystems


def _external_target_info(path: str, filesystems: dict[str, str]) -> dict[str, Any] | None:
    if not path or not os.path.isdir(path):
        return None

    real_path = os.path.realpath(path)
    if not any(
        real_path == root or real_path.startswith(root + os.sep)
        for root in EXTERNAL_MEDIA_ROOTS
    ):
        return None

    try:
        usage = shutil.disk_usage(real_path)
    except OSError:
        return None

    is_root = real_path in EXTERNAL_MEDIA_ROOTS
    return {
        "id": real_path,
        "label": (
            "BIRDSTORE " + os.path.basename(real_path)[:8]
            if os.path.dirname(real_path) == "/managed-media"
            else "Configured external storage"
            if is_root
            else os.path.basename(real_path.rstrip(os.sep))
        ),
        "mount_path": real_path,
        "writable": os.access(real_path, os.W_OK),
        "available": True,
        "filesystem": filesystems.get(real_path),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "source": "external",
    }


def get_available_media_targets() -> list[dict[str, Any]]:
    """Return internal plus mounted writable-ish external media targets."""
    filesystems = _mount_filesystems()
    seen: set[str] = set()
    targets = [_internal_target_info()]

    for root in EXTERNAL_MEDIA_ROOTS:
        if root == "/external-media" and not _external_media_configured():
            continue
        if not os.path.isdir(root):
            continue
        for candidate in _iter_candidate_dirs(root, filesystems):
            if root == "/managed-media" and candidate == root:
                continue
            info = _external_target_info(candidate, filesystems)
            if not info:
                continue
            if info["id"] in seen:
                continue
            seen.add(info["id"])
            targets.append(info)

    targets[1:] = sorted(targets[1:], key=lambda item: item["label"].lower())
    return targets


def get_preferred_media_target_id(settings: dict[str, Any] | None = None) -> str:
    settings = settings if settings is not None else get_runtime_settings()
    return settings.get("storage", {}).get("media_target", MEDIA_TARGET_INTERNAL)


def is_valid_media_target_id(target_id: Any) -> bool:
    if target_id == MEDIA_TARGET_INTERNAL:
        return True
    if not isinstance(target_id, str) or not target_id:
        return False

    real_path = os.path.realpath(target_id)
    return any(
        (real_path == root and root != "/managed-media") or os.path.dirname(real_path) == root
        for root in EXTERNAL_MEDIA_ROOTS
    )


def _target_by_id(target_id: str, targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for target in targets:
        if target["id"] == target_id:
            return target
    return None


def get_media_storage_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings if settings is not None else get_runtime_settings()
    preferred_id = get_preferred_media_target_id(settings)
    targets = get_available_media_targets()
    preferred_target = _target_by_id(preferred_id, targets)

    fallback_reason = None
    if preferred_id == MEDIA_TARGET_INTERNAL:
        effective_target = _target_by_id(MEDIA_TARGET_INTERNAL, targets)
    elif preferred_target and preferred_target.get("writable"):
        effective_target = preferred_target
    else:
        effective_target = _target_by_id(MEDIA_TARGET_INTERNAL, targets)
        fallback_reason = "missing" if preferred_target is None else "unwritable"
        if preferred_target is None and is_valid_media_target_id(preferred_id):
            preferred_target = {
                "id": preferred_id,
                "label": os.path.basename(preferred_id.rstrip(os.sep)) or preferred_id,
                "mount_path": preferred_id,
                "writable": False,
                "available": False,
                "filesystem": None,
                "free_bytes": None,
                "total_bytes": None,
                "source": "external",
            }
            targets.append(preferred_target)

    return {
        "preferred_target_id": preferred_id,
        "preferred_target": preferred_target,
        "effective_target_id": effective_target["id"] if effective_target else MEDIA_TARGET_INTERNAL,
        "effective_target": effective_target,
        "fallback_active": preferred_id != (effective_target["id"] if effective_target else MEDIA_TARGET_INTERNAL),
        "fallback_reason": fallback_reason,
        "targets": targets,
    }


def get_effective_media_root(
    settings: dict[str, Any] | None = None,
    internal_root: str | None = None,
) -> str:
    settings = settings if settings is not None else get_runtime_settings()
    if get_preferred_media_target_id(settings) == MEDIA_TARGET_INTERNAL:
        return internal_root or _INTERNAL_MEDIA_ROOT

    status = get_media_storage_status(settings)
    effective = status.get("effective_target") or _internal_target_info()
    if effective["id"] == MEDIA_TARGET_INTERNAL:
        return internal_root or _INTERNAL_MEDIA_ROOT
    return os.path.join(effective["mount_path"], EXTERNAL_MEDIA_APP_DIR)


def get_effective_storage_path(settings: dict[str, Any] | None = None) -> str:
    """Return an existing path suitable for capacity and disk-usage checks."""
    status = get_media_storage_status(settings)
    effective = status.get("effective_target") or _internal_target_info()
    return effective["mount_path"]


def ensure_effective_media_dirs(
    settings: dict[str, Any] | None = None,
    recording_dir: str | None = None,
    extracted_audio_dir: str | None = None,
    spectrogram_dir: str | None = None,
) -> None:
    for path in (
        get_effective_recording_dir(settings, recording_dir),
        get_effective_extracted_audio_dir(settings, extracted_audio_dir),
        get_effective_spectrogram_dir(settings, spectrogram_dir),
    ):
        os.makedirs(path, exist_ok=True)


def get_effective_recording_dir(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> str:
    settings = settings if settings is not None else get_runtime_settings()
    if get_preferred_media_target_id(settings) == MEDIA_TARGET_INTERNAL:
        return internal_dir or RECORDING_DIR
    return os.path.join(get_effective_media_root(settings), "audio", "recordings")


def get_effective_extracted_audio_dir(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> str:
    settings = settings if settings is not None else get_runtime_settings()
    if get_preferred_media_target_id(settings) == MEDIA_TARGET_INTERNAL:
        return internal_dir or EXTRACTED_AUDIO_DIR
    return os.path.join(get_effective_media_root(settings), "audio", "extracted_songs")


def get_effective_spectrogram_dir(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> str:
    settings = settings if settings is not None else get_runtime_settings()
    if get_preferred_media_target_id(settings) == MEDIA_TARGET_INTERNAL:
        return internal_dir or SPECTROGRAM_DIR
    return os.path.join(get_effective_media_root(settings), "spectrograms")


def _unique_existing_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _media_search_dirs(effective, internal_dir, subdir):
    paths = [effective, internal_dir]
    for target in get_available_media_targets():
        if target['id'] != MEDIA_TARGET_INTERNAL:
            candidate = os.path.join(target['mount_path'], EXTERNAL_MEDIA_APP_DIR, subdir)
            if os.path.isdir(candidate):
                paths.append(candidate)
    return _unique_existing_paths(paths)


def get_recording_scan_dirs(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> list[str]:
    internal_dir = internal_dir or RECORDING_DIR
    return _media_search_dirs(
        get_effective_recording_dir(settings, internal_dir), internal_dir, 'audio/recordings'
    )


def get_audio_search_dirs(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> list[str]:
    internal_dir = internal_dir or EXTRACTED_AUDIO_DIR
    return _media_search_dirs(
        get_effective_extracted_audio_dir(settings, internal_dir), internal_dir, 'audio/extracted_songs'
    )


def get_spectrogram_search_dirs(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> list[str]:
    internal_dir = internal_dir or SPECTROGRAM_DIR
    return _media_search_dirs(
        get_effective_spectrogram_dir(settings, internal_dir), internal_dir, 'spectrograms'
    )


def get_allowed_recording_dirs(
    settings: dict[str, Any] | None = None,
    internal_dir: str | None = None,
) -> list[str]:
    return [
        os.path.realpath(path)
        for path in get_recording_scan_dirs(settings, internal_dir)
    ]
