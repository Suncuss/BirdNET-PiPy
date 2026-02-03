"""Weather service for fetching current weather from Open-Meteo API.

This module provides background hourly weather fetching with caching.
Weather is fetched automatically when location is configured and the service is started.
The get_current_weather() method returns cached data immediately without blocking.
"""

import threading
import time
import requests
from typing import Optional, Dict

from core.logging_config import get_logger

logger = get_logger(__name__)

OPEN_METEO_API_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_REQUEST_TIMEOUT = 10

# Background fetch configuration
MAX_CACHE_AGE = 3 * 3600   # 3 hours - stale data is worse than no data
RETRY_COUNT = 3
RETRY_DELAY = 10           # seconds between retries
FETCH_INTERVAL = 3600      # 1 hour


class WeatherService:
    """Thread-safe weather service with background hourly fetching."""

    def __init__(self, lat: float, lon: float):
        """Initialize weather service with location coordinates.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
        """
        self._lat = lat
        self._lon = lon
        self._cache: Optional[Dict] = None
        self._cache_time: Optional[float] = None  # time.time() based
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._fetch_thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self._fetch_thread.start()
        logger.info("Weather service started", extra={'lat': lat, 'lon': lon})

    def _fetch_loop(self) -> None:
        """Background loop that fetches weather on startup and then hourly."""
        self._fetch_with_retry()  # Initial fetch with retries
        while not self._stop_event.wait(FETCH_INTERVAL):
            self._fetch_with_retry()

    def _fetch_with_retry(self) -> None:
        """Fetch weather with retry logic on failure."""
        for attempt in range(RETRY_COUNT):
            weather = self._fetch_weather()
            if weather:
                with self._lock:
                    self._cache = weather
                    self._cache_time = time.time()
                logger.info("Weather updated", extra={
                    'temp': weather['temp'],
                    'code': weather['code']
                })
                return
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)
        logger.warning(f"Weather fetch failed after {RETRY_COUNT} attempts")

    def _fetch_weather(self) -> Optional[Dict]:
        """Make API request to Open-Meteo.

        Returns:
            Weather dict on success, None on failure (errors are logged)
        """
        params = {
            'latitude': self._lat,
            'longitude': self._lon,
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

            if None in weather.values():
                logger.warning("Incomplete weather data from API", extra={'response': current})
                return None

            return weather

        except requests.exceptions.Timeout:
            logger.warning("Weather API timeout")
        except requests.exceptions.ConnectionError:
            logger.warning("Weather API connection error")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Weather API error: {e}")
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            # ValueError covers json.JSONDecodeError (its parent class)
            logger.warning(f"Weather API response parse error: {e}")
        return None

    def get_current_weather(self) -> Optional[Dict]:
        """Get current cached weather data.

        Returns immediately with cached data or None if unavailable/stale.
        Never blocks on API calls.

        Returns:
            Weather dict if valid cache exists, None otherwise
        """
        with self._lock:
            if self._cache is None or self._cache_time is None:
                return None
            if time.time() - self._cache_time > MAX_CACHE_AGE:
                # Stale data is worse than no data - clear it
                self._cache = None
                self._cache_time = None
                return None
            return self._cache

    def stop(self) -> None:
        """Stop the background fetch thread. Useful for testing and graceful shutdown."""
        self._stop_event.set()
        if self._fetch_thread.is_alive():
            self._fetch_thread.join(timeout=1)

    def clear_cache(self):
        """Clear the weather cache. Useful for testing."""
        with self._lock:
            self._cache = None
            self._cache_time = None


# Singleton
_weather_service: Optional[WeatherService] = None
_weather_service_lock = threading.Lock()


def get_weather_service(lat: Optional[float] = None, lon: Optional[float] = None) -> Optional[WeatherService]:
    """Get or create weather service singleton.

    Args:
        lat: Latitude (required on first call)
        lon: Longitude (required on first call)

    Returns:
        WeatherService instance if location provided on first call, None otherwise
    """
    global _weather_service
    with _weather_service_lock:
        if _weather_service is None:
            if lat is None or lon is None:
                return None
            _weather_service = WeatherService(lat, lon)
        return _weather_service


def reset_weather_service() -> None:
    """Reset the weather service singleton. Useful for testing."""
    global _weather_service
    with _weather_service_lock:
        if _weather_service is not None:
            _weather_service.stop()
            _weather_service = None
