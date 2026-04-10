"""Inference server for bird detection models.

This module provides a Flask API for analyzing audio files using the configured
bird detection model. It supports multiple model types through the factory pattern.
"""

import datetime
import warnings

import numpy as np

from config import settings
from config.constants import (
    DEFAULT_GEOMODEL_FILTER_THRESHOLD,
    DEFAULT_SPECIES_FILTER_THRESHOLD,
    ModelType,
)

# Suppress NumPy floating point limit warnings
warnings.filterwarnings('ignore', category=UserWarning, module='numpy.core.getlimits')
import os
import sys
import time

from flask import Flask, jsonify, request
from scipy.io import wavfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.logging_config import get_logger, log_execution_time, setup_logging
from core.runtime_config import get_runtime_settings
from core.timezone_service import get_timezone_str
from core.utils import build_detection_filenames
from model_service.base_model import BirdDetectionModel
from model_service.label_utils import get_common_name, get_scientific_name
from model_service.location_filter import (
    GeoModelFilter,
    LocationFilter,
    ModelBackedFilter,
)
from model_service.model_factory import (
    create_location_filter,
    create_model,
    get_model_type_from_settings,
)

app = Flask(__name__)

# Setup logging
setup_logging('birdnet')
logger = get_logger(__name__)

# Load the model using factory pattern
logger.info("Loading bird detection model", extra={
    'model_type': get_model_type_from_settings().value
})

try:
    model_type = get_model_type_from_settings()
    model = create_model(model_type)
    model.load()
    logger.info("Model loaded successfully", extra={
        'model_name': model.name,
        'model_version': model.version,
        'num_species': len(model.get_labels())
    })
except Exception:
    logger.error("Failed to load model", exc_info=True)
    raise

# Create location filter (factory owns load + fallback)
location_filter = create_location_filter(model_type, model=model)

# Log location filter configuration
if isinstance(location_filter, GeoModelFilter):
    _filter_desc = 'standalone geomodel (ONNX)'
elif isinstance(location_filter, ModelBackedFilter):
    _filter_desc = 'embedded meta model (TFLite)'
else:
    _filter_desc = 'disabled'

logger.info("Location filter initialized", extra={
    'filter_type': _filter_desc,
    'model_type': model_type.value,
})


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


def _is_input_shape_mismatch_error(error: Exception) -> bool:
    """Return True when model inference failed due to tensor input shape mismatch."""
    message = str(error)
    return (
        isinstance(error, ValueError)
        and "Cannot set tensor" in message
        and "Dimension mismatch" in message
    )


