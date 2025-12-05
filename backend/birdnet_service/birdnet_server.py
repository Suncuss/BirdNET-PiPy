from birdnet_service.model_loader import ModelLoader
from config import settings
import datetime
import warnings
import numpy as np
import threading
# Suppress NumPy floating point limit warnings
warnings.filterwarnings('ignore', category=UserWarning, module='numpy.core.getlimits')
from flask import Flask, request, jsonify
import librosa
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.logging_config import setup_logging, get_logger, log_execution_time
from core.utils import build_detection_filenames


app = Flask(__name__)

# Setup logging
setup_logging('birdnet')
logger = get_logger(__name__)

# Load the model at startup
model_config = {
    "model_path": settings.MODEL_PATH,
    "meta_model_path": settings.META_MODEL_PATH,
    "labels_path": settings.LABELS_PATH
}

logger.info("Loading BirdNet models", extra={
    'model_path': settings.MODEL_PATH,
    'meta_model_path': settings.META_MODEL_PATH
})

try:
    model_loader = ModelLoader(**model_config)
    model = model_loader.load_model()
    meta_model = model_loader.load_meta_model()
    labels = model_loader.load_labels()
    logger.info("Models loaded successfully", extra={
        'num_species': len(labels)
    })
except Exception as e:
    logger.error("Failed to load models", exc_info=True)
    raise

# Lock to serialize access to TFLite interpreters (not thread-safe)
inference_lock = threading.Lock()

# Minimum probability threshold for local species filtering (meta model)
SPECIES_FILTER_THRESHOLD = 0.03

# Warmup: Pre-compile librosa/numba JIT functions at startup
# This avoids ~50 second delay on first real request
logger.info("Warming up librosa (JIT compilation)...")
warmup_start = time.time()
try:
    # Create dummy audio at target sample rate
    dummy_audio = np.zeros(settings.SAMPLE_RATE, dtype='float32')
    # Trigger librosa's resampling JIT compilation
    _ = librosa.resample(dummy_audio, orig_sr=settings.SAMPLE_RATE, target_sr=settings.SAMPLE_RATE)
    warmup_time = time.time() - warmup_start
    logger.info("Warmup complete", extra={'warmup_time': round(warmup_time, 2)})
except Exception as e:
    logger.warning("Warmup failed (non-fatal)", extra={'error': str(e)})


def custom_sigmoid(x, sensitivity):
    """Apply custom sigmoid with adjustable sensitivity."""
    return 1 / (1.0 + np.exp(-sensitivity * x))


def get_probable_species_for_location(lat, lon, week, meta_model, labels):
    local_species = []

    meta_model_input = np.expand_dims(
        np.array([lat, lon, week], dtype='float32'), 0)
    meta_model.set_tensor(
        model_loader.meta_input_layer_index, meta_model_input)

    meta_model.invoke()

    # Use .copy() to avoid holding references to internal TFLite tensor data
    meta_model_output = meta_model.get_tensor(
        model_loader.meta_output_layer_index)[0].copy()
    meta_model_output = np.where(
        meta_model_output >= SPECIES_FILTER_THRESHOLD, meta_model_output, 0)
    meta_model_output = list(zip(meta_model_output, labels))
    meta_model_output = sorted(
        meta_model_output, key=lambda x: x[0], reverse=True)

    for species in meta_model_output:
        if species[0] >= SPECIES_FILTER_THRESHOLD:
            local_species.append(species[1])

    return local_species


