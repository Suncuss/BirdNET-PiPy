from config.settings import (
    RECORDING_DIR, RECORDING_LENGTH, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR,
    BIRDNET_SERVER_ENDPOINT, ANALYSIS_CHUNK_LENGTH, API_PORT, API_HOST, SAMPLE_RATE,
    RECORDING_MODE, PULSEAUDIO_SOURCE, STREAM_URL, RTSP_URL, LAT, LON, LOCATION_CONFIGURED
)
from core.db import DatabaseManager
from core.utils import generate_spectrogram, trim_audio, select_audio_chunks, convert_wav_to_mp3, sanitize_url
from core.audio_manager import BaseRecorder, create_recorder
from core.logging_config import setup_logging, get_logger
from core.storage_manager import storage_monitor_loop
from core.weather_service import get_weather_service
from version import __version__, DISPLAY_NAME

import json
import os
import time
import glob
import threading
import requests
from typing import List, Dict, Any
import signal

# Configuration constants
MIN_RECORDING_DURATION = 5.0  # Minimum acceptable recording duration in seconds
FILE_SCAN_INTERVAL = 2.0      # How often to scan for new recordings (seconds)
BROADCAST_TIMEOUT = 5         # WebSocket broadcast request timeout (seconds)
BIRDNET_REQUEST_TIMEOUT = 60  # BirdNet analysis request timeout (seconds) - increased for warmup
BIRDNET_MAX_RETRIES = 5       # Max retries for BirdNet connection errors
BIRDNET_RETRY_BASE_DELAY = 2  # Base delay for exponential backoff (seconds)
RECORDING_THREAD_SHUTDOWN_TIMEOUT = 10  # Max wait for recording thread (seconds)
PROCESSING_THREAD_SHUTDOWN_TIMEOUT = 5  # Max wait for processing thread (seconds)

# Setup logging
setup_logging('main')
logger = get_logger(__name__)

# Initialize the database manager
db_manager = DatabaseManager()

# Global flag to signal all threads to stop
stop_flag = threading.Event()

# Ensure directories exist
for dir in [RECORDING_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR]:
    os.makedirs(dir, exist_ok=True)

def setup_recorder(recording_mode: str, thread_logger) -> BaseRecorder:
    """Create and configure audio recorder based on recording mode.

    Args:
        recording_mode: 'pulseaudio', 'http_stream', or 'rtsp'
        thread_logger: Logger instance for this thread

    Returns:
        Configured recorder instance
    """
    # Log startup info based on mode
    if recording_mode == 'pulseaudio':
        thread_logger.info("Starting PulseAudio recording", extra={
            'pulseaudio_source': PULSEAUDIO_SOURCE,
            'chunk_duration': RECORDING_LENGTH,
            'output_dir': RECORDING_DIR
        })
    elif recording_mode == 'rtsp':
        thread_logger.info("Starting RTSP stream recording", extra={
            'rtsp_url': sanitize_url(RTSP_URL),
            'chunk_duration': RECORDING_LENGTH,
            'output_dir': RECORDING_DIR
        })
    else:  # http_stream
        thread_logger.info("Starting HTTP stream recording", extra={
            'stream_url': STREAM_URL,
            'chunk_duration': RECORDING_LENGTH,
            'output_dir': RECORDING_DIR
        })

    # Delegate to audio_manager factory
    return create_recorder(
        recording_mode=recording_mode,
        chunk_duration=RECORDING_LENGTH,
        output_dir=RECORDING_DIR,
        target_sample_rate=SAMPLE_RATE,
        source_name=PULSEAUDIO_SOURCE,
        stream_url=STREAM_URL,
        rtsp_url=RTSP_URL
    )

