"""Tests for the weather service module."""

import pytest
from unittest.mock import patch, MagicMock
import threading
import requests


class TestWeatherService:
    """Test WeatherService class functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws._weather_service = None

    def test_get_current_weather_success(self):
        """Test successful weather fetch returns data."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
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
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert error is None
            assert weather['temp'] == 15.2
            assert weather['humidity'] == 80
            assert weather['precip'] == 0.0
            assert weather['wind'] == 8.5
            assert weather['code'] == 3
            assert weather['cloud_cover'] == 20
            assert weather['pressure'] == 1013

    def test_get_current_weather_caching(self):
        """Test that weather is cached within the same hour."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 20.0,
                    'relative_humidity_2m': 50,
                    'precipitation': 0.0,
                    'wind_speed_10m': 5.0,
                    'weather_code': 0,
                    'cloud_cover': 10,
                    'pressure_msl': 1015
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call should hit API
            weather1, _ = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Second call should use cache
            weather2, _ = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1  # Still 1, no new API call

            assert weather1 == weather2

    def test_get_current_weather_timeout(self):
        """Test timeout returns None with error message."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert 'timeout' in error.lower()

    def test_get_current_weather_connection_error(self):
        """Test connection error returns None with error message."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError('Network unreachable')

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert 'connection' in error.lower()

    def test_get_current_weather_http_error(self):
        """Test HTTP error returns None with error message."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError('500 Server Error')
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert error is not None

    def test_get_current_weather_invalid_response(self):
        """Test invalid API response returns None with error."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'invalid': 'response'}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert error is not None

    def test_get_current_weather_partial_response(self):
        """Test partial API response (missing fields) returns error."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            # Missing some required fields
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70
                    # Missing: precipitation, wind_speed_10m, weather_code, etc.
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert 'Incomplete' in error

    def test_get_current_weather_api_url_format(self):
        """Test that API is called with correct URL parameters."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            service.get_current_weather(42.47, -76.45)

            # Verify API was called
            mock_get.assert_called_once()
            call_args = mock_get.call_args

            # Check URL
            assert 'api.open-meteo.com' in call_args[0][0]

            # Check params
            params = call_args[1]['params']
            assert params['latitude'] == 42.47
            assert params['longitude'] == -76.45
            assert 'temperature_2m' in params['current']
            assert params['timezone'] == 'auto'

    def test_cache_invalidates_on_hour_change(self):
        """Test cache invalidates when hour changes within same day."""
        from datetime import date
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.datetime') as mock_datetime:

            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            # Mock datetime.now() to return different hours on same day
            today = date(2024, 1, 15)
            mock_now_hour10 = MagicMock()
            mock_now_hour10.hour = 10
            mock_now_hour10.date.return_value = today
            mock_now_hour11 = MagicMock()
            mock_now_hour11.hour = 11
            mock_now_hour11.date.return_value = today

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call at hour 10
            mock_datetime.now.return_value = mock_now_hour10
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Second call still at hour 10 - should use cache
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Third call at hour 11 - should hit API again
            mock_datetime.now.return_value = mock_now_hour11
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 2

    def test_cache_invalidates_on_day_change(self):
        """Test cache invalidates when day changes even if same hour."""
        from datetime import date
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.datetime') as mock_datetime:

            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            # Mock datetime.now() to return same hour on different days
            day1 = date(2024, 1, 15)
            day2 = date(2024, 1, 16)
            mock_now_day1 = MagicMock()
            mock_now_day1.hour = 10
            mock_now_day1.date.return_value = day1
            mock_now_day2 = MagicMock()
            mock_now_day2.hour = 10  # Same hour!
            mock_now_day2.date.return_value = day2

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call on day 1 at 10:00
            mock_datetime.now.return_value = mock_now_day1
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Second call on day 1 at 10:00 - should use cache
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Third call on day 2 at 10:00 - should hit API again (different day!)
            mock_datetime.now.return_value = mock_now_day2
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 2

    def test_clear_cache(self):
        """Test that clear_cache resets the cache."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1

            # Clear cache
            service.clear_cache()

            # Next call should hit API again
            service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 2

    def test_negative_caching_on_failure(self):
        """Test that failures are cached for 5 minutes (negative caching)."""
        from datetime import datetime, timedelta
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.datetime') as mock_datetime:

            mock_get.side_effect = requests.exceptions.Timeout()

            # Mock time progression
            base_time = datetime(2024, 1, 15, 10, 0, 0)
            mock_datetime.now.return_value = base_time

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call - hits API and fails
            weather1, error1 = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1
            assert weather1 is None
            assert 'timeout' in error1.lower()

            # Second call 1 minute later - should use negative cache, no API call
            mock_datetime.now.return_value = base_time + timedelta(minutes=1)
            weather2, error2 = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1  # Still 1, no new API call
            assert weather2 is None
            assert 'temporarily unavailable' in error2.lower()

            # Third call 6 minutes later - should retry API (past 5 min cooldown)
            mock_datetime.now.return_value = base_time + timedelta(minutes=6)
            weather3, error3 = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 2  # New API call
            assert weather3 is None

    def test_error_cache_cleared_on_success(self):
        """Test that error cache is cleared when a successful fetch occurs."""
        from datetime import datetime, timedelta
        with patch('core.weather_service.requests.get') as mock_get, \
             patch('core.weather_service.datetime') as mock_datetime:

            base_time = datetime(2024, 1, 15, 10, 0, 0)
            mock_datetime.now.return_value = base_time

            from core.weather_service import WeatherService
            service = WeatherService()

            # First call fails
            mock_get.side_effect = requests.exceptions.Timeout()
            weather1, _ = service.get_current_weather(42.47, -76.45)
            assert weather1 is None
            assert mock_get.call_count == 1

            # Second call 1 minute later - still in error cache
            mock_datetime.now.return_value = base_time + timedelta(minutes=1)
            weather2, error2 = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 1
            assert 'temporarily unavailable' in error2.lower()

            # Now API recovers - move past error cache and try again
            mock_datetime.now.return_value = base_time + timedelta(minutes=6)
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.side_effect = None
            mock_get.return_value = mock_response

            weather3, error3 = service.get_current_weather(42.47, -76.45)
            assert weather3 is not None
            assert error3 is None
            assert mock_get.call_count == 2

            # Verify error cache was cleared - next hour should work immediately
            mock_datetime.now.return_value = base_time + timedelta(hours=1)
            mock_get.side_effect = requests.exceptions.Timeout()
            weather4, _ = service.get_current_weather(42.47, -76.45)
            assert mock_get.call_count == 3  # Would be skipped if error cache wasn't cleared

    def test_null_current_response_handled(self):
        """Test that null 'current' in API response is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'current': None}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert error is not None  # Should return error, not crash

    def test_non_dict_current_response_handled(self):
        """Test that non-dict 'current' in API response is handled gracefully."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'current': 'unexpected string'}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            weather, error = service.get_current_weather(42.47, -76.45)

            assert weather is None
            assert error is not None  # Should return error, not crash


