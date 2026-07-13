"""Integrity, tensor-contract, and real-artifact tests for BirdNET V3.1."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from model_service.birdnet_v3_assets import (
    LEGACY_BIRDNET_V3_FILENAME,
    BirdNetV3AssetError,
    load_birdnet_v3_manifest,
    load_validated_birdnet_v3,
    remove_legacy_birdnet_v3_files,
    validate_birdnet_v3_files,
    validate_birdnet_v3_session,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_test_bundle(tmp_path: Path, *, output_classes: int = 2):
    model_path = tmp_path / "model.onnx"
    labels_path = tmp_path / "labels.csv"
    terms_path = tmp_path / "TERMS_OF_USE.txt"
    manifest_path = tmp_path / "manifest.json"

    model_path.write_bytes(b"model")
    labels_path.write_text(
        "idx;id;sci_name;com_name;class;order\n"
        "0;1;Turdus migratorius;American Robin;Aves;Passeriformes\n"
        "1;2;Cardinalis cardinalis;Northern Cardinal;Aves;Passeriformes\n",
        encoding="utf-8",
    )
    terms_path.write_text("terms\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "version": "3.1",
        "source": {
            "repository": "https://example.test/birdnet",
            "release": "https://example.test/birdnet/releases/3.1",
            "doi": "10.example/birdnet",
            "upstream_name": "BirdNET test release",
        },
        "license": {
            "spdx": "CC-BY-SA-4.0",
            "url": "https://creativecommons.org/licenses/by-sa/4.0/",
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
            "terms": {
                "filename": terms_path.name,
                "size_bytes": terms_path.stat().st_size,
                "sha256": _digest(terms_path),
            },
        },
        "contract": {
            "sample_rate_hz": 32000,
            "input": {
                "name": "input",
                "dtype": "tensor(float)",
                "rank": 2,
            },
            "predictions": {
                "name": "predictions",
                "dtype": "tensor(float)",
                "classes": output_classes,
                "activation": "sigmoid",
                "range": [0.0, 1.0],
            },
        },
        "precision": "test precision",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return model_path, labels_path, terms_path, manifest_path


class _FakeSession:
    def __init__(self, output_classes: int = 2):
        self.input_node = SimpleNamespace(
            name="input",
            type="tensor(float)",
            shape=["batch", "samples"],
        )
        self.embedding_node = SimpleNamespace(
            name="embeddings_out",
            type="tensor(float)",
            shape=["batch", 1280],
        )
        self.prediction_node = SimpleNamespace(
            name="predictions",
            type="tensor(float)",
            shape=["batch", output_classes],
        )
        self.probabilities = np.full(
            (1, output_classes), 0.25, dtype=np.float32
        )
        self.requested_outputs = None

    def get_inputs(self):
        return [self.input_node]

    def get_outputs(self):
        # Deliberately use the legacy ordering to prove validation is name-based.
        return [self.embedding_node, self.prediction_node]

    def run(self, output_names, inputs):
        self.requested_outputs = output_names
        assert output_names == ["predictions"]
        assert inputs["input"].shape == (1, 96000)
        assert inputs["input"].dtype == np.float32
        assert np.any(inputs["input"] != 0.0)
        return [self.probabilities]


class TestBirdNetV3AssetValidation:
    def test_matching_bundle_passes(self, tmp_path):
        model_path, labels_path, _terms_path, manifest_path = _write_test_bundle(
            tmp_path
        )
        manifest = load_birdnet_v3_manifest(manifest_path)

        labels = validate_birdnet_v3_files(
            manifest, model_path, labels_path, manifest_path
        )

        assert manifest.version == "3.1"
        assert manifest.precision == "test precision"
        assert labels[0] == ("Turdus migratorius", "American Robin")

    def test_null_version_is_rejected(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["version"] = None
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(BirdNetV3AssetError, match="version.*non-empty string"):
            load_birdnet_v3_manifest(manifest_path)

    def test_wrong_app_version_is_rejected(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["version"] = "3.0"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(BirdNetV3AssetError, match="version must be '3.1'"):
            load_birdnet_v3_manifest(manifest_path)

    def test_model_checksum_mismatch_is_rejected(self, tmp_path):
        model_path, labels_path, _terms_path, manifest_path = _write_test_bundle(
            tmp_path
        )
        manifest = load_birdnet_v3_manifest(manifest_path)
        model_path.write_bytes(b"MODEL")

        with pytest.raises(BirdNetV3AssetError, match="checksum mismatch"):
            validate_birdnet_v3_files(
                manifest, model_path, labels_path, manifest_path
            )

    def test_label_count_must_match_prediction_width(self, tmp_path):
        model_path, labels_path, _terms_path, manifest_path = _write_test_bundle(
            tmp_path, output_classes=3
        )
        manifest = load_birdnet_v3_manifest(manifest_path)

        with pytest.raises(BirdNetV3AssetError, match="label count"):
            validate_birdnet_v3_files(
                manifest, model_path, labels_path, manifest_path
            )

    def test_terms_are_build_validated_but_not_runtime_load_bearing(self, tmp_path):
        model_path, labels_path, terms_path, manifest_path = _write_test_bundle(
            tmp_path
        )
        manifest = load_birdnet_v3_manifest(manifest_path)
        terms_path.unlink()

        validate_birdnet_v3_files(
            manifest, model_path, labels_path, manifest_path
        )
        with pytest.raises(BirdNetV3AssetError, match="terms artifact"):
            validate_birdnet_v3_files(
                manifest,
                model_path,
                labels_path,
                manifest_path,
                validate_documentation=True,
            )

    def test_prediction_output_is_selected_by_name_not_position(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_birdnet_v3_manifest(manifest_path)
        session = _FakeSession()

        validate_birdnet_v3_session(session, manifest)

        assert session.requested_outputs == ["predictions"]

    def test_missing_prediction_output_is_rejected(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_birdnet_v3_manifest(manifest_path)
        session = _FakeSession()
        session.prediction_node.name = "scores"

        with pytest.raises(BirdNetV3AssetError, match="available outputs"):
            validate_birdnet_v3_session(session, manifest)

    def test_static_prediction_width_mismatch_is_rejected(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_birdnet_v3_manifest(manifest_path)
        session = _FakeSession()
        session.prediction_node.shape = ["batch", 3]

        with pytest.raises(BirdNetV3AssetError, match="prediction shape mismatch"):
            validate_birdnet_v3_session(session, manifest)

    def test_symbolic_prediction_width_uses_smoke_result(self, tmp_path):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_birdnet_v3_manifest(manifest_path)
        session = _FakeSession()
        session.prediction_node.shape = ["batch", "classes"]

        validate_birdnet_v3_session(session, manifest)

    @pytest.mark.parametrize("bad_value", [np.nan, 1.1])
    def test_smoke_output_must_be_finite_probability(self, tmp_path, bad_value):
        _model, _labels, _terms, manifest_path = _write_test_bundle(tmp_path)
        manifest = load_birdnet_v3_manifest(manifest_path)
        session = _FakeSession()
        session.probabilities[0, 0] = bad_value

        with pytest.raises(BirdNetV3AssetError, match="non-finite|probability range"):
            validate_birdnet_v3_session(session, manifest)

    def test_session_construction_error_uses_asset_error(self, tmp_path, monkeypatch):
        model_path, labels_path, _terms_path, manifest_path = _write_test_bundle(
            tmp_path
        )

        def fail_session(*_args, **_kwargs):
            raise RuntimeError("unsupported operator")

        monkeypatch.setattr("onnxruntime.InferenceSession", fail_session)

        with pytest.raises(BirdNetV3AssetError, match="initialize BirdNET V3"):
            load_validated_birdnet_v3(model_path, labels_path, manifest_path)


class TestLegacyModelCleanup:
    def test_legacy_model_is_removed_without_hashing(self, tmp_path):
        legacy_path = tmp_path / LEGACY_BIRDNET_V3_FILENAME
        legacy_path.write_bytes(b"legacy")

        removed = remove_legacy_birdnet_v3_files(legacy_path)

        assert removed == (legacy_path,)
        assert not legacy_path.exists()

    def test_partial_download_residue_is_removed(self, tmp_path):
        legacy_path = tmp_path / LEGACY_BIRDNET_V3_FILENAME
        temporary_path = Path(f"{legacy_path}.tmp")
        temporary_path.write_bytes(b"partial")

        removed = remove_legacy_birdnet_v3_files(legacy_path)

        assert removed == (temporary_path,)
        assert not temporary_path.exists()

    def test_missing_legacy_model_is_a_noop(self, tmp_path):
        legacy_path = tmp_path / LEGACY_BIRDNET_V3_FILENAME

        assert remove_legacy_birdnet_v3_files(legacy_path) == ()

    def test_unexpected_cleanup_filename_is_rejected(self, tmp_path):
        custom_path = tmp_path / "custom.onnx"
        custom_path.write_bytes(b"custom")

        with pytest.raises(BirdNetV3AssetError, match="unexpected filename"):
            remove_legacy_birdnet_v3_files(custom_path)
        assert custom_path.exists()


class TestBundledBirdNetV31:
    bundle_dir = (
        Path(__file__).resolve().parents[2]
        / "model_service"
        / "models"
        / "v3.1"
    )

    def test_real_release_artifacts_load_and_validate(self):
        loaded = load_validated_birdnet_v3(
            self.bundle_dir
            / "BirdNET+_V3.0-preview3.1_Global_11K_FP16_pruned.onnx",
            self.bundle_dir
            / "BirdNET+_V3.0-preview3.1_Global_11K_Labels.csv",
            self.bundle_dir / "manifest.json",
            validate_documentation=True,
        )

        assert loaded.manifest.version == "3.1"
        assert loaded.manifest.output_classes == 11560
        assert len(loaded.labels) == 11560
        assert loaded.session.get_inputs()[0].type == "tensor(float)"
        outputs = {output.name: output for output in loaded.session.get_outputs()}
        assert outputs["predictions"].type == "tensor(float)"
        assert outputs["predictions"].shape[1] == 11560