def continuous_audio_recording(thread_logger):
    """Continuous audio recording from PulseAudio or HTTP stream.

    This thread ONLY manages the recorder (FFmpeg). It does not scan for files
    or queue them - that's the processing thread's job.
    """
    # Create recorder
    recorder = setup_recorder(RECORDING_MODE, thread_logger)

    try:
        recorder.start()

        while not stop_flag.is_set():
            try:
                # Check recorder health and restart if needed
                if not recorder.is_healthy():
                    thread_logger.warning("Recorder unhealthy, restarting...")
                    recorder.restart()

                # Brief sleep to prevent CPU thrashing
                time.sleep(FILE_SCAN_INTERVAL)

            except Exception as e:
                thread_logger.error("Recording loop error", extra={
                    'error': str(e)
                }, exc_info=True)
                time.sleep(1)

    finally:
        # Always clean up on exit
        thread_logger.info("Stopping audio recording")
        recorder.stop()

def extract_detection_audio(detection: Dict[str, Any], input_file_path: str) -> str:
    """Extract audio segment for detection and convert to MP3.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file

    Returns:
        Path to the MP3 file
    """
    step_seconds = detection.get('step_seconds', ANALYSIS_CHUNK_LENGTH)
    audio_segments_indices = select_audio_chunks(
        detection['chunk_index'], detection['total_chunks'])
    start_time = audio_segments_indices[0] * step_seconds
    end_time = audio_segments_indices[1] * step_seconds + ANALYSIS_CHUNK_LENGTH

    wav_path = os.path.join(EXTRACTED_AUDIO_DIR, detection['bird_song_file_name'])
    mp3_path = wav_path.replace('.wav', '.mp3')

    trim_audio(input_file_path, wav_path, start_time, end_time)
    convert_wav_to_mp3(wav_path, mp3_path)
    os.remove(wav_path)

    return mp3_path


def create_detection_spectrogram(detection: Dict[str, Any], input_file_path: str) -> str:
    """Generate spectrogram image for detection.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file

    Returns:
        Path to the spectrogram image
    """
    step_seconds = detection.get('step_seconds', ANALYSIS_CHUNK_LENGTH)
    spectrogram_path = os.path.join(SPECTROGRAM_DIR, detection['spectrogram_file_name'])

    title = f"{detection['common_name']} ({detection['confidence']:.2f}) - {detection['timestamp']}"
    start_time = step_seconds * detection['chunk_index']
    end_time = start_time + ANALYSIS_CHUNK_LENGTH

    generate_spectrogram(input_file_path, spectrogram_path, title,
                        start_time=start_time, end_time=end_time)
    return spectrogram_path


def save_detection_to_db(detection: Dict[str, Any]) -> None:
    """Insert detection record into database.

    Args:
        detection: Detection dictionary from BirdNet analysis
    """
    db_manager.insert_detection({
        'timestamp': detection['timestamp'],
        'group_timestamp': detection['group_timestamp'],
        'scientific_name': detection['scientific_name'],
        'common_name': detection['common_name'],
        'confidence': detection['confidence'],
        'latitude': detection['latitude'],
        'longitude': detection['longitude'],
        'cutoff': detection['cutoff'],
        'sensitivity': detection['sensitivity'],
        'overlap': detection['overlap'],
        'extra': detection.get('extra', {})
    })


def broadcast_detection(detection: Dict[str, Any], thread_logger) -> None:
    """Send detection to WebSocket clients via API.

    Args:
        detection: Detection dictionary from BirdNet analysis
        thread_logger: Logger instance for this thread
    """
    try:
        detection_data = {
            'timestamp': detection['timestamp'],
            'common_name': detection['common_name'],
            'scientific_name': detection['scientific_name'],
            'confidence': detection['confidence'],
            'bird_song_file_name': detection['bird_song_file_name'].replace('.wav', '.mp3'),
            'spectrogram_file_name': detection['spectrogram_file_name']
        }
        requests.post(
            f'http://{API_HOST}:{API_PORT}/api/broadcast/detection',
            json=detection_data,
            timeout=BROADCAST_TIMEOUT
        )
        thread_logger.debug("Detection broadcasted via WebSocket", extra={
            'species': detection['common_name']
        })
    except Exception as e:
        thread_logger.warning("Failed to broadcast detection", extra={
            'species': detection['common_name'],
            'error': str(e)
        })


