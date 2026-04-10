"""Tests for the system logs API endpoint."""

from unittest.mock import patch


class TestLogsAPI:
    """Test GET /api/system/logs endpoint."""

    def test_returns_log_entries(self, api_client):
        """Test endpoint returns correct structure."""
        mock_result = {
            'entries': [
                {
                    'timestamp': '2026-03-14T12:00:00Z',
                    'level': 'INFO',
                    'service': 'main',
                    'message': 'Audio recorded',
                    'module': 'audio_manager',
                    'extra': {},
                }
            ],
            'total': 1,
        }

        with patch('core.log_reader.get_logs', return_value=mock_result):
            response = api_client.get('/api/system/logs')

        assert response.status_code == 200
        data = response.get_json()
        assert 'entries' in data
        assert 'total' in data
        assert len(data['entries']) == 1
        assert data['entries'][0]['service'] == 'main'

    def test_filter_params_passed(self, api_client):
        """Test that filter query params are forwarded to get_logs."""
        with patch('core.log_reader.get_logs', return_value={'entries': [], 'total': 0}) as mock_get:
            response = api_client.get(
                '/api/system/logs?service=api&search=bird&limit=100'
            )

        assert response.status_code == 200
        mock_get.assert_called_once_with(
            service='api', search='bird', limit=100
        )

    def test_requires_auth(self, api_client):
        """Test that endpoint requires authentication when auth is enabled."""
        # Enable auth by setting up a password
        api_client.post('/api/auth/setup', json={'password': 'testpass123'})
        # Logout
        api_client.post('/api/auth/logout')

        response = api_client.get('/api/system/logs')
        assert response.status_code == 401

    def test_empty_logs(self, api_client):
        """Test endpoint handles empty results."""
        with patch('core.log_reader.get_logs', return_value={'entries': [], 'total': 0}):
            response = api_client.get('/api/system/logs')

        assert response.status_code == 200
        data = response.get_json()
        assert data['entries'] == []
        assert data['total'] == 0
