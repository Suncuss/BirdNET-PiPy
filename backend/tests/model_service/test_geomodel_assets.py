"""Contract, provenance, and real-artifact tests for BirdNET Geomodel."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from model_service.geomodel_assets import (
    GeoModelAssetError,
    load_geomodel_manifest,
    load_validated_geomodel,
    validate_geomodel_files,
    validate_geomodel_session,
)
from model_service.label_utils import parse_geomodel_labels, parse_v3_labels
from model_service.location_filter import GeoModelFilter


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_test_bundle(tmp_path: Path, *, output_classes: int = 2):
    model_path = tmp_path / "geomodel_fp16.onnx"
    labels_path = tmp_path / "labels.txt"
    license_path = tmp_path / "MODEL_LICENSE.txt"
    manifest_path = tmp_path / "manifest.json"

    model_path.write_bytes(b"model")
    labels_path.write_text(
        "amerob\tTurdus migratorius\tAmerican Robin\n"
        "norcar\tCardinalis cardinalis\tNorthern Cardinal\n",
        encoding="utf-8",
    )
    license_path.write_text("license\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "version": "test",
        "source": {
            "repository": "https://example.test/geomodel",
            "release": "https://example.test/geomodel/releases/test",
        },
        "artifacts": {
            "model": {
                "filename": model_path.name,
                "size_bytes": model_path.stat().st_size,
                "sha256": _digest(model_path),
            },
            "labels": {
                "filename": labels_path.name,
                "size_bytes": labels_path.stat().st_size,
                "sha256": _digest(labels_path),
            },
            "license": {
                "filename": license_path.name,
                "size_bytes": license_path.stat().st_size,
                "sha256": _digest(license_path),
            },
        },
        "contract": {
            "input": {
                "name": "input",
                "dtype": "tensor(float)",
                "columns": ["latitude", "longitude", "week"],
            },
            "output": {
                "name": "probabilities",
                "dtype": "tensor(float)",
                "classes": output_classes,
                "activation": "sigmoid",
                "range": [0.0, 1.0],
            },
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return model_path, labels_path, manifest_path


class _FakeSession:
    def __init__(self, output_classes: int = 2):
        self.input_node = SimpleNamespace(
            name="input", type="tensor(float)", shape=["batch", 3]
        )
        self.output_node = SimpleNamespace(
            name="probabilities",
            type="tensor(float)",
            shape=["batch", output_classes],
        )
        self.probabilities = np.full((1, output_classes), 0.25, dtype=np.float32)

    def get_inputs(self):
        return [self.input_node]

    def get_outputs(self):
        return [self.output_node]

    def run(self, output_names, inputs):
        assert output_names == ["probabilities"]
        assert inputs["input"].shape == (1, 3)
        np.testing.assert_array_equal(
            inputs["input"][0], np.array([42.0, -76.0, 23.0], dtype=np.float32)
        )
        return [self.probabilities]


class TestGeoModelAssetValidation:
    def test_matching_release_pair_passes(self, tmp_path):
        model_path, labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)

        labels = validate_geomodel_files(
            manifest, model_path, labels_path, manifest_path
        )

        assert manifest.version == "test"
        assert len(labels) == 2
        assert labels[0][1] == "Turdus migratorius"

    def test_input_columns_must_match_runtime_order(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["contract"]["input"]["columns"] = [
            "longitude",
            "latitude",
            "week",
        ]
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(GeoModelAssetError, match="input columns"):
            load_geomodel_manifest(manifest_path)

    def test_null_string_is_rejected_instead_of_coerced(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["version"] = None
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(GeoModelAssetError, match="version.*non-empty string"):
            load_geomodel_manifest(manifest_path)

    def test_artifact_filename_must_not_escape_bundle(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["artifacts"]["labels"]["filename"] = "../labels.txt"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(GeoModelAssetError, match="only a filename"):
            load_geomodel_manifest(manifest_path)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("activation", "softmax", "output activation"),
            ("range", [-1.0, 1.0], "output range"),
        ],
    )
    def test_probability_contract_is_enforced(
        self, tmp_path, field, value, message
    ):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["contract"]["output"][field] = value
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(GeoModelAssetError, match=message):
            load_geomodel_manifest(manifest_path)

    def test_checksum_mismatch_is_rejected(self, tmp_path):
        model_path, labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)
        model_path.write_bytes(b"MODEL")  # Same size, different digest.

        with pytest.raises(GeoModelAssetError, match="checksum mismatch"):
            validate_geomodel_files(
                manifest, model_path, labels_path, manifest_path
            )

    def test_label_count_must_match_output_width(self, tmp_path):
        model_path, labels_path, manifest_path = _write_test_bundle(
            tmp_path, output_classes=3
        )
        manifest = load_geomodel_manifest(manifest_path)

        with pytest.raises(GeoModelAssetError, match="label count"):
            validate_geomodel_files(
                manifest, model_path, labels_path, manifest_path
            )

    def test_fp32_io_probability_contract_passes(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)

        validate_geomodel_session(_FakeSession(), manifest)

    def test_symbolic_feature_dimensions_use_smoke_output_width(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)
        session = _FakeSession()
        session.input_node.shape = ["batch", "features"]
        session.output_node.shape = ["batch", "classes"]

        validate_geomodel_session(session, manifest)

    def test_output_width_mismatch_is_rejected(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)
        session = _FakeSession()
        session.output_node.shape = ["batch", 3]

        with pytest.raises(GeoModelAssetError, match="output shape mismatch"):
            validate_geomodel_session(session, manifest)

    def test_non_probability_output_is_rejected(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)
        session = _FakeSession()
        session.probabilities[0, 0] = 1.1

        with pytest.raises(GeoModelAssetError, match="probability range"):
            validate_geomodel_session(session, manifest)

    def test_smoke_inference_error_uses_asset_error_contract(self, tmp_path):
        _model_path, _labels_path, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_geomodel_manifest(manifest_path)
        session = _FakeSession()

        def fail_inference(*_args, **_kwargs):
            raise RuntimeError("unsupported operator")

        session.run = fail_inference

        with pytest.raises(GeoModelAssetError, match="smoke inference failed"):
            validate_geomodel_session(session, manifest)

    def test_session_construction_error_uses_asset_error_contract(
        self, tmp_path, monkeypatch
    ):
        model_path, labels_path, manifest_path = _write_test_bundle(tmp_path)

        def fail_session(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr("onnxruntime.InferenceSession", fail_session)

        with pytest.raises(GeoModelAssetError, match="initialize geomodel"):
            load_validated_geomodel(model_path, labels_path, manifest_path)


class TestBundledGeoModelV303:
    bundle_dir = (
        Path(__file__).resolve().parents[2]
        / "model_service"
        / "models"
        / "geomodel"
    )

    def test_real_release_artifacts_load_and_validate(self):
        loaded = load_validated_geomodel(
            self.bundle_dir / "geomodel_fp16.onnx",
            self.bundle_dir / "labels.txt",
            self.bundle_dir / "manifest.json",
        )

        assert loaded.manifest.version == "3.0.3"
        assert loaded.manifest.output_activation == "sigmoid"
        assert loaded.manifest.output_range == (0.0, 1.0)
        assert len(loaded.labels) == 12314
        assert loaded.session.get_inputs()[0].type == "tensor(float)"
        assert loaded.session.get_outputs()[0].type == "tensor(float)"

    def test_mapping_coverage_matches_v303_release(self):
        model_root = self.bundle_dir.parent
        acoustic_labels = [
            f"{sci}_{common}"
            for sci, common in parse_v3_labels(
                str(
                    model_root
                    / "v3.1"
                    / "BirdNET+_V3.0-preview3.1_Global_11K_Labels.csv"
                )
            )
        ]
        geomodel_labels = parse_geomodel_labels(str(self.bundle_dir / "labels.txt"))
        location_filter = GeoModelFilter(
            str(self.bundle_dir / "geomodel_fp16.onnx"),
            str(self.bundle_dir / "labels.txt"),
            acoustic_labels,
            str(self.bundle_dir / "manifest.json"),
        )

        location_filter._build_label_mapping(geomodel_labels)

        assert len(acoustic_labels) == 11560
        assert len(location_filter._index_to_birdnet_label) == 10505
        assert len(location_filter._unmapped_labels) == 1055
