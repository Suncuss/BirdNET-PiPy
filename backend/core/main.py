from config.settings import (
    RECORDING_DIR, RECORDING_LENGTH, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR,
    BIRDNET_SERVER_ENDPOINT, ANALYSIS_CHUNK_LENGTH, API_PORT, API_HOST, SAMPLE_RATE,
    RECORDING_MODE, PULSEAUDIO_SOURCE, STREAM_URL
)
from core.db import DatabaseManager
from core.utils import generate_spectrogram, trim_audio, select_audio_chunks, convert_wav_to_mp3
from core.audio_manager import HttpStreamRecorder, PulseAudioRecorder
from core.logging_config import setup_logging, get_logger
from version import __version__, DISPLAY_NAME

import os
import time
import glob
import threading
import requests
from typing import List, Dict, Any, Union
import signal

# Configuration constants
MIN_RECORDING_DURATION = 5.0  # Minimum acceptable recording duration in seconds
FILE_SCAN_INTERVAL = 2.0      # How often to scan for new recordings (seconds)
BROADCAST_TIMEOUT = 5         # WebSocket broadcast request timeout (seconds)
BIRDNET_REQUEST_TIMEOUT = 30  # BirdNet analysis request timeout (seconds)
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

def create_recorder(recording_mode: str, thread_logger) -> Union[PulseAudioRecorder, HttpStreamRecorder]:
    """Create and configure audio recorder based on recording mode.

    Args:
        recording_mode: Either 'pulseaudio' or 'http_stream'
        thread_logger: Logger instance for this thread

    Returns:
        Configured recorder instance
    """
    if recording_mode == 'pulseaudio':
        thread_logger.info("Starting PulseAudio recording", extra={
            'pulseaudio_source': PULSEAUDIO_SOURCE,
            'chunk_duration': RECORDING_LENGTH,
            'output_dir': RECORDING_DIR
        })
        return PulseAudioRecorder(
            source_name=PULSEAUDIO_SOURCE,
            chunk_duration=RECORDING_LENGTH,
            output_dir=RECORDING_DIR,
            target_sample_rate=SAMPLE_RATE
        )
    else:  # http_stream
        thread_logger.info("Starting HTTP stream recording", extra={
            'stream_url': STREAM_URL,
            'chunk_duration': RECORDING_LENGTH,
            'output_dir': RECORDING_DIR
        })
        return HttpStreamRecorder(
            stream_url=STREAM_URL,
            chunk_duration=RECORDING_LENGTH,
            output_dir=RECORDING_DIR,
            target_sample_rate=SAMPLE_RATE
        )

def continuous_audio_recording(thread_logger):
    """Continuous audio recording from PulseAudio or HTTP stream.

    This thread ONLY manages the recorder (FFmpeg). It does not scan for files
    or queue them - that's the processing thread's job.
    """
    # Create recorder
    recorder = create_recorder(RECORDING_MODE, thread_logger)

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

def handle_detection(detection: Dict[str, Any], input_file_path: str, thread_logger) -> None:
    """Process a single bird detection: create audio, spectrogram, save to DB, broadcast.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file
        thread_logger: Logger instance for this thread
    """
    # Log the detection (main user-facing log)
    thread_logger.info("🐦 Bird detected", extra={
        'species': detection['common_name'],
        'confidence': round(detection['confidence'] * 100),
        'time': detection['timestamp'].split('T')[1].split('.')[0]
    })

    # Calculate the start and end time of the audio chunk
    audio_segments_indices = select_audio_chunks(
        detection['chunk_index'], detection['total_chunks'])
    start_time = audio_segments_indices[0] * ANALYSIS_CHUNK_LENGTH
    end_time = (audio_segments_indices[1] + 1) * ANALYSIS_CHUNK_LENGTH

    bird_song_file_path = os.path.join(
        EXTRACTED_AUDIO_DIR, detection['bird_song_file_name'])
    spectrogram_file_path = os.path.join(
        SPECTROGRAM_DIR, detection['spectrogram_file_name'])

    # Extract audio and generate spectrogram
    trim_audio(input_file_path, bird_song_file_path, start_time, end_time)
    spectrogram_title = f"{detection['common_name']} ({detection['confidence']:.2f}) - {detection['timestamp']}"
    generate_spectrogram(input_file_path, spectrogram_file_path, spectrogram_title,
                        start_time=ANALYSIS_CHUNK_LENGTH * detection['chunk_index'],
                        end_time=ANALYSIS_CHUNK_LENGTH * (detection['chunk_index'] + 1))

    # Convert to MP3 and cleanup WAV
    convert_wav_to_mp3(bird_song_file_path, bird_song_file_path.replace('.wav', '.mp3'))
    os.remove(bird_song_file_path)

    # Insert detection into the database
    thread_logger.debug("Saving detection to database", extra={
        'species': detection['common_name'],
        'scientific_name': detection['scientific_name']
    })
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
        'overlap': detection['overlap']
    })

    # Broadcast detection to WebSocket clients via HTTP request
    try:
        detection_data = {
            'id': detection.get('id'),
            'timestamp': detection['timestamp'],
            'common_name': detection['common_name'],
            'scientific_name': detection['scientific_name'],
            'confidence': detection['confidence'],
            'bird_song_file_name': detection['bird_song_file_name'].replace('.wav', '.mp3'),
            'spectrogram_file_name': detection['spectrogram_file_name']
        }
        requests.post(f'http://{API_HOST}:{API_PORT}/api/broadcast/detection',
                     json=detection_data, timeout=BROADCAST_TIMEOUT)
        thread_logger.debug("Detection broadcasted via WebSocket", extra={
            'species': detection['common_name']
        })
    except Exception as e:
        thread_logger.warning("Failed to broadcast detection", extra={
            'species': detection['common_name'],
            'error': str(e)
        })

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
    try:
        # Prepare the payload
        payload = {'audio_file_path': audio_file_path}

        # Send the POST request with timeout to prevent thread hang
        response = requests.post(BIRDNET_SERVER_ENDPOINT, json=payload, timeout=BIRDNET_REQUEST_TIMEOUT)

        # Check if the request was successful
        if response.status_code == 200:
            detections = response.json()
            logger.debug("BirdNet analysis complete", extra={
                'file': os.path.basename(audio_file_path),
                'detections_count': len(detections)
            })
            return detections
        else:
            logger.error("BirdNet service error", extra={
                'file': os.path.basename(audio_file_path),
                'status_code': response.status_code,
                'response': response.text[:200]
            })
            return []

    except requests.RequestException as e:
        logger.error("BirdNet service request failed", extra={
            'file': os.path.basename(audio_file_path),
            'error': str(e)
        })
        return []
    except Exception as e:
        logger.error("Unexpected error calling BirdNet service", extra={
            'file': os.path.basename(audio_file_path),
            'error': str(e)
        }, exc_info=True)
        return []

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

    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        # Signal handler will handle this
        pass
