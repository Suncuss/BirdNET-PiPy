"""Weather service for fetching current weather from Open-Meteo API.

This module provides hourly weather data caching and attachment to bird detections.
Weather is fetched automatically when location is configured.
"""

import threading
import requests
from datetime import datetime
from typing import Optional, Dict, Tuple
from core.logging_config import get_logger

logger = get_logger(__name__)

OPEN_METEO_API_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_REQUEST_TIMEOUT = 10
ERROR_CACHE_DURATION = 300  # Cache failures for 5 minutes to avoid repeated timeouts


class WeatherService:
    """Thread-safe weather service with hourly caching."""

    def __init__(self):
        self._cache: Optional[Dict] = None
        self._cache_time: Optional[datetime] = None
        self._error_cache_time: Optional[datetime] = None
        self._lock = threading.Lock()

    def _is_cache_valid(self, now: datetime) -> bool:
        """Check if cached weather is still valid (same date and hour)."""
        if self._cache is None or self._cache_time is None:
            return False
        return (self._cache_time.date() == now.date() and
                self._cache_time.hour == now.hour)

    def get_current_weather(self, lat: float, lon: float) -> Tuple[Optional[Dict], Optional[str]]:
        """Fetch current weather for given coordinates.

        Uses hourly caching - returns cached data if within same hour of same day.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)

        Returns:
            Tuple of (weather_dict, error_string)
            - On success: (weather_data, None)
            - On failure: (None, error_message)
        """
        with self._lock:
            now = datetime.now()

            # Return cached if same hour of same day
            if self._is_cache_valid(now):
                return self._cache, None

            # Check if we're in error cooldown period (negative caching)
            if self._error_cache_time:
                seconds_since_error = (now - self._error_cache_time).total_seconds()
                if seconds_since_error < ERROR_CACHE_DURATION:
                    return None, "Weather API temporarily unavailable"

            # Fetch fresh
            weather, error = self._fetch_weather(lat, lon)
            if weather:
                self._cache = weather
                self._cache_time = now
                self._error_cache_time = None  # Clear error cache on success
            else:
                self._error_cache_time = now  # Start error cooldown

            return weather, error

    def _fetch_weather(self, lat: float, lon: float) -> Tuple[Optional[Dict], Optional[str]]:
        """Make API request to Open-Meteo."""
        params = {
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,cloud_cover,pressure_msl',
            'timezone': 'auto'
        }

        try:
            response = requests.get(
                OPEN_METEO_API_URL,
                params=params,
                timeout=WEATHER_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()

            current = data.get('current') or {}
            weather = {
                'temp': current.get('temperature_2m'),
                'humidity': current.get('relative_humidity_2m'),
                'precip': current.get('precipitation'),
                'wind': current.get('wind_speed_10m'),
                'code': current.get('weather_code'),
                'cloud_cover': current.get('cloud_cover'),
                'pressure': current.get('pressure_msl')
            }

            # Validate we got all fields
            if None in weather.values():
                logger.warning("Incomplete weather data from API", extra={'response': current})
                return None, "Incomplete weather data from API"

            logger.debug("Weather fetched successfully", extra={
                'temp': weather['temp'],
                'code': weather['code']
            })
            return weather, None

        except requests.exceptions.Timeout:
            logger.warning("Weather API timeout")
            return None, "Weather API timeout"
        except requests.exceptions.ConnectionError:
            logger.warning("Weather API connection error")
            return None, "Weather API connection error"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Weather API error: {e}")
            return None, f"Weather API error: {str(e)}"
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning(f"Weather API response parse error: {e}")
            return None, "Invalid weather API response"

    def clear_cache(self):
        """Clear the weather cache. Useful for testing."""
        with self._lock:
            self._cache = None
            self._cache_time = None
            self._error_cache_time = None


# Singleton
_weather_service: Optional[WeatherService] = None


def get_weather_service() -> WeatherService:
    """Get or create weather service singleton."""
    global _weather_service
    if _weather_service is None:
        _weather_service = WeatherService()
    return _weather_service
