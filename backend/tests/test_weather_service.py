"""Tests for the weather service module."""

import threading
import time
from unittest.mock import MagicMock, patch

import requests


def _create_mock_response(timezone='America/New_York'):
    """Create a standard mock response with valid weather data."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'timezone': timezone,
        'current': {
            'temperature_2m': 15.2,
            'relative_humidity_2m': 80,
            'precipitation': 0.0,
            'wind_speed_10m': 8.5,
            'weather_code': 3,
            'cloud_cover': 20,
            'pressure_msl': 1013
        }
    }
    mock_response.raise_for_status.return_value = None
    return mock_response


class TestWeatherService:
    """Test WeatherService class functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def teardown_method(self):
        """Clean up after each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def test_service_starts_background_thread(self):
        """Test that service starts a background fetch thread on init."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Give thread time to start and make initial fetch
            time.sleep(0.1)

            # Thread should have fetched weather
            assert mock_get.call_count >= 1
            service.stop()

    def test_get_current_weather_returns_cached_data(self):
        """Test that get_current_weather returns cached data immediately."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Wait for initial fetch
            time.sleep(0.1)

            weather = service.get_current_weather()
            assert weather is not None
            assert weather['temp'] == 15.2
            assert weather['humidity'] == 80
            assert weather['precip'] == 0.0
            assert weather['wind'] == 8.5
            assert weather['code'] == 3
            assert weather['cloud_cover'] == 20
            assert weather['pressure'] == 1013
            service.stop()

    def test_get_current_weather_returns_none_before_fetch(self):
        """Test that get_current_weather returns None if cache is empty."""
        with patch('core.weather_service.requests.get') as mock_get:
            # Make fetch slow so we can check before it completes
            def slow_get(*args, **kwargs):
                time.sleep(1)
                return _create_mock_response()
            mock_get.side_effect = slow_get

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Check immediately before fetch completes
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

    def test_get_current_weather_never_blocks(self):
        """Test that get_current_weather returns immediately even when API is slow."""
        with patch('core.weather_service.requests.get') as mock_get:
            # Make API very slow
            def very_slow_get(*args, **kwargs):
                time.sleep(10)
                return _create_mock_response()
            mock_get.side_effect = very_slow_get

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # get_current_weather should return immediately (< 100ms)
            start = time.time()
            weather = service.get_current_weather()
            elapsed = time.time() - start

            assert elapsed < 0.1  # Should be nearly instant
            assert weather is None  # No cache yet
            service.stop()

    def test_retry_on_failure(self):
        """Test that service retries on fetch failure."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 3):

            # Fail twice, succeed third time
            call_count = [0]
            def flaky_get(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] < 3:
                    raise requests.exceptions.Timeout()
                return _create_mock_response()
            mock_get.side_effect = flaky_get

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Wait for retries to complete
            time.sleep(0.2)

            # Should have called 3 times (2 failures + 1 success)
            assert call_count[0] == 3
            weather = service.get_current_weather()
            assert weather is not None
            service.stop()

    def test_all_retries_fail(self):
        """Test that after all retries fail, cache remains empty."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 3):

            mock_get.side_effect = requests.exceptions.Timeout()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Wait for all retries to complete
            time.sleep(0.2)

            weather = service.get_current_weather()
            assert weather is None
            assert mock_get.call_count == 3
            service.stop()

    def test_cache_expiration(self):
        """Test that cache expires after MAX_CACHE_AGE."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.time') as mock_time:

            mock_get.return_value = _create_mock_response()

            # Use real time.sleep but mock time.time for cache checks
            real_sleep = time.sleep
            mock_time.sleep = real_sleep
            mock_time.time.return_value = 1000.0

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Wait for fetch
            real_sleep(0.1)

            # Cache should be valid
            weather = service.get_current_weather()
            assert weather is not None

            # Simulate time passing beyond MAX_CACHE_AGE (3 hours)
            mock_time.time.return_value = 1000.0 + (3 * 3600) + 1

            # Cache should now be stale
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

    def test_stop_terminates_thread(self):
        """Test that stop() terminates the background thread."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            assert service._fetch_thread.is_alive()

            service.stop()
            time.sleep(0.1)
            assert not service._fetch_thread.is_alive()

    def test_clear_cache(self):
        """Test that clear_cache resets the cache."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            assert service.get_current_weather() is not None

            service.clear_cache()
            assert service.get_current_weather() is None
            service.stop()

    def test_api_url_and_params(self):
        """Test that API is called with correct URL and parameters."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)

            mock_get.assert_called()
            call_args = mock_get.call_args
            assert 'api.open-meteo.com' in call_args[0][0]

            params = call_args[1]['params']
            assert params['latitude'] == 42.47
            assert params['longitude'] == -76.45
            assert 'temperature_2m' in params['current']
            assert params['timezone'] == 'auto'
            service.stop()

    def test_connection_error_handled(self):
        """Test connection error is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 1):

            mock_get.side_effect = requests.exceptions.ConnectionError()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

    def test_http_error_handled(self):
        """Test HTTP error is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 1):

            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError('500')
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

    def test_incomplete_response_handled(self):
        """Test incomplete API response is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 1):

            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0
                    # Missing other fields
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

    def test_null_current_handled(self):
        """Test null 'current' in response is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.RETRY_DELAY', 0.01), \
             patch('core.weather_service.RETRY_COUNT', 1):

            mock_response = MagicMock()
            mock_response.json.return_value = {'current': None}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            time.sleep(0.1)
            weather = service.get_current_weather()
            assert weather is None
            service.stop()

class TestWeatherServiceSingleton:
    """Test the get_weather_service singleton function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def teardown_method(self):
        """Clean up after each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def test_singleton_returns_same_instance(self):
        """Test that get_weather_service returns the same instance."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import get_weather_service

            service1 = get_weather_service(42.47, -76.45)
            service2 = get_weather_service(42.47, -76.45)

            assert service1 is service2
            service1.stop()

    def test_singleton_returns_none_without_coords(self):
        """Test that get_weather_service returns None if coords not provided on first call."""
        from core.weather_service import get_weather_service

        service = get_weather_service()
        assert service is None

    def test_singleton_ignores_coords_after_first_call(self):
        """Test that coords are ignored after service is created."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import get_weather_service

            service1 = get_weather_service(42.47, -76.45)
            # Second call with different coords should return same service
            service2 = get_weather_service(0.0, 0.0)

            assert service1 is service2
            assert service1._lat == 42.47
            assert service1._lon == -76.45
            service1.stop()

    def test_reset_allows_new_instance(self):
        """Test that reset_weather_service allows creating a new instance."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import get_weather_service, reset_weather_service

            service1 = get_weather_service(42.47, -76.45)
            reset_weather_service()
            service2 = get_weather_service(0.0, 0.0)

            assert service1 is not service2
            assert service2._lat == 0.0
            assert service2._lon == 0.0
            service2.stop()


class TestWeatherServiceThreadSafety:
    """Test thread safety of WeatherService."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def teardown_method(self):
        """Clean up after each test."""
        import core.weather_service as ws
        ws.reset_weather_service()

    def test_concurrent_get_weather_calls(self):
        """Test that concurrent get_current_weather calls don't cause race conditions."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import WeatherService
            service = WeatherService(42.47, -76.45)

            # Wait for initial fetch
            time.sleep(0.1)

            results = []
            errors = []

            def fetch_weather():
                try:
                    weather = service.get_current_weather()
                    results.append(weather)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=fetch_weather) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            assert len(results) == 10
            # All results should be identical
            assert all(r == results[0] for r in results)
            service.stop()

    def test_concurrent_singleton_access(self):
        """Test that concurrent get_weather_service calls return same instance."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.return_value = _create_mock_response()

            from core.weather_service import get_weather_service

            services = []
            errors = []

            def get_service():
                try:
                    service = get_weather_service(42.47, -76.45)
                    services.append(service)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=get_service) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            assert len(services) == 10
            # All should be the same instance
            assert all(s is services[0] for s in services)
            services[0].stop()
