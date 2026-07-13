"""Shared integrity primitives for bundled model artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ModelAssetError(RuntimeError):
    """Base error for invalid or incompatible model assets."""


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """Expected identity of one immutable release artifact."""

    filename: str
    size_bytes: int
    sha256: str


ManifestT = TypeVar("ManifestT")


def require_string(
    value: object,
    field: str,
    *,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> str:
    """Require a non-empty string manifest field."""
    if not isinstance(value, str) or not value.strip():
        raise error_type(
            f"Manifest field '{field}' must be a non-empty string"
        )
    return value


def require_int(
    value: object,
    field: str,
    *,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> int:
    """Require an integer manifest field, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"Manifest field '{field}' must be an integer")
    return value


def require_number(
    value: object,
    field: str,
    *,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> float:
    """Require a finite numeric manifest field."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"Manifest field '{field}' must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise error_type(f"Manifest field '{field}' must be finite")
    return result


def load_json_manifest(
    path: str | Path,
    parser: Callable[[dict[str, Any]], ManifestT],
    *,
    description: str,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> ManifestT:
    """Read a JSON object and apply a release-specific manifest parser."""
    manifest_path = Path(path)
    try:
        with manifest_path.open(encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        if not isinstance(data, dict):
            raise TypeError("top-level JSON value must be an object")
        return parser(data)
    except error_type:
        raise
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise error_type(
            f"Invalid {description} manifest '{manifest_path}': {exc}"
        ) from exc
    except OSError as exc:
        raise error_type(
            f"Unable to read {description} manifest '{manifest_path}': {exc}"
        ) from exc


def parse_artifact_metadata(
    value: object,
    field: str,
    *,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> ArtifactMetadata:
    """Parse and validate one artifact object from a JSON manifest."""
    if not isinstance(value, dict):
        raise error_type(f"Manifest field '{field}' must be an object")

    filename = value.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise error_type(
            f"Manifest field '{field}.filename' must be a non-empty string"
        )
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise error_type(
            f"Manifest field '{field}.filename' must contain only a filename"
        )

    size_bytes = value.get("size_bytes")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
    ):
        raise error_type(
            f"Manifest field '{field}.size_bytes' must be a positive integer"
        )

    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise error_type(f"Invalid SHA-256 in manifest field '{field}.sha256'")

    return ArtifactMetadata(
        filename=filename,
        size_bytes=size_bytes,
        sha256=sha256,
    )


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest for a file without loading it all into RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact(
    path: str | Path,
    expected: ArtifactMetadata,
    *,
    description: str,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> None:
    """Require a file to match its manifest filename, size, and digest."""
    artifact_path = Path(path)
    if artifact_path.name != expected.filename:
        raise error_type(
            f"Expected {description} '{expected.filename}', got '{artifact_path.name}'"
        )

    try:
        actual_size = artifact_path.stat().st_size
    except OSError as exc:
        raise error_type(f"Unable to read {description} '{artifact_path}': {exc}") from exc
    if actual_size != expected.size_bytes:
        raise error_type(
            f"{description.capitalize()} size mismatch for '{artifact_path.name}': "
            f"expected {expected.size_bytes}, got {actual_size}"
        )

    try:
        actual_sha256 = sha256_file(artifact_path)
    except OSError as exc:
        raise error_type(f"Unable to read {description} '{artifact_path}': {exc}") from exc
    if actual_sha256 != expected.sha256:
        raise error_type(
            f"{description.capitalize()} checksum mismatch for '{artifact_path.name}': "
            f"expected {expected.sha256}, got {actual_sha256}"
        )


def first_duplicate(values: list[str]) -> str | None:
    """Return the first repeated string while preserving input order."""
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def has_wrong_static_width(shape: list[Any], expected_width: int) -> bool:
    """Reject a wrong static width while allowing symbolic ONNX dimensions."""
    if len(shape) != 2:
        return True
    width = shape[1]
    return isinstance(width, Integral) and int(width) != expected_width


def validate_probability_result(
    result: list[Any],
    *,
    expected_shape: tuple[int, ...],
    output_range: tuple[float, float],
    description: str,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> np.ndarray:
    """Validate a single ONNX result as finite, bounded probabilities."""
    if len(result) != 1:
        raise error_type(
            f"{description} test returned an unexpected output count"
        )

    probabilities = np.asarray(result[0])
    if probabilities.shape != expected_shape:
        raise error_type(
            f"{description} output shape mismatch: expected {expected_shape}, "
            f"got {probabilities.shape}"
        )
    if not np.isfinite(probabilities).all():
        raise error_type(f"{description} output contains non-finite values")
    output_min, output_max = output_range
    if np.any(probabilities < output_min) or np.any(probabilities > output_max):
        raise error_type(
            f"{description} output is outside probability range "
            f"[{output_min}, {output_max}]"
        )
    return probabilities


def load_validated_onnx_session(
    model_path: str | Path,
    validator: Callable[[Any], None],
    *,
    description: str,
    error_type: type[ModelAssetError] = ModelAssetError,
) -> Any:
    """Create a CPU ONNX session and normalize its validation errors."""
    try:
        import onnxruntime as ort
    except Exception as exc:
        raise error_type(f"Unable to import ONNX Runtime: {exc}") from exc

    try:
        session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        validator(session)
    except error_type:
        raise
    except Exception as exc:
        raise error_type(
            f"Unable to initialize {description} ONNX session: {exc}"
        ) from exc
    return session


def node_description(node: Any) -> str:
    """Return a compact ONNX node description for diagnostics."""
    return f"name={node.name!r}, type={node.type!r}, shape={node.shape!r}"
