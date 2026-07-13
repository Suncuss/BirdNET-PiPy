"""Durable model-service startup diagnostics shared with the API container."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_startup_failure(
    path: str | Path,
    *,
    model_type: str,
    error: Exception,
) -> dict[str, str | int]:
    """Atomically persist a startup failure before the model process exits."""
    status_path = Path(path)
    payload: dict[str, str | int] = {
        "schema_version": 1,
        "state": "startup_failed",
        "model_type": model_type,
        "error_type": type(error).__name__,
        "message": str(error),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = Path(f"{status_path}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj)
        file_obj.flush()
        os.fsync(file_obj.fileno())
    os.replace(temporary_path, status_path)
    return payload


def clear_startup_failure(path: str | Path) -> None:
    """Remove a stale startup failure after the model loads successfully."""
    status_path = Path(path)
    for candidate in (status_path, Path(f"{status_path}.tmp")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def read_startup_failure(path: str | Path) -> dict[str, Any] | None:
    """Return a validated startup failure payload, or None if unavailable."""
    try:
        with Path(path).open(encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except (OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    required_strings = ("state", "model_type", "error_type", "message", "timestamp")
    if payload.get("schema_version") != 1 or any(
        not isinstance(payload.get(field), str) or not payload[field].strip()
        for field in required_strings
    ):
        return None
    if payload["state"] != "startup_failed":
        return None
    return payload