@log_execution_time
def process_audio_file(
    model: BirdDetectionModel,
    location_filter: LocationFilter,
    audio_file_path,
    lat,
    lon,
    sensitivity,
    cutoff,
    overlap: float,
    recording_length: float,
    allowed_species: list[str] | None,
    blocked_species: list[str] | None,
    species_filter_threshold: float = DEFAULT_SPECIES_FILTER_THRESHOLD
):
    """Process an audio file and return detected species.

    Args:
        model: The bird detection model instance
        location_filter: Location-based species filter
        audio_file_path: Path to the audio file to analyze
        lat, lon: Location coordinates for species filtering
        sensitivity: Confidence adjustment parameter
        cutoff: Minimum confidence threshold

    Returns:
        List of detection result dictionaries
    """
    # Parse file timestamp from filename (used for location filtering and detection records)
    source_file_name = os.path.basename(audio_file_path)
    file_timestamp_str = source_file_name.split('.')[0]
    file_timestamp = datetime.datetime.strptime(file_timestamp_str, "%Y%m%d_%H%M%S")

    # Location-based species filtering (uses recording timestamp, not request time)
    meta_start = time.time()
    location_context = location_filter.filter(
        lat, lon, file_timestamp, threshold=species_filter_threshold
    )
    meta_time = time.time() - meta_start

    if location_context.allowed_species is not None:
        logger.debug("Location filter applied", extra={
            'meta_time': round(meta_time, 3),
            'local_species_count': len(location_context.allowed_species),
            'location_source': location_context.source,
            'filter_threshold': round(location_context.threshold * 100, 1),
        })
    else:
        logger.debug("Location filtering not available", extra={
            'model': model.name,
            'location_source': location_context.source,
        })

    # Get overlap and chunk length from runtime settings/model
    chunk_length = model.chunk_length_seconds

    # Time audio loading and splitting
    split_start = time.time()
    audio_chunks = split_audio(
        audio_file_path, chunk_length, model.sample_rate,
        recording_length, overlap=overlap)
    split_time = time.time() - split_start
    logger.debug("Audio split complete", extra={
        'split_time': round(split_time, 3),
        'chunks': len(audio_chunks)
    })

    # Calculate step size for timestamp calculation (BirdNET-Pi compatible)
    step_seconds = chunk_length - overlap

    logger.info("Starting audio analysis", extra={
        'file': source_file_name,
        'chunks': len(audio_chunks),
        'model': model.name,
        'model_version': model.version,
        'lat': lat,
        'lon': lon,
        'overlap': overlap,
        'sensitivity': sensitivity,
        'cutoff': cutoff,
        'species_filter_threshold': species_filter_threshold
    })

    results = []
    detections_count = 0
    chunks_with_detections = 0

    # Normalize optional filter lists
    allowed_species = allowed_species or []
    blocked_species = blocked_species or []

    # Pre-compute loop-invariant values
    loc_active = location_context.source != 'disabled'
    cutoff_pct = round(cutoff * 100, 1)
    threshold_pct = round(location_context.threshold * 100, 1) if loc_active else None

    # Time inference loop
    inference_start = time.time()
    for chunk_index, audio_chunk in enumerate(audio_chunks):
        # Run model inference (includes cutoff filtering and human detection)
        try:
            chunk_prediction = model.predict_chunk(
                audio_chunk, sensitivity, cutoff, chunk_index=chunk_index)
        except Exception as error:
            if _is_input_shape_mismatch_error(error):
                logger.warning("Skipping audio file due to model input shape mismatch", extra={
                    'file': os.path.basename(audio_file_path),
                    'chunk_index': chunk_index,
                    'chunk_samples': len(audio_chunk),
                    'expected_samples': int(model.chunk_length_seconds * model.sample_rate),
                    'model': model.name,
                    'model_version': model.version,
                    'error': str(error)
                })
                return []
            raise

        top3_info = []
        for label, confidence in chunk_prediction.raw_top3:
            entry = {
                'species': get_common_name(label),
                'confidence': round(confidence * 100, 1),
            }
            if loc_active:
                loc_prob = location_context.probability_for(label)
                entry['location_prob'] = (
                    round(loc_prob * 100, 1) if loc_prob is not None else 'unmapped'
                )
            top3_info.append(entry)

        chunk_log_extra = {
            'top3': top3_info,
            'cutoff': cutoff_pct,
        }
        if loc_active:
            chunk_log_extra['location_source'] = location_context.source
            chunk_log_extra['filter_threshold'] = threshold_pct
        if chunk_prediction.human_detected:
            chunk_log_extra['privacy_filtered'] = True
        logger.info(f"Chunk {chunk_index} raw model output", extra=chunk_log_extra)

        species_in_audio_chunk = chunk_prediction.candidates
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

            # Rule 3: Normal mode - use location-based filter
            if location_context.allowed_species is None:
                # Model doesn't support location filtering, accept all
                filtered_species_list.append(species_detection)
            elif species_label in location_context.allowed_species:
                filtered_species_list.append(species_detection)
            else:
                logger.debug("Species not in local species list", extra={'species': scientific_name})

        if filtered_species_list:
            species_info = [(get_common_name(s[0]), round(s[1]*100, 1)) for s in filtered_species_list]
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
            detection_extra = {
                'species': result['common_name'],
                'confidence': round(result['confidence'] * 100, 1),
                'chunk': chunk_index,
                'time': result['timestamp']
            }
            if loc_active:
                loc_prob = location_context.probability_for(species[0])
                detection_extra['location_source'] = location_context.source
                detection_extra['location_prob'] = round(loc_prob * 100, 1) if loc_prob is not None else 'unmapped'
            logger.info("Bird detected", extra=detection_extra)

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
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Invalid or missing JSON payload"}), 400
        if 'audio_file_path' not in data:
            return jsonify({"error": "Missing required field: audio_file_path"}), 400
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

        # Get current analysis settings from runtime config
        runtime_settings = get_runtime_settings()
        location_settings = runtime_settings.get('location', {})
        detection_settings = runtime_settings.get('detection', {})
        audio_settings = runtime_settings.get('audio', {})
        species_filter_settings = runtime_settings.get('species_filter', {})

        lat = location_settings.get('latitude')
        lon = location_settings.get('longitude')
        sensitivity = detection_settings.get('sensitivity', 0.75)
        cutoff = detection_settings.get('cutoff', 0.60)
        default_threshold = (
            DEFAULT_GEOMODEL_FILTER_THRESHOLD if model_type == ModelType.BIRDNET_V3
            else DEFAULT_SPECIES_FILTER_THRESHOLD
        )
        species_filter_threshold = detection_settings.get('species_filter_threshold', default_threshold)
        overlap = audio_settings.get('overlap', 0.0)
        recording_length = audio_settings.get('recording_length', 9)
        allowed_species = species_filter_settings.get('allowed_species') or []
        blocked_species = species_filter_settings.get('blocked_species') or []

        requested_model_type = runtime_settings.get('model', {}).get('type', settings.MODEL_TYPE)
        if requested_model_type != settings.MODEL_TYPE:
            logger.warning("Model type changed in settings; full restart required", extra={
                'loaded_model_type': settings.MODEL_TYPE,
                'requested_model_type': requested_model_type
            })

        logger.info("Audio analysis request received", extra={
            'file': os.path.basename(audio_file_path),
            'lat': lat,
            'lon': lon,
            'sensitivity': sensitivity,
            'cutoff': cutoff,
            'species_filter_threshold': species_filter_threshold,
            'overlap': overlap
        })

        # Process audio file (model and filter handle thread safety internally)
        results = process_audio_file(
            model,
            location_filter,
            resolved_path,
            lat,
            lon,
            sensitivity,
            cutoff,
            overlap,
            recording_length,
            allowed_species,
            blocked_species,
            species_filter_threshold
        )

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
        'model_version': model.version,
        'num_species': len(model.get_labels()),
        'location_filter': _filter_desc,
        'timezone': get_timezone_str()
    })
    app.run(host='0.0.0.0', debug=False, port=settings.BIRDNET_SERVICE_PORT)
