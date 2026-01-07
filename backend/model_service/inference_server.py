"""Inference server for bird detection models.

This module provides a Flask API for analyzing audio files using the configured
bird detection model. It supports multiple model types through the factory pattern.
"""

from config import settings
import datetime
import warnings
import numpy as np
# Suppress NumPy floating point limit warnings
warnings.filterwarnings('ignore', category=UserWarning, module='numpy.core.getlimits')
from flask import Flask, request, jsonify
from scipy.io import wavfile
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.logging_config import setup_logging, get_logger, log_execution_time
from core.utils import build_detection_filenames
from .model_factory import create_model, get_model_type_from_settings
from .base_model import BirdDetectionModel


app = Flask(__name__)

# Setup logging
setup_logging('birdnet')
logger = get_logger(__name__)

# Load the model using factory pattern
logger.info("Loading bird detection model", extra={
    'model_type': get_model_type_from_settings().value
})

try:
    model = create_model(get_model_type_from_settings())
    model.load()
    logger.info("Model loaded successfully", extra={
        'model_name': model.name,
        'model_version': model.version,
        'num_species': len(model.get_labels())
    })
except Exception as e:
    logger.error("Failed to load model", exc_info=True)
    raise


def get_scientific_name(label: str) -> str:
    """Extract scientific name from full species label.

    Args:
        label: Full species label (e.g., "Turdus migratorius_American Robin")

    Returns:
        Scientific name (e.g., "Turdus migratorius")
    """
    parts = label.split('_', 1)
    return parts[0] if len(parts) == 2 else label


def get_common_name(label: str) -> str:
    """Extract common name from full species label."""
    parts = label.split('_', 1)
    return parts[1] if len(parts) == 2 else label


def split_audio(path, chunk_length, sample_rate, total_duration, overlap=0.0, minlen=1.5):
    """
    Split audio file into chunks for analysis, with optional overlap.

    Compatible with BirdNET-Pi's splitSignal() behavior:
    - Step size = chunk_length - overlap
    - Chunks shorter than minlen are discarded
    - Chunks between minlen and chunk_length are zero-padded

    Args:
        path: Path to audio file
        chunk_length: Duration of each chunk in seconds (e.g., 3)
        sample_rate: Sample rate in Hz (e.g., 48000)
        total_duration: Expected total duration in seconds (e.g., 9)
        overlap: Overlap between chunks in seconds (0.0 to 2.5)
        minlen: Minimum chunk length to keep (default 1.5s)

    Returns:
        List of audio chunks, each exactly chunk_length * sample_rate samples
    """
    file_name = os.path.basename(path)

    # Load audio using scipy (fast, no JIT warmup needed)
    # Audio files are already 48kHz mono WAV from the recorder
    load_start = time.time()
    rate, sig = wavfile.read(path)
    # Convert int16 to float32 in range [-1, 1] (same as librosa output)
    sig = sig.astype(np.float32) / 32768.0
    load_time = time.time() - load_start
    logger.debug("Audio loaded", extra={
        'file': file_name,
        'load_time': round(load_time, 3),
        'samples': len(sig),
        'sample_rate': rate
    })

    # Calculate target samples for normalization
    target_samples = int(total_duration * rate)
    original_samples = len(sig)
    original_duration = original_samples / rate

    # Normalize audio to exact target duration (trim or pad)
    if original_samples > target_samples:
        # Trim excess from end
        trimmed_ms = (original_samples - target_samples) / rate * 1000
        sig = sig[:target_samples]
        logger.debug("Audio trimmed to target duration", extra={
            'file': file_name,
            'original_duration': round(original_duration, 3),
            'target_duration': total_duration,
            'trimmed_ms': round(trimmed_ms, 1)
        })
    elif original_samples < target_samples:
        # Pad with zeros at end
        padding_samples = target_samples - original_samples
        padding_ms = padding_samples / rate * 1000
        padding_percent = (padding_samples / target_samples) * 100
        sig = np.pad(sig, (0, padding_samples), mode='constant')

        # Log if padding is significant (>1% of total duration)
        if padding_percent > 1.0:
            logger.info("Audio padded to target duration", extra={
                'file': file_name,
                'original_duration': round(original_duration, 3),
                'target_duration': total_duration,
                'padding_ms': round(padding_ms, 1),
                'padding_percent': round(padding_percent, 2)
            })

    # Calculate step size and chunk size in samples
    chunk_size = int(chunk_length * rate)
    step_size = int((chunk_length - overlap) * rate)
    minlen_samples = int(minlen * rate)

    # Split into chunks with overlap (BirdNET-Pi compatible)
    chunks = []
    for i in range(0, len(sig), step_size):
        split = sig[i:i + chunk_size]

        # Check if chunk is too short
        if len(split) < minlen_samples:
            # End of signal - chunk too short, discard
            break

        # Pad short chunks (>= minlen but < chunk_length) with zeros
        if len(split) < chunk_size:
            padded = np.zeros(chunk_size, dtype=sig.dtype)
            padded[:len(split)] = split
            split = padded

        chunks.append(split)

    # Log chunk info with overlap details
    if overlap > 0:
        logger.debug("Audio split with overlap", extra={
            'file': file_name,
            'overlap': overlap,
            'step_size': round(chunk_length - overlap, 2),
            'chunks': len(chunks)
        })

    return chunks


