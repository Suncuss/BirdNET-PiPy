"""Durable model-service startup diagnostic tests."""

import json

from model_service.service_status import (
    clear_startup_failure,
    read_startup_failure,
    write_startup_failure,
)


def test_startup_failure_round_trip_and_clear(tmp_path):
    status_path = tmp_path / "model_startup.json"

    write_startup_failure(
        status_path,
        model_type="birdnet_v3",
        error=RuntimeError("checksum mismatch"),
    )

    payload = read_startup_failure(status_path)
    assert payload["model_type"] == "birdnet_v3"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "checksum mismatch"

    clear_startup_failure(status_path)
    assert read_startup_failure(status_path) is None


def test_malformed_startup_failure_is_ignored(tmp_path):
    status_path = tmp_path / "model_startup.json"
    status_path.write_text(json.dumps({"message": "incomplete"}), encoding="utf-8")

    assert read_startup_failure(status_path) is None