def handle_detection(detection: Dict[str, Any], input_file_path: str, thread_logger) -> None:
    """Process a single bird detection: create audio, spectrogram, save to DB, broadcast.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file
        thread_logger: Logger instance for this thread
    """
    thread_logger.info("🐦 Bird detected", extra={
        'species': detection['common_name'],
        'confidence': round(detection['confidence'] * 100),
        'time': detection['timestamp'].split('T')[1].split('.')[0]
    })

    extract_detection_audio(detection, input_file_path)
    create_detection_spectrogram(detection, input_file_path)

    # Attach weather data if location is configured (explicit None check for 0-coordinate support)
    if LOCATION_CONFIGURED and LAT is not None and LON is not None:
        weather_service = get_weather_service()
        weather_data, weather_error = weather_service.get_current_weather(LAT, LON)
        if weather_data:
            extra = detection.get('extra', {})
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except json.JSONDecodeError:
                    extra = {}
            extra['weather'] = weather_data
            detection['extra'] = extra
            thread_logger.debug("Weather attached to detection", extra={
                'species': detection['common_name'],
                'temp': weather_data.get('temp')
            })
        elif weather_error:
            thread_logger.debug("Weather fetch skipped", extra={
                'reason': weather_error
            })

    thread_logger.debug("Saving detection to database", extra={
        'species': detection['common_name'],
        'scientific_name': detection['scientific_name']
    })
    save_detection_to_db(detection)
    broadcast_detection(detection, thread_logger)

def is_valid_recording(file_path: str, thread_logger) -> bool:
    """Check if a recording file is valid (meets minimum duration).

    Args:
        file_path: Path to WAV file to validate
        thread_logger: Logger instance for this thread

    Returns:
        True if file is valid, False if too short (and should be deleted)
    """
    try:
        file_size = os.path.getsize(file_path)
        # Calculate duration: mono 16-bit = 2 bytes per sample
        actual_duration = file_size / (SAMPLE_RATE * 2)
        min_acceptable_size = SAMPLE_RATE * 2 * MIN_RECORDING_DURATION

        if file_size >= min_acceptable_size:
            return True
        else:
            thread_logger.warning("Recording too short, removing", extra={
                'file': os.path.basename(file_path),
                'size_bytes': file_size,
                'duration_seconds': round(actual_duration, 3),
                'expected_min_duration': MIN_RECORDING_DURATION
            })
            return False

    except OSError as e:
        thread_logger.error("Failed to validate file", extra={
            'file': os.path.basename(file_path),
            'error': str(e)
        })
        return False


def process_audio_files():
    """Processing thread: scans directory for .wav files and processes them.

    The filesystem IS the queue - no in-memory queue needed.
    Files are deleted after successful processing.
    """
    thread_logger = get_logger(f"{__name__}.processing")
    thread_logger.info("Processing thread started")

    while not stop_flag.is_set():
        try:
            # Scan directory for .wav files (sorted by name = chronological order)
            files = sorted(glob.glob(os.path.join(RECORDING_DIR, "*.wav")))

            for file_path in files:
                if stop_flag.is_set():
                    break

                file_name = os.path.basename(file_path)

                # Validate file size/duration
                if not is_valid_recording(file_path, thread_logger):
                    # File too short - delete it
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass  # File might have been removed already
                    continue

                # Log that we're processing this file
                thread_logger.info("🔴 Processing recording", extra={
                    'file': file_name
                })

                # Process the audio file via BirdNet
                detections = process_audio_file(file_path)
                if detections:
                    for detection in detections:
                        handle_detection(detection, file_path, thread_logger)

                # Clean up processed file
                thread_logger.debug("Audio file processed", extra={
                    'file': file_name,
                    'detections': len(detections) if detections else 0
                })
                try:
                    os.remove(file_path)
                except OSError as e:
                    thread_logger.warning("Failed to delete processed file", extra={
                        'file': file_name,
                        'error': str(e)
                    })

            # Sleep before next scan (only if no files were found)
            if not files:
                time.sleep(FILE_SCAN_INTERVAL)

        except Exception as e:
            thread_logger.error("Processing error", extra={
                'error': str(e)
            }, exc_info=True)
            time.sleep(1)

