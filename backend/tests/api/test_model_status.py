"""Model-service health proxy tests."""

from unittest.mock import Mock, patch

import requests


class TestModelServiceStatus:
    def test_proxies_structured_filter_status(self, api_client):
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
            response = api_client.get("/api/model/status")

        assert response.status_code == 200
        assert response.get_json()["location_filter"]["state"] == "degraded"
        request_get.assert_called_once()
        assert request_get.call_args.kwargs["timeout"] == 3
        upstream.raise_for_status.assert_called_once_with()

    def test_returns_unavailable_status_when_model_service_is_down(self, api_client):
        with (
            patch(
                "core.api.requests.get",
                side_effect=requests.exceptions.ConnectionError(
                    "connection refused"
                ),
            ),
            patch("core.api.read_startup_failure", return_value=None),
        ):
            response = api_client.get("/api/model/status")

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "unavailable"
        assert payload["location_filter"]["state"] == "unavailable"
        assert payload["location_filter"]["code"] == "model_service_unavailable"
        assert "may still be starting or may have failed" in payload[
            "location_filter"
        ]["message"]

    def test_surfaces_persisted_model_startup_failure(self, api_client):
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
            response = api_client.get("/api/model/status")

        payload = response.get_json()
        filter_status = payload["location_filter"]
        assert filter_status["code"] == "model_service_startup_failed"
        assert "BirdNetV3AssetError" in filter_status["message"]
        assert "checksum mismatch" in filter_status["message"]

    def test_rejects_malformed_upstream_status(self, api_client):
        upstream = Mock()
        upstream.json.return_value = {"status": "ok"}

        with patch("core.api.requests.get", return_value=upstream):
            response = api_client.get("/api/model/status")

        assert response.status_code == 200
        assert response.get_json()["location_filter"]["state"] == "unavailable"
