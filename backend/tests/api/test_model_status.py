"""Model-service health reads (read_model_service_status), which the settings
status snapshot and the readiness probe build on."""

from unittest.mock import Mock, patch

import requests


def _read_status():
    from core.api import read_model_service_status
    return read_model_service_status()


class TestReadModelServiceStatus:
    def test_passes_through_structured_filter_status(self):
        upstream = Mock()
        upstream.json.return_value = {
            "status": "degraded",
            "model": {
                "type": "birdnet_v3",
                "name": "BirdNET V3",
                "version": "3.1",
            },
            "location_filter": {
                "state": "degraded",
                "source": "disabled",
                "version": None,
                "code": "geomodel_validation_failed",
                "message": "Location filtering failed to start.",
            },
        }

        with patch("core.api.requests.get", return_value=upstream) as request_get:
            payload = _read_status()

        assert payload["location_filter"]["state"] == "degraded"
        request_get.assert_called_once()
        assert request_get.call_args.kwargs["timeout"] == 3
        upstream.raise_for_status.assert_called_once_with()

    def test_returns_unavailable_status_when_model_service_is_down(self):
        with (
            patch(
                "core.api.requests.get",
                side_effect=requests.exceptions.ConnectionError(
                    "connection refused"
                ),
            ),
            patch("core.api.read_startup_failure", return_value=None),
        ):
            payload = _read_status()

        assert payload["status"] == "unavailable"
        assert payload["location_filter"]["state"] == "unavailable"
        assert payload["location_filter"]["code"] == "model_service_unavailable"
        assert "may still be starting or may have failed" in payload[
            "location_filter"
        ]["message"]

    def test_surfaces_persisted_model_startup_failure(self):
        startup_failure = {
            "error_type": "BirdNetV3AssetError",
            "message": "model artifact checksum mismatch",
        }
        with (
            patch(
                "core.api.requests.get",
                side_effect=requests.exceptions.ConnectionError(
                    "connection refused"
                ),
            ),
            patch(
                "core.api.read_startup_failure",
                return_value=startup_failure,
            ),
        ):
            payload = _read_status()

        filter_status = payload["location_filter"]
        assert filter_status["code"] == "model_service_startup_failed"
        assert "BirdNetV3AssetError" in filter_status["message"]
        assert "checksum mismatch" in filter_status["message"]

    def test_rejects_malformed_upstream_status(self):
        upstream = Mock()
        upstream.json.return_value = {"status": "ok"}

        with patch("core.api.requests.get", return_value=upstream):
            payload = _read_status()

        assert payload["location_filter"]["state"] == "unavailable"
