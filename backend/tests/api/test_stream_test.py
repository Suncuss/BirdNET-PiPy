"""Tests for the POST /api/stream/test endpoint."""
from unittest.mock import MagicMock, patch


class TestStreamTestEndpoint:
    """Tests for stream URL testing API."""

    def test_missing_url(self, api_client):
        resp = api_client.post('/api/stream/test', json={})
        assert resp.status_code == 400
        assert 'No URL' in resp.json['error']

    def test_empty_url(self, api_client):
        resp = api_client.post('/api/stream/test', json={'url': ''})
        assert resp.status_code == 400

    def test_invalid_rtsp_url_format(self, api_client):
        resp = api_client.post('/api/stream/test', json={'url': 'http://wrong'})
        assert resp.status_code == 200
        assert resp.json['success'] is False
        assert 'Invalid URL format' in resp.json['message']

    @patch('core.audio_manager.subprocess.run')
    def test_rtsp_stream_success(self, mock_run, api_client):
        """Successful RTSP probe returns success=true."""
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        resp = api_client.post('/api/stream/test', json={
            'url': 'rtsp://192.168.1.100:554/stream',
        })
        assert resp.status_code == 200
        assert resp.json['success'] is True
