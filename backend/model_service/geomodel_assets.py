"""Validation and provenance handling for the bundled BirdNET Geomodel."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from .label_utils import parse_geomodel_labels
from .model_assets import (
    ArtifactMetadata,
    ModelAssetError,
    first_duplicate,
    has_wrong_static_width,
    load_json_manifest,
    load_validated_onnx_session,
    parse_artifact_metadata,
    require_int,
    require_number,
    require_string,
    validate_artifact,
    validate_probability_result,
)

GEOMODEL_INPUT_COLUMNS = ("latitude", "longitude", "week")
GEOMODEL_TENSOR_DTYPE = "tensor(float)"
GEOMODEL_OUTPUT_ACTIVATION = "sigmoid"
GEOMODEL_OUTPUT_RANGE = (0.0, 1.0)


class GeoModelAssetError(ModelAssetError):
    """Raised when the bundled geomodel files do not match their manifest."""


@dataclass(frozen=True, slots=True)
class GeoModelManifest:
    """Validated metadata describing one model/labels release pair."""

    version: str
    repository_url: str
    release_url: str
    model: ArtifactMetadata
    labels: ArtifactMetadata
    license: ArtifactMetadata
    input_name: str
    input_dtype: str
    input_columns: tuple[str, ...]
    output_name: str
    output_dtype: str
    output_classes: int
    output_activation: str
    output_range: tuple[float, float]


@dataclass(slots=True)
class LoadedGeoModel:
    """A loaded ONNX session paired with its validated labels and metadata."""

    session: Any
    labels: list[tuple[str, str, str]]
    manifest: GeoModelManifest


_require_string = partial(require_string, error_type=GeoModelAssetError)
_require_int = partial(require_int, error_type=GeoModelAssetError)
_require_number = partial(require_number, error_type=GeoModelAssetError)


def _parse_geomodel_manifest(data: dict[str, Any]) -> GeoModelManifest:
    schema_version = _require_int(data["schema_version"], "schema_version")
    if schema_version != 1:
        raise GeoModelAssetError(
            f"Unsupported geomodel manifest schema: {schema_version}"
        )

    source = data["source"]
    artifacts = data["artifacts"]
    contract = data["contract"]
    input_data = contract["input"]
    output_data = contract["output"]
    input_columns_data = input_data["columns"]
    output_range_data = output_data["range"]

    if not isinstance(input_columns_data, list):
        raise GeoModelAssetError(
            "Manifest field 'contract.input.columns' must be a list"
        )
    if not isinstance(output_range_data, list) or len(output_range_data) != 2:
        raise GeoModelAssetError(
            "Manifest field 'contract.output.range' must contain two numbers"
        )

    return GeoModelManifest(
        version=_require_string(data["version"], "version"),
        repository_url=_require_string(
            source["repository"], "source.repository"
        ),
        release_url=_require_string(source["release"], "source.release"),
        model=parse_artifact_metadata(
            artifacts["model"],
            "artifacts.model",
            error_type=GeoModelAssetError,
        ),
        labels=parse_artifact_metadata(
            artifacts["labels"],
            "artifacts.labels",
            error_type=GeoModelAssetError,
        ),
        license=parse_artifact_metadata(
            artifacts["license"],
            "artifacts.license",
            error_type=GeoModelAssetError,
        ),
        input_name=_require_string(input_data["name"], "contract.input.name"),
        input_dtype=_require_string(input_data["dtype"], "contract.input.dtype"),
        input_columns=tuple(
            _require_string(value, f"contract.input.columns[{index}]")
            for index, value in enumerate(input_columns_data)
        ),
        output_name=_require_string(output_data["name"], "contract.output.name"),
        output_dtype=_require_string(
            output_data["dtype"], "contract.output.dtype"
        ),
        output_classes=_require_int(
            output_data["classes"], "contract.output.classes"
        ),
        output_activation=_require_string(
            output_data["activation"], "contract.output.activation"
        ),
        output_range=(
            _require_number(output_range_data[0], "contract.output.range[0]"),
            _require_number(output_range_data[1], "contract.output.range[1]"),
        ),
    )


def load_geomodel_manifest(path: str | Path) -> GeoModelManifest:
    """Load and structurally validate a geomodel manifest."""
    manifest = load_json_manifest(
        path,
        _parse_geomodel_manifest,
        description="geomodel",
        error_type=GeoModelAssetError,
    )

    if manifest.input_columns != GEOMODEL_INPUT_COLUMNS:
        raise GeoModelAssetError(
            "Geomodel input columns must be "
            f"{GEOMODEL_INPUT_COLUMNS}, got {manifest.input_columns}"
        )
    if manifest.input_dtype != GEOMODEL_TENSOR_DTYPE:
        raise GeoModelAssetError(
            f"Geomodel input dtype must be '{GEOMODEL_TENSOR_DTYPE}'"
        )
    if manifest.output_dtype != GEOMODEL_TENSOR_DTYPE:
        raise GeoModelAssetError(
            f"Geomodel output dtype must be '{GEOMODEL_TENSOR_DTYPE}'"
        )
    if manifest.output_classes <= 0:
        raise GeoModelAssetError("Geomodel output class count must be positive")
    if manifest.output_activation != GEOMODEL_OUTPUT_ACTIVATION:
        raise GeoModelAssetError(
            f"Geomodel output activation must be '{GEOMODEL_OUTPUT_ACTIVATION}'"
        )
    if manifest.output_range != GEOMODEL_OUTPUT_RANGE:
        raise GeoModelAssetError(
            f"Geomodel output range must be {GEOMODEL_OUTPUT_RANGE}"
        )
    return manifest


def validate_geomodel_files(
    manifest: GeoModelManifest,
    model_path: str | Path,
    labels_path: str | Path,
    manifest_path: str | Path,
) -> list[tuple[str, str, str]]:
    """Validate artifact identity and return labels in model output order."""
    model_file = Path(model_path)
    labels_file = Path(labels_path)
    manifest_file = Path(manifest_path)
    license_file = manifest_file.parent / manifest.license.filename

    validate_artifact(
        model_file,
        manifest.model,
        description="geomodel model artifact",
        error_type=GeoModelAssetError,
    )
    validate_artifact(
        labels_file,
        manifest.labels,
        description="geomodel labels artifact",
        error_type=GeoModelAssetError,
    )
    validate_artifact(
        license_file,
        manifest.license,
        description="geomodel license artifact",
        error_type=GeoModelAssetError,
    )

    try:
        labels = parse_geomodel_labels(str(labels_file))
    except (OSError, UnicodeError) as exc:
        raise GeoModelAssetError(
            f"Unable to parse geomodel labels '{labels_file}': {exc}"
        ) from exc
    if len(labels) != manifest.output_classes:
        raise GeoModelAssetError(
            "Geomodel label count does not match the declared output width: "
            f"expected {manifest.output_classes}, got {len(labels)}"
        )

    duplicate_code = first_duplicate([code for code, _sci, _com in labels])
    if duplicate_code is not None:
        raise GeoModelAssetError(f"Duplicate geomodel species code: {duplicate_code}")

    duplicate_sci = first_duplicate([sci for _code, sci, _com in labels])
    if duplicate_sci is not None:
        raise GeoModelAssetError(f"Duplicate geomodel scientific name: {duplicate_sci}")

    return labels


def build_geomodel_input(
    latitude: float, longitude: float, week: int
) -> np.ndarray:
    """Build one input row in the canonical manifest-validated column order."""
    return np.array([[latitude, longitude, week]], dtype=np.float32)


def validate_geomodel_session(session: Any, manifest: GeoModelManifest) -> None:
    """Validate the ONNX tensor contract and run one probability smoke test."""
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise GeoModelAssetError(
            "Geomodel must expose exactly one input and one output tensor"
        )

    input_node = inputs[0]
    output_node = outputs[0]
    expected_input_width = len(manifest.input_columns)

    if input_node.name != manifest.input_name:
        raise GeoModelAssetError(
            f"Geomodel input name mismatch: expected '{manifest.input_name}', "
            f"got '{input_node.name}'"
        )
    if input_node.type != manifest.input_dtype:
        raise GeoModelAssetError(
            f"Geomodel input dtype mismatch: expected '{manifest.input_dtype}', "
            f"got '{input_node.type}'"
        )
    if has_wrong_static_width(input_node.shape, expected_input_width):
        raise GeoModelAssetError(
            "Geomodel input shape mismatch: expected [batch, "
            f"{expected_input_width}], got {input_node.shape}"
        )

    if output_node.name != manifest.output_name:
        raise GeoModelAssetError(
            f"Geomodel output name mismatch: expected '{manifest.output_name}', "
            f"got '{output_node.name}'"
        )
    if output_node.type != manifest.output_dtype:
        raise GeoModelAssetError(
            f"Geomodel output dtype mismatch: expected '{manifest.output_dtype}', "
            f"got '{output_node.type}'"
        )
    if has_wrong_static_width(output_node.shape, manifest.output_classes):
        raise GeoModelAssetError(
            "Geomodel output shape mismatch: expected [batch, "
            f"{manifest.output_classes}], got {output_node.shape}"
        )

    smoke_input = build_geomodel_input(42.0, -76.0, 23)
    try:
        result = session.run(
            [manifest.output_name], {manifest.input_name: smoke_input}
        )
    except Exception as exc:
        raise GeoModelAssetError(f"Geomodel smoke inference failed: {exc}") from exc
    validate_probability_result(
        result,
        expected_shape=(1, manifest.output_classes),
        output_range=manifest.output_range,
        description="Geomodel smoke",
        error_type=GeoModelAssetError,
    )


def load_validated_geomodel(
    model_path: str | Path,
    labels_path: str | Path,
    manifest_path: str | Path,
) -> LoadedGeoModel:
    """Load a geomodel only after validating its release pair and ONNX contract."""
    manifest = load_geomodel_manifest(manifest_path)
    labels = validate_geomodel_files(
        manifest, model_path, labels_path, manifest_path
    )
    session = load_validated_onnx_session(
        model_path,
        lambda candidate: validate_geomodel_session(candidate, manifest),
        description="geomodel",
        error_type=GeoModelAssetError,
    )
    return LoadedGeoModel(session=session, labels=labels, manifest=manifest)


def main() -> None:
    """Validate the bundled release artifacts during image builds."""
    bundle_dir = Path(__file__).resolve().parent / "models" / "geomodel"
    loaded = load_validated_geomodel(
        bundle_dir / "geomodel_fp16.onnx",
        bundle_dir / "labels.txt",
        bundle_dir / "manifest.json",
    )
    print(
        f"Validated BirdNET Geomodel v{loaded.manifest.version}: "
        f"{loaded.manifest.output_classes} outputs"
    )


if __name__ == "__main__":
    main()