def build_detection_result(species, chunk_index, total_chunks, step_seconds,
                          file_timestamp, source_file_name, lat, lon,
                          cutoff, sensitivity, overlap, model: BirdDetectionModel):
    """Build a detection result dictionary for a single species detection.

    Args:
        species: Tuple of (species_label, confidence) from model output
        chunk_index: Index of the audio chunk
        total_chunks: Total number of chunks in the audio file
        step_seconds: Step size in seconds (accounts for overlap)
        file_timestamp: Datetime of the source file
        source_file_name: Name of the source audio file
        lat, lon: Location coordinates
        cutoff, sensitivity, overlap: Analysis parameters
        model: The bird detection model instance

    Returns:
        Detection result dictionary
    """
    scientific_name = get_scientific_name(species[0])
    common_name = get_common_name(species[0])
    confidence = float(species[1])

    start_timestamp = file_timestamp + datetime.timedelta(seconds=chunk_index * step_seconds)

    filenames = build_detection_filenames(
        common_name,
        confidence,
        start_timestamp,
        audio_extension='wav'
    )

    return {
        # Fields in the database schema
        "timestamp": start_timestamp.isoformat(),
        "group_timestamp": file_timestamp.isoformat(),
        "scientific_name": scientific_name,
        "common_name": common_name,
        "confidence": confidence,
        "latitude": float(lat),
        "longitude": float(lon),
        "cutoff": float(cutoff),
        "sensitivity": float(sensitivity),
        "overlap": float(overlap),
        "extra": {
            "ebird_code": model.get_ebird_code(scientific_name),
            "model": model.name,
            "model_version": model.version
        },

        # Additional fields not in the database schema
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "step_seconds": step_seconds,
        "bird_song_file_name": filenames['audio_filename'],
        "spectrogram_file_name": filenames['spectrogram_filename'],
        "bird_song_duration": model.chunk_length_seconds,
        "source_file_name": source_file_name,
    }


