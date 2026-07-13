"""Location-filter factory degradation tests."""

import logging
from unittest.mock import MagicMock


def _configure_existing_bundle_paths(tmp_path, monkeypatch):
    from config import settings

    model_path = tmp_path / "geomodel.onnx"
    labels_path = tmp_path / "labels.txt"
    manifest_path = tmp_path / "manifest.json"
    for path in (model_path, labels_path, manifest_path):
        path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(settings, "GEOMODEL_PATH", str(model_path))
    monkeypatch.setattr(settings, "GEOMODEL_LABELS_PATH", str(labels_path))
    monkeypatch.setattr(settings, "GEOMODEL_MANIFEST_PATH", str(manifest_path))


def test_geomodel_validation_failure_returns_visible_degraded_state(
    tmp_path, monkeypatch, caplog
):
    from config.constants import ModelType
    from model_service.geomodel_assets import GeoModelAssetError
    from model_service.location_filter import GeoModelFilter, NoFilter
    from model_service.model_factory import create_location_filter

    _configure_existing_bundle_paths(tmp_path, monkeypatch)
    model = MagicMock()
    model.get_labels.return_value = ["Turdus migratorius_American Robin"]

    def fail_validation(_self):
        raise GeoModelAssetError("checksum mismatch")

    monkeypatch.setattr(GeoModelFilter, "load", fail_validation)

    with caplog.at_level(logging.ERROR):
        location_filter = create_location_filter(ModelType.BIRDNET_V3, model=model)

    assert isinstance(location_filter, NoFilter)
    assert location_filter.status.state == "degraded"
    assert location_filter.status.code == "geomodel_validation_failed"
    assert "without location filtering" in location_filter.status.message
    assert any("Geomodel validation failed" in record.message for record in caplog.records)


def test_missing_geomodel_uses_validation_degraded_state(tmp_path, monkeypatch):
    from config import settings
    from config.constants import ModelType
    from model_service.location_filter import NoFilter
    from model_service.model_factory import create_location_filter

    monkeypatch.setattr(settings, "GEOMODEL_PATH", str(tmp_path / "missing.onnx"))

    location_filter = create_location_filter(
        ModelType.BIRDNET_V3,
        birdnet_labels=["Turdus migratorius_American Robin"],
    )

    assert isinstance(location_filter, NoFilter)
    assert location_filter.status.state == "degraded"
    assert location_filter.status.code == "geomodel_validation_failed"


def test_v24_meta_model_validation_failure_degrades_without_breaking_acoustic_model(
    caplog,
):
    from config.constants import ModelType
    from model_service.location_filter import NoFilter
    from model_service.model_factory import create_location_filter

    model = MagicMock()
    model.validate_location_model.side_effect = ValueError("corrupt meta model")

    with caplog.at_level(logging.ERROR):
        location_filter = create_location_filter(ModelType.BIRDNET, model=model)

    assert isinstance(location_filter, NoFilter)
    assert location_filter.status.state == "degraded"
    assert location_filter.status.code == "meta_model_validation_failed"
    assert any(
        "meta-model validation failed" in record.message
        for record in caplog.records
    )