def process_audio_file(audio_file_path: str) -> List[Dict[str, Any]]:
    """Send audio file to BirdNet service for analysis.

    Includes retry logic with exponential backoff for connection errors,
    which can occur during server startup (warmup period).
    """
    payload = {'audio_file_path': audio_file_path}
    file_name = os.path.basename(audio_file_path)

    for attempt in range(BIRDNET_MAX_RETRIES):
        try:
            response = requests.post(
                BIRDNET_SERVER_ENDPOINT,
                json=payload,
                timeout=BIRDNET_REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                detections = response.json()
                logger.debug("BirdNet analysis complete", extra={
                    'file': file_name,
                    'detections_count': len(detections)
                })
                return detections
            else:
                logger.error("BirdNet service error", extra={
                    'file': file_name,
                    'status_code': response.status_code,
                    'response': response.text[:200]
                })
                return []

        except requests.exceptions.ConnectionError as e:
            # Server not ready yet (still warming up) - retry with backoff
            if attempt < BIRDNET_MAX_RETRIES - 1:
                wait_time = BIRDNET_RETRY_BASE_DELAY ** (attempt + 1)  # 2, 4, 8, 16, 32 seconds
                logger.warning("BirdNet service not ready, retrying", extra={
                    'file': file_name,
                    'attempt': attempt + 1,
                    'max_retries': BIRDNET_MAX_RETRIES,
                    'retry_in': wait_time
                })
                time.sleep(wait_time)
            else:
                logger.error("BirdNet service unavailable after retries", extra={
                    'file': file_name,
                    'attempts': BIRDNET_MAX_RETRIES,
                    'error': str(e)
                })
                return []

        except requests.exceptions.Timeout as e:
            # Request timed out - don't retry, server is likely overloaded
            logger.error("BirdNet service request timed out", extra={
                'file': file_name,
                'timeout': BIRDNET_REQUEST_TIMEOUT,
                'error': str(e)
            })
            return []

        except requests.RequestException as e:
            logger.error("BirdNet service request failed", extra={
                'file': file_name,
                'error': str(e)
            })
            return []

        except Exception as e:
            logger.error("Unexpected error calling BirdNet service", extra={
                'file': file_name,
                'error': str(e)
            }, exc_info=True)
            return []

    return []  # Should not reach here, but safety fallback

def shutdown():
    logger.info("Shutdown initiated")
    stop_flag.set()  # Signal all threads to stop

    # Give recording thread more time to finish current recording
    recording_thread.join(timeout=RECORDING_THREAD_SHUTDOWN_TIMEOUT)

    # Processing thread can finish faster
    processing_thread.join(timeout=PROCESSING_THREAD_SHUTDOWN_TIMEOUT)

    # If threads are still alive, they're blocked; force stop them
    if recording_thread.is_alive():
        logger.warning("Recording thread did not stop cleanly")
    if processing_thread.is_alive():
        logger.warning("Processing thread did not stop cleanly")

    logger.info("Shutdown complete")

def signal_handler(signum, _):
    """Handle shutdown signals gracefully"""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal, initiating graceful shutdown")
    shutdown()

if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)  # Docker stop
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    
    logger.info(f"🎵 {DISPLAY_NAME} v{__version__} starting", extra={
        'recording_dir': RECORDING_DIR,
        'recording_length': RECORDING_LENGTH,
        'analysis_chunk_length': ANALYSIS_CHUNK_LENGTH
    })

    # Start the recording thread
    recording_logger = get_logger(f"{__name__}.recording")
    recording_thread = threading.Thread(
        target=continuous_audio_recording,
        args=(recording_logger,),
        name="RecordingThread"
    )
    recording_thread.start()
    logger.info("Recording thread started")

    # Start the processing thread
    processing_thread = threading.Thread(target=process_audio_files, name="ProcessingThread")
    processing_thread.start()
    logger.info("Processing thread started")

    # Start the storage monitor thread
    storage_thread = threading.Thread(
        target=storage_monitor_loop,
        args=(stop_flag, db_manager),
        name="StorageThread"
    )
    storage_thread.start()
    logger.info("Storage monitor thread started")

    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        # Signal handler will handle this
        pass