@log_execution_time
def process_audio_file(model: BirdDetectionModel, audio_file_path, lat, lon, week, sensitivity, cutoff):
    """Process an audio file and return detected species.

    Args:
        model: The bird detection model instance
        audio_file_path: Path to the audio file to analyze
        lat, lon: Location coordinates for species filtering
        week: ISO week number for species filtering
        sensitivity: Confidence adjustment parameter
        cutoff: Minimum confidence threshold

    Returns:
        List of detection result dictionaries
    """
    # Time meta model inference for location filtering
    meta_start = time.time()
    local_species_list = model.filter_by_location(lat, lon, week)
    meta_time = time.time() - meta_start

    if local_species_list is not None:
        logger.debug("Location filter applied", extra={
            'meta_time': round(meta_time, 3),
            'local_species_count': len(local_species_list)
        })
    else:
        logger.debug("Location filtering not supported by model", extra={
            'model': model.name
        })

    # Get overlap and chunk length from settings/model
    overlap = settings.OVERLAP
    chunk_length = model.chunk_length_seconds

    # Time audio loading and splitting
    split_start = time.time()
    audio_chunks = split_audio(
        audio_file_path, chunk_length, model.sample_rate,
        settings.RECORDING_LENGTH, overlap=overlap)
    split_time = time.time() - split_start
    logger.debug("Audio split complete", extra={
        'split_time': round(split_time, 3),
        'chunks': len(audio_chunks)
    })

    # Calculate step size for timestamp calculation (BirdNET-Pi compatible)
    step_seconds = chunk_length - overlap

    logger.info("Starting audio analysis", extra={
        'file': os.path.basename(audio_file_path),
        'chunks': len(audio_chunks),
        'overlap': overlap,
        'sensitivity': sensitivity,
        'cutoff': cutoff
    })

    results = []
    detections_count = 0
    chunks_with_detections = 0

    # Parse file timestamp once before loop (constant value)
    source_file_name = os.path.basename(audio_file_path)
    file_timestamp_str = source_file_name.split('.')[0]
    file_timestamp = datetime.datetime.strptime(file_timestamp_str, "%Y%m%d_%H%M%S")

    # Get filter lists from settings
    allowed_species = settings.ALLOWED_SPECIES
    blocked_species = settings.BLOCKED_SPECIES

    # Time inference loop
    inference_start = time.time()
    for chunk_index, audio_chunk in enumerate(audio_chunks):
        # Run model inference (includes cutoff filtering and human detection)
        species_in_audio_chunk = model.predict(
            audio_chunk, sensitivity, cutoff, chunk_index=chunk_index)
        if species_in_audio_chunk:
            chunks_with_detections += 1

        # Apply species filters (3-tier logic)
        filtered_species_list = []
        for species_detection in species_in_audio_chunk:
            species_label = species_detection[0]  # e.g., "Turdus_migratorius_American Robin"
            scientific_name = get_scientific_name(species_label)  # e.g., "Turdus migratorius"

            # Rule 1: Blocked species are always rejected
            if blocked_species and scientific_name in blocked_species:
                logger.debug("Species blocked", extra={'species': scientific_name})
                continue

            # Rule 2: If allowed_species is set, only detect those (bypasses location filter)
            if allowed_species:
                if scientific_name in allowed_species:
                    filtered_species_list.append(species_detection)
                else:
                    logger.debug("Species not in allowed list", extra={'species': scientific_name})
                continue

            # Rule 3: Normal mode - use location-based meta-model filter
            if local_species_list is None:
                # Model doesn't support location filtering, accept all
                filtered_species_list.append(species_detection)
            elif species_label in local_species_list:
                filtered_species_list.append(species_detection)
            else:
                logger.debug("Species not in local species list", extra={'species': scientific_name})

        if filtered_species_list:
            species_info = [(get_common_name(s[0]), round(s[1]*100)) for s in filtered_species_list]
            logger.debug(f"Chunk {chunk_index}/{len(audio_chunks)-1} analyzed", extra={
                'detections': len(filtered_species_list),
                'species': species_info[0] if species_info else None
            })

        for species in filtered_species_list:
            result = build_detection_result(
                species, chunk_index, len(audio_chunks), step_seconds,
                file_timestamp, source_file_name, lat, lon,
                cutoff, sensitivity, overlap, model
            )
            results.append(result)
            detections_count += 1

            # Log each confirmed detection
            logger.info("Bird detected", extra={
                'species': result['common_name'],
                'confidence': round(result['confidence'] * 100),
                'chunk': chunk_index,
                'time': result['timestamp']
            })

    # Log inference loop timing
    inference_time = time.time() - inference_start
    logger.debug("Inference complete", extra={
        'inference_time': round(inference_time, 3),
        'chunks': len(audio_chunks),
        'avg_per_chunk': round(inference_time / len(audio_chunks), 3) if audio_chunks else 0
    })

    # Summary log
    log_extra = {
        'file': source_file_name,
        'total_detections': detections_count,
        'chunks_analyzed': len(audio_chunks)
    }

    # Add detection rate if there were any detections
    if detections_count > 0:
        log_extra['detection_rate'] = round(chunks_with_detections / len(audio_chunks) * 100, 1) if audio_chunks else 0

    logger.info("Analysis complete", extra=log_extra)

    return results


@app.route('/api/analyze_audio_file', methods=['POST'])
def analyze_audio_file():
    start_time = time.time()
    try:
        data = request.json
        audio_file_path = data['audio_file_path']

        # Validate path is within allowed directory (prevent path traversal)
        allowed_dir = os.path.realpath(settings.RECORDING_DIR)
        resolved_path = os.path.realpath(audio_file_path)
        if not resolved_path.startswith(allowed_dir + os.sep):
            logger.warning("Path traversal attempt blocked", extra={
                'requested_path': audio_file_path,
                'resolved_path': resolved_path
            })
            return jsonify({"error": "Invalid file path"}), 400

        # Validate file exists before processing
        if not os.path.exists(resolved_path):
            logger.warning("Audio file not found", extra={
                'file': os.path.basename(audio_file_path)
            })
            return jsonify({"error": f"File not found: {audio_file_path}"}), 404

        week = datetime.datetime.now().isocalendar()[1]

        # Get current settings from config
        lat = settings.LAT
        lon = settings.LON
        sensitivity = settings.SENSITIVITY
        cutoff = settings.CUTOFF

        logger.info("Audio analysis request received", extra={
            'file': os.path.basename(audio_file_path),
            'lat': lat,
            'lon': lon,
            'sensitivity': sensitivity,
            'cutoff': cutoff
        })

        # Process audio file (model handles thread safety internally)
        results = process_audio_file(model, resolved_path, lat, lon, week, sensitivity, cutoff)

        processing_time = time.time() - start_time
        logger.info("Request completed", extra={
            'file': os.path.basename(audio_file_path),
            'detections': len(results),
            'processing_time': round(processing_time, 2)
        })

        return jsonify(results)
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error("Audio processing failed", extra={
            'file': os.path.basename(audio_file_path) if 'audio_file_path' in locals() else 'unknown',
            'processing_time': round(processing_time, 2),
            'error': str(e)
        }, exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logger.info("Inference service starting", extra={
        'port': settings.BIRDNET_SERVICE_PORT,
        'model': model.name,
        'model_version': model.version
    })
    app.run(host='0.0.0.0', debug=False, port=settings.BIRDNET_SERVICE_PORT)
