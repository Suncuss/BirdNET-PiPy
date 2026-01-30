"""BirdWeather service for uploading detections to birdweather.com.

This module provides async upload of bird detections to the BirdWeather network.
Uploads are queued and processed in a background thread to avoid blocking detection pipeline.
"""

import os
import queue
import subprocess
import tempfile
import threading
from datetime import datetime
from typing import Dict, Any, Optional

import requests

from config.settings import LAT, LON, BIRDWEATHER_ID
from core.timezone_service import get_timezone
from core.logging_config import get_logger

logger = get_logger(__name__)

BIRDWEATHER_API_BASE = "https://app.birdweather.com/api/v1/stations"
BIRDWEATHER_TIMEOUT = 30


def _to_iso8601_with_tz(timestamp_str: str) -> str:
    """Convert timestamp string to ISO8601 with local timezone."""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=get_timezone())
        return dt.isoformat()
    except Exception:
        return timestamp_str


BIRDWEATHER_QUEUE_MAXSIZE = 50  # Limit queue to prevent disk pressure from FLAC files


class BirdWeatherService:
    """Thread-safe BirdWeather upload service with background processing."""

    def __init__(self, station_id: str):
        self._station_id = station_id
        self._queue: queue.Queue = queue.Queue(maxsize=BIRDWEATHER_QUEUE_MAXSIZE)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        logger.info("BirdWeather service started", extra={'station_id': station_id[:8] + '...'})

    def publish(self, detection: Dict[str, Any], audio_path: str, start_time: float, end_time: float) -> None:
        """Queue detection for async upload. Returns immediately.

        Extracts audio to FLAC synchronously (before file is deleted by main thread),
        then queues for async upload. Drops upload if queue is full to prevent disk pressure.

        Args:
            detection: Detection dictionary from BirdNet analysis
            audio_path: Path to the source WAV file
            start_time: Start time in seconds within the audio file
            end_time: End time in seconds within the audio file
        """
        # Extract FLAC synchronously to avoid race condition with file deletion
        flac_path = self._extract_flac(audio_path, start_time, end_time)
        if flac_path:
            clip_duration = end_time - start_time
            try:
                self._queue.put_nowait((detection, flac_path, clip_duration))
            except queue.Full:
                logger.warning("BirdWeather queue full, dropping upload", extra={
                    'species': detection.get('common_name')
                })
                try:
                    os.remove(flac_path)
                except OSError:
                    pass

    def _worker_loop(self) -> None:
        """Process uploads sequentially in background."""
        while True:
            item = self._queue.get()
            try:
                self._do_publish(*item)
            except Exception as e:
                logger.error("BirdWeather upload failed", extra={'error': str(e)})

    def _do_publish(self, detection: Dict[str, Any], flac_path: str,
                    clip_duration: float) -> None:
        """Perform the actual upload to BirdWeather API.

        Args:
            detection: Detection dictionary from BirdNet analysis
            flac_path: Path to the pre-extracted FLAC file
            clip_duration: Duration of the extracted clip in seconds
        """
        # Extract timestamp from detection and ensure it has timezone info
        raw_timestamp = detection.get('timestamp', datetime.now().isoformat())
        timestamp_str = _to_iso8601_with_tz(raw_timestamp)

        try:
            # 1. Upload soundscape
            soundscape_id = self._upload_soundscape(flac_path, timestamp_str)
            if not soundscape_id:
                return

            # 2. Upload detection (offsets are relative to the uploaded clip: 0 to duration)
            self._upload_detection(detection, soundscape_id, timestamp_str, clip_duration)

            logger.info("BirdWeather upload complete", extra={
                'species': detection.get('common_name'),
                'soundscape_id': soundscape_id
            })
        finally:
            # Clean up temp FLAC file
            if flac_path and os.path.exists(flac_path):
                try:
                    os.remove(flac_path)
                except OSError:
                    pass

    def _extract_flac(self, audio_path: str, start_time: float, end_time: float) -> Optional[str]:
        """Extract audio segment and convert to FLAC."""
        if not os.path.exists(audio_path):
            logger.warning("Audio file not found for BirdWeather", extra={'path': audio_path})
            return None

        fd, flac_path = tempfile.mkstemp(suffix='.flac')
        os.close(fd)

        try:
            cmd = ['ffmpeg', '-y', '-ss', str(start_time), '-t', str(end_time - start_time),
                   '-i', audio_path, '-c:a', 'flac', '-ar', '48000', '-ac', '1', flac_path]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0:
                return flac_path
            logger.warning("FFmpeg FLAC conversion failed", extra={'stderr': result.stderr.decode()[-200:]})
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg FLAC conversion timed out")
        except Exception as e:
            logger.warning("FLAC extraction error", extra={'error': str(e)})

        # Cleanup on any failure
        if os.path.exists(flac_path):
            os.remove(flac_path)
        return None

    def _upload_soundscape(self, flac_path: str, timestamp: str) -> Optional[str]:
        """Upload audio file to BirdWeather soundscapes endpoint.

        Returns:
            soundscape_id on success, None on failure
        """
        url = f"{BIRDWEATHER_API_BASE}/{self._station_id}/soundscapes"
        params = {'timestamp': timestamp}

        try:
            with open(flac_path, 'rb') as f:
                audio_data = f.read()

            response = requests.post(
                url,
                params=params,
                data=audio_data,
                headers={'Content-Type': 'audio/flac'},
                timeout=BIRDWEATHER_TIMEOUT
            )

            if response.status_code in (200, 201):
                data = response.json()
                soundscape_id = data.get('soundscape', {}).get('id')
                if soundscape_id:
                    logger.debug("Soundscape uploaded", extra={'soundscape_id': soundscape_id})
                    return str(soundscape_id)
                else:
                    logger.warning("No soundscape ID in response", extra={'response': data})
                    return None
            else:
                logger.warning("Soundscape upload failed", extra={
                    'status': response.status_code,
                    'response': response.text[:200]
                })
                return None

        except requests.exceptions.Timeout:
            logger.warning("Soundscape upload timed out")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning("Soundscape upload error", extra={'error': str(e)})
            return None

    def _upload_detection(self, detection: Dict[str, Any], soundscape_id: str,
                          timestamp: str, clip_duration: float) -> bool:
        """Upload detection metadata to BirdWeather detections endpoint.

        Returns:
            True on success, False on failure
        """
        url = f"{BIRDWEATHER_API_BASE}/{self._station_id}/detections"

        # Offsets are relative to the uploaded soundscape clip (0 to clip_duration)
        payload = {
            'timestamp': timestamp,
            'lat': LAT,
            'lon': LON,
            'soundscapeId': soundscape_id,
            'soundscapeStartTime': 0,
            'soundscapeEndTime': clip_duration,
            'commonName': detection.get('common_name'),
            'scientificName': detection.get('scientific_name'),
            'algorithm': 'birdnet-pi',
            'confidence': detection.get('confidence')
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=BIRDWEATHER_TIMEOUT
            )

            if response.status_code in (200, 201):
                logger.debug("Detection uploaded to BirdWeather", extra={
                    'species': detection.get('common_name')
                })
                return True
            else:
                logger.warning("Detection upload failed", extra={
                    'status': response.status_code,
                    'response': response.text[:200]
                })
                return False

        except requests.exceptions.Timeout:
            logger.warning("Detection upload timed out")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning("Detection upload error", extra={'error': str(e)})
            return False


# Singleton
_birdweather_service: Optional[BirdWeatherService] = None


def get_birdweather_service() -> Optional[BirdWeatherService]:
    """Get or create BirdWeather service singleton.

    Returns:
        BirdWeatherService instance if station ID is configured, None otherwise
    """
    global _birdweather_service
    if _birdweather_service is None and BIRDWEATHER_ID:
        _birdweather_service = BirdWeatherService(BIRDWEATHER_ID)
    return _birdweather_service
