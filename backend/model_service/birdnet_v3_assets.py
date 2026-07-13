"""Validation, provenance, and legacy cleanup for bundled BirdNET V3.1."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from .label_utils import parse_v3_labels
from .model_assets import (
    ArtifactMetadata,
    ModelAssetError,
    first_duplicate,
    has_wrong_static_width,
    load_json_manifest,
    load_validated_onnx_session,
    node_description,
    parse_artifact_metadata,
    require_int,
    require_number,
    require_string,
    validate_artifact,
    validate_probability_result,
)

BIRDNET_V3_VERSION = "3.1"
BIRDNET_V3_SAMPLE_RATE = 32000
BIRDNET_V3_INPUT_DTYPE = "tensor(float)"
BIRDNET_V3_OUTPUT_DTYPE = "tensor(float)"
BIRDNET_V3_OUTPUT_ACTIVATION = "sigmoid"
BIRDNET_V3_OUTPUT_RANGE = (0.0, 1.0)
BIRDNET_V3_LICENSE = "CC-BY-SA-4.0"
LEGACY_BIRDNET_V3_FILENAME = "BirdNET_V3.0_Global_11K_FP32.onnx"
_SMOKE_SECONDS = 3


class BirdNetV3AssetError(ModelAssetError):
    """Raised when the bundled BirdNET V3.1 release is invalid."""


@dataclass(frozen=True, slots=True)
class BirdNetV3Manifest:
    """Validated metadata for the bundled acoustic release."""

    version: str
    repository_url: str
    release_url: str
    doi: str
    upstream_name: str
    license_spdx: str
    license_url: str
    model: ArtifactMetadata
    labels: ArtifactMetadata
    terms: ArtifactMetadata
    sample_rate_hz: int
    input_name: str
    input_dtype: str
    input_rank: int
    prediction_name: str
    prediction_dtype: str
    output_classes: int
    output_activation: str
    output_range: tuple[float, float]
    precision: str


@dataclass(slots=True)
class LoadedBirdNetV3:
    """A validated ONNX session paired with its labels and release metadata."""

    session: Any
    labels: list[tuple[str, str]]
    manifest: BirdNetV3Manifest


_require_string = partial(require_string, error_type=BirdNetV3AssetError)
_require_int = partial(require_int, error_type=BirdNetV3AssetError)
_require_number = partial(require_number, error_type=BirdNetV3AssetError)


def _parse_birdnet_v3_manifest(data: dict[str, Any]) -> BirdNetV3Manifest:
    schema_version = _require_int(data["schema_version"], "schema_version")
    if schema_version != 1:
        raise BirdNetV3AssetError(
            f"Unsupported BirdNET V3 manifest schema: {schema_version}"
        )

    source = data["source"]
    license_data = data["license"]
    artifacts = data["artifacts"]
    contract = data["contract"]
    input_data = contract["input"]
    predictions = contract["predictions"]
    output_range_data = predictions["range"]
    if not isinstance(output_range_data, list) or len(output_range_data) != 2:
        raise BirdNetV3AssetError(
            "Manifest field 'contract.predictions.range' must contain two numbers"
        )

    return BirdNetV3Manifest(
        version=_require_string(data["version"], "version"),
        repository_url=_require_string(source["repository"], "source.repository"),
        release_url=_require_string(source["release"], "source.release"),
        doi=_require_string(source["doi"], "source.doi"),
        upstream_name=_require_string(
            source["upstream_name"], "source.upstream_name"
        ),
        license_spdx=_require_string(license_data["spdx"], "license.spdx"),
        license_url=_require_string(license_data["url"], "license.url"),
        model=parse_artifact_metadata(
            artifacts["model"],
            "artifacts.model",
            error_type=BirdNetV3AssetError,
        ),
        labels=parse_artifact_metadata(
            artifacts["labels"],
            "artifacts.labels",
            error_type=BirdNetV3AssetError,
        ),
        terms=parse_artifact_metadata(
            artifacts["terms"],
            "artifacts.terms",
            error_type=BirdNetV3AssetError,
        ),
        sample_rate_hz=_require_int(
            contract["sample_rate_hz"], "contract.sample_rate_hz"
        ),
        input_name=_require_string(input_data["name"], "contract.input.name"),
        input_dtype=_require_string(input_data["dtype"], "contract.input.dtype"),
        input_rank=_require_int(input_data["rank"], "contract.input.rank"),
        prediction_name=_require_string(
            predictions["name"], "contract.predictions.name"
        ),
        prediction_dtype=_require_string(
            predictions["dtype"], "contract.predictions.dtype"
        ),
        output_classes=_require_int(
            predictions["classes"], "contract.predictions.classes"
        ),
        output_activation=_require_string(
            predictions["activation"], "contract.predictions.activation"
        ),
        output_range=(
            _require_number(
                output_range_data[0], "contract.predictions.range[0]"
            ),
            _require_number(
                output_range_data[1], "contract.predictions.range[1]"
            ),
        ),
        precision=_require_string(data["precision"], "precision"),
    )


def load_birdnet_v3_manifest(path: str | Path) -> BirdNetV3Manifest:
    """Load and structurally validate the bundled V3.1 manifest."""
    manifest = load_json_manifest(
        path,
        _parse_birdnet_v3_manifest,
        description="BirdNET V3",
        error_type=BirdNetV3AssetError,
    )

    if manifest.version != BIRDNET_V3_VERSION:
        raise BirdNetV3AssetError(
            f"BirdNET V3 manifest version must be '{BIRDNET_V3_VERSION}'"
        )
    if manifest.sample_rate_hz != BIRDNET_V3_SAMPLE_RATE:
        raise BirdNetV3AssetError(
            f"BirdNET V3 sample rate must be {BIRDNET_V3_SAMPLE_RATE} Hz"
        )
    if manifest.input_dtype != BIRDNET_V3_INPUT_DTYPE:
        raise BirdNetV3AssetError(
            f"BirdNET V3 input dtype must be '{BIRDNET_V3_INPUT_DTYPE}'"
        )
    if manifest.input_rank != 2:
        raise BirdNetV3AssetError("BirdNET V3 input rank must be 2")
    if manifest.prediction_dtype != BIRDNET_V3_OUTPUT_DTYPE:
        raise BirdNetV3AssetError(
            f"BirdNET V3 prediction dtype must be '{BIRDNET_V3_OUTPUT_DTYPE}'"
        )
    if manifest.output_classes <= 0:
        raise BirdNetV3AssetError("BirdNET V3 output class count must be positive")
    if manifest.output_activation != BIRDNET_V3_OUTPUT_ACTIVATION:
        raise BirdNetV3AssetError(
            f"BirdNET V3 output activation must be '{BIRDNET_V3_OUTPUT_ACTIVATION}'"
        )
    if manifest.output_range != BIRDNET_V3_OUTPUT_RANGE:
        raise BirdNetV3AssetError(
            f"BirdNET V3 output range must be {BIRDNET_V3_OUTPUT_RANGE}"
        )
    if manifest.license_spdx != BIRDNET_V3_LICENSE:
        raise BirdNetV3AssetError(
            f"BirdNET V3 model license must be '{BIRDNET_V3_LICENSE}'"
        )

    return manifest


def validate_birdnet_v3_files(
    manifest: BirdNetV3Manifest,
    model_path: str | Path,
    labels_path: str | Path,
    manifest_path: str | Path,
    *,
    validate_documentation: bool = False,
) -> list[tuple[str, str]]:
    """Validate the release artifacts and return labels in model output order."""
    validate_artifact(
        model_path,
        manifest.model,
        description="BirdNET V3 model artifact",
        error_type=BirdNetV3AssetError,
    )
    validate_artifact(
        labels_path,
        manifest.labels,
        description="BirdNET V3 labels artifact",
        error_type=BirdNetV3AssetError,
    )
    if validate_documentation:
        terms_path = Path(manifest_path).parent / manifest.terms.filename
        validate_artifact(
            terms_path,
            manifest.terms,
            description="BirdNET V3 terms artifact",
            error_type=BirdNetV3AssetError,
        )

    try:
        labels = parse_v3_labels(str(labels_path))
    except (OSError, UnicodeError, ValueError, AttributeError) as exc:
        raise BirdNetV3AssetError(
            f"Unable to parse BirdNET V3 labels '{labels_path}': {exc}"
        ) from exc
    if len(labels) != manifest.output_classes:
        raise BirdNetV3AssetError(
            "BirdNET V3 label count does not match the prediction width: "
            f"expected {manifest.output_classes}, got {len(labels)}"
        )

    duplicate_label = first_duplicate([f"{sci}_{common}" for sci, common in labels])
    if duplicate_label is not None:
        raise BirdNetV3AssetError(f"Duplicate BirdNET V3 label: {duplicate_label}")
    return labels


def build_birdnet_v3_smoke_input(sample_rate: int) -> np.ndarray:
    """Build deterministic, non-silent FP32 audio for contract validation."""
    time_axis = np.arange(sample_rate * _SMOKE_SECONDS, dtype=np.float32) / sample_rate
    audio = (
        0.04 * np.sin(2.0 * np.pi * 880.0 * time_axis)
        + 0.02 * np.sin(2.0 * np.pi * 1760.0 * time_axis)
    )
    return audio.astype(np.float32, copy=False)[np.newaxis, :]


def validate_birdnet_v3_session(
    session: Any, manifest: BirdNetV3Manifest
) -> None:
    """Validate names, dtypes, shapes, and probability behavior."""
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1:
        raise BirdNetV3AssetError(
            f"BirdNET V3 must expose exactly one input tensor, got {len(inputs)}"
        )

    input_node = inputs[0]
    if input_node.name != manifest.input_name:
        raise BirdNetV3AssetError(
            f"BirdNET V3 input name mismatch: expected '{manifest.input_name}', "
            f"got {node_description(input_node)}"
        )
    if input_node.type != manifest.input_dtype:
        raise BirdNetV3AssetError(
            f"BirdNET V3 input dtype mismatch: expected '{manifest.input_dtype}', "
            f"got {node_description(input_node)}"
        )
    if len(input_node.shape) != manifest.input_rank:
        raise BirdNetV3AssetError(
            f"BirdNET V3 input rank mismatch: expected {manifest.input_rank}, "
            f"got {node_description(input_node)}"
        )

    prediction_nodes = [
        output for output in outputs if output.name == manifest.prediction_name
    ]
    if len(prediction_nodes) != 1:
        available = [output.name for output in outputs]
        raise BirdNetV3AssetError(
            f"BirdNET V3 must expose one '{manifest.prediction_name}' output; "
            f"available outputs: {available}"
        )
    prediction_node = prediction_nodes[0]
    if prediction_node.type != manifest.prediction_dtype:
        raise BirdNetV3AssetError(
            "BirdNET V3 prediction dtype mismatch: expected "
            f"'{manifest.prediction_dtype}', got {node_description(prediction_node)}"
        )
    if has_wrong_static_width(prediction_node.shape, manifest.output_classes):
        raise BirdNetV3AssetError(
            "BirdNET V3 prediction shape mismatch: expected [batch, "
            f"{manifest.output_classes}], got {prediction_node.shape}"
        )

    smoke_input = build_birdnet_v3_smoke_input(manifest.sample_rate_hz)
    try:
        result = session.run(
            [manifest.prediction_name], {manifest.input_name: smoke_input}
        )
    except Exception as exc:
        raise BirdNetV3AssetError(
            f"BirdNET V3 smoke inference failed: {exc}"
        ) from exc
    validate_probability_result(
        result,
        expected_shape=(1, manifest.output_classes),
        output_range=manifest.output_range,
        description="BirdNET V3 smoke",
        error_type=BirdNetV3AssetError,
    )


def load_validated_birdnet_v3(
    model_path: str | Path,
    labels_path: str | Path,
    manifest_path: str | Path,
    *,
    validate_documentation: bool = False,
) -> LoadedBirdNetV3:
    """Load BirdNET V3.1 only after validating its immutable release bundle."""
    manifest = load_birdnet_v3_manifest(manifest_path)
    labels = validate_birdnet_v3_files(
        manifest,
        model_path,
        labels_path,
        manifest_path,
        validate_documentation=validate_documentation,
    )
    session = load_validated_onnx_session(
        model_path,
        lambda candidate: validate_birdnet_v3_session(candidate, manifest),
        description="BirdNET V3",
        error_type=BirdNetV3AssetError,
    )
    return LoadedBirdNetV3(session=session, labels=labels, manifest=manifest)


def remove_legacy_birdnet_v3_files(
    legacy_model_path: str | Path,
) -> tuple[Path, ...]:
    """Delete the obsolete V3.0 model and old downloader residue by exact path."""
    legacy_path = Path(legacy_model_path)
    if legacy_path.name != LEGACY_BIRDNET_V3_FILENAME:
        raise BirdNetV3AssetError(
            "Refusing legacy cleanup for unexpected filename "
            f"'{legacy_path.name}'"
        )

    removed: list[Path] = []
    for candidate in (legacy_path, Path(f"{legacy_path}.tmp")):
        try:
            candidate.unlink()
            removed.append(candidate)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BirdNetV3AssetError(
                f"Unable to remove legacy BirdNET V3 file '{candidate}': {exc}"
            ) from exc
    try:
        legacy_path.parent.rmdir()
    except OSError:
        pass
    return tuple(removed)


def main() -> None:
    """Validate the complete bundled release during image builds."""
    bundle_dir = Path(__file__).resolve().parent / "models" / "v3.1"
    loaded = load_validated_birdnet_v3(
        bundle_dir / "BirdNET+_V3.0-preview3.1_Global_11K_FP16_pruned.onnx",
        bundle_dir / "BirdNET+_V3.0-preview3.1_Global_11K_Labels.csv",
        bundle_dir / "manifest.json",
        validate_documentation=True,
    )
    print(
        f"Validated BirdNET V{loaded.manifest.version}: "
        f"{loaded.manifest.output_classes} outputs, {loaded.manifest.precision}"
    )


if __name__ == "__main__":
    main()