def detect_species_in_audio(model, audio_input, labels, sensitivity, cutoff):

    model_input = np.array(np.expand_dims(audio_input, 0), dtype='float32')
    model.set_tensor(model_loader.input_layer_index, model_input)
    model.invoke()
    # Use .copy() to avoid holding references to internal TFLite tensor data
    model_output = model.get_tensor(model_loader.output_layer_index)[0].copy()

    model_output = custom_sigmoid(model_output, sensitivity)
    model_output = np.where(model_output >= cutoff, model_output, 0)
    model_output = dict(zip(labels, model_output))
    model_output = {k: v for k, v in model_output.items() if v != 0}
    model_output = sorted(model_output.items(),
                          key=lambda x: x[1], reverse=True)

    # Check for the prescence of Human
    human_detection = any('Human' in x[0] for x in model_output)
    if human_detection:
        logger.warning("Human detected in audio - chunk discarded for privacy")
        return []
    return model_output


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

    # Load audio (time this - librosa can be slow on first call due to JIT)
    load_start = time.time()
    sig, rate = librosa.load(path, sr=sample_rate, mono=True, res_type='kaiser_fast')
    load_time = time.time() - load_start
    logger.debug("Audio loaded with librosa", extra={
        'file': file_name,
        'load_time': round(load_time, 3),
        'samples': len(sig)
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


@log_execution_time
def process_audio_file(model, meta_model, audio_file_path, labels, lat, lon, week, sensitivity, cutoff):
    # Time meta model inference
    meta_start = time.time()
    local_species_list = get_probable_species_for_location(
        lat, lon, week, meta_model, labels)
    meta_time = time.time() - meta_start
    logger.debug("Meta model inference complete", extra={
        'meta_time': round(meta_time, 3),
        'local_species_count': len(local_species_list)
    })

    # Get overlap from settings
    overlap = settings.OVERLAP

    # Time audio loading and splitting
    split_start = time.time()
    audio_chunks = split_audio(
        audio_file_path, settings.ANALYSIS_CHUNK_LENGTH, settings.SAMPLE_RATE,
        settings.RECORDING_LENGTH, overlap=overlap)
    split_time = time.time() - split_start
    logger.debug("Audio split complete", extra={
        'split_time': round(split_time, 3),
        'chunks': len(audio_chunks)
    })

    # Calculate step size for timestamp calculation (BirdNET-Pi compatible)
    step_seconds = settings.ANALYSIS_CHUNK_LENGTH - overlap

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

    # Time TFLite inference loop
    inference_start = time.time()
    for chunk_index, audio_chunk in enumerate(audio_chunks):
        species_in_audio_chunk = detect_species_in_audio(
            model, audio_chunk, labels, sensitivity, cutoff)

        if species_in_audio_chunk:
            chunks_with_detections += 1

        if len(species_in_audio_chunk) > 1:
            logger.warning("Multiple species detected in single chunk", extra={
                'chunk_index': chunk_index,
                'species_count': len(species_in_audio_chunk),
                'species': [(s[0].split('_')[1], round(s[1]*100)) for s in species_in_audio_chunk[:3]]
            })

        if species_in_audio_chunk:
            species_info = [(s[0].split('_')[1], round(s[1]*100)) for s in species_in_audio_chunk]
            logger.debug(f"Chunk {chunk_index}/{len(audio_chunks)-1} analyzed", extra={
                'detections': len(species_in_audio_chunk),
                'species': species_info[0] if species_info else None
            })
        filtered_species_list = [
            x for x in species_in_audio_chunk if x[0] in local_species_list]

        # Use step_seconds for timestamp calculation (accounts for overlap)
        start_timestamp = file_timestamp + \
            datetime.timedelta(seconds=chunk_index * step_seconds)

        for species in filtered_species_list:
            scientific_name = species[0].split('_')[0]
            common_name = species[0].split('_')[1]
            confidence = float(species[1])

            # Generate standardized filenames using utility function
            filenames = build_detection_filenames(
                common_name,
                confidence,
                start_timestamp,
                audio_extension='wav'
            )

            results.append({
                # Fields in the database schema
                "timestamp": start_timestamp.isoformat(),
                "group_timestamp": file_timestamp.isoformat(),
                "scientific_name": scientific_name,
                "common_name": common_name,
                "confidence": float(confidence),
                "latitude": float(lat),
                "longitude": float(lon),
                "cutoff": float(cutoff),
                "sensitivity": float(sensitivity),
                "overlap": float(overlap),

                # Additional fields not in the database schema
                "chunk_index": chunk_index,
                "total_chunks": len(audio_chunks),
                "step_seconds": step_seconds,  # For accurate extraction in main.py
                "bird_song_file_name": filenames['audio_filename'],
                "spectrogram_file_name": filenames['spectrogram_filename'],
                "bird_song_duration": settings.ANALYSIS_CHUNK_LENGTH,
                "source_file_name": source_file_name,
            })
            detections_count += 1

            # Log each confirmed detection
            logger.info("Bird detected", extra={
                'species': common_name,
                'confidence': round(confidence * 100),
                'chunk': chunk_index,
                'time': start_timestamp.isoformat()
            })

    # Log inference loop timing
    inference_time = time.time() - inference_start
    logger.debug("TFLite inference complete", extra={
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

        # Validate file exists before processing
        if not os.path.exists(audio_file_path):
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

        # Acquire lock to prevent concurrent TFLite interpreter access
        with inference_lock:
            results = process_audio_file(model, meta_model, audio_file_path, labels,
                                         lat, lon, week, sensitivity, cutoff)
        
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
    logger.info("BirdNet service starting", extra={
        'port': settings.BIRDNET_SERVICE_PORT,
        'model_path': settings.MODEL_PATH
    })
    app.run(host='0.0.0.0', debug=False, port=settings.BIRDNET_SERVICE_PORT)