class TestWeatherServiceSingleton:
    """Test the get_weather_service singleton function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws._weather_service = None

    def test_singleton_returns_same_instance(self):
        """Test that get_weather_service returns the same instance."""
        from core.weather_service import get_weather_service

        service1 = get_weather_service()
        service2 = get_weather_service()

        assert service1 is service2

    def test_singleton_creates_instance_if_none(self):
        """Test that singleton creates instance when none exists."""
        import core.weather_service as ws
        from core.weather_service import get_weather_service, WeatherService

        assert ws._weather_service is None

        service = get_weather_service()

        assert service is not None
        assert isinstance(service, WeatherService)


class TestWeatherServiceThreadSafety:
    """Test thread safety of WeatherService."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.weather_service as ws
        ws._weather_service = None

    def test_concurrent_access(self):
        """Test that concurrent access doesn't cause race conditions."""
        with patch('core.weather_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'current': {
                    'temperature_2m': 15.0,
                    'relative_humidity_2m': 70,
                    'precipitation': 0.0,
                    'wind_speed_10m': 10.0,
                    'weather_code': 1,
                    'cloud_cover': 30,
                    'pressure_msl': 1010
                }
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.weather_service import WeatherService
            service = WeatherService()
            results = []
            errors = []

            def fetch_weather():
                try:
                    weather, error = service.get_current_weather(42.47, -76.45)
                    results.append((weather, error))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=fetch_weather) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            assert len(results) == 10
            # All results should be identical (from cache after first call)
            assert all(r[0] == results[0][0] for r in results)
