import sox
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.signal import spectrogram
import subprocess
import os
import requests
from io import BytesIO
from pydub import AudioSegment
from matplotlib import font_manager
import glob
import threading
import time
from PIL import Image

from config.settings import SAMPLE_RATE, SPECTROGRAM_MIN_DBFS, SPECTROGRAM_MAX_DBFS, SPECTROGRAM_MAX_FREQ_IN_KHZ, SPECTROGRAM_MIN_FREQ_IN_KHZ, SPECTROGRAM_FONT_PATH
BUFFER_SIZE = 1000


def build_detection_filenames(common_name, confidence, timestamp, audio_extension='mp3'):
    """
    Generate standardized filenames for bird detection audio and spectrogram files.

    Args:
        common_name (str): Common name of the bird species (e.g., "American Robin")
        confidence (float): Detection confidence score (0.0 to 1.0)
        timestamp (str or datetime): ISO timestamp string or datetime object
        audio_extension (str): File extension for audio file ('mp3' or 'wav'). Default: 'mp3'

    Returns:
        dict: Dictionary with 'audio_filename' and 'spectrogram_filename' keys

    Example:
        >>> build_detection_filenames("American Robin", 0.85, "2025-11-24T10:30:45.123456")
        {'audio_filename': 'American_Robin_85_2025-11-24-birdnet-10:30:45.123456.mp3',
         'spectrogram_filename': 'American_Robin_85_2025-11-24-birdnet-10:30:45.123456.webp'}
    """
    from datetime import datetime

    # Normalize common name to use underscores
    common_name_underscored = common_name.replace(' ', '_')

    # Round confidence to percentage (0-100)
    confidence_rounded = round(confidence * 100)

    # Parse timestamp if it's a string, otherwise assume it's a datetime object
    if isinstance(timestamp, str):
        # Split ISO format timestamp: "2025-11-24T10:30:45.123456"
        date_part = timestamp.split('T')[0]
        time_part = timestamp.split('T')[1]
        # Strip microseconds if present (handles timestamps like "11:38:39.000000")
        if '.' in time_part:
            time_part = time_part.split('.')[0]
    else:
        # Assume it's a datetime object
        date_part = timestamp.strftime('%Y-%m-%d')
        # Strip microseconds to match database timestamp format
        time_part = timestamp.strftime('%H:%M:%S')

    # Build filenames using consistent format
    audio_filename = f"{common_name_underscored}_{confidence_rounded}_{date_part}-birdnet-{time_part}.{audio_extension}"
    spectrogram_filename = f"{common_name_underscored}_{confidence_rounded}_{date_part}-birdnet-{time_part}.webp"

    return {
        'audio_filename': audio_filename,
        'spectrogram_filename': spectrogram_filename
    }


def trim_audio(source_file_path, output_audio_path, start, end):
    tfm = sox.Transformer()
    tfm.trim(start, end)
    tfm.build(source_file_path, output_audio_path)


def generate_spectrogram(input_file_path, output_file_path, graph_title, start_time=0, end_time=None):
    figsize = (5, 0.8)

    # Set up Inter font
    font_path = SPECTROGRAM_FONT_PATH  # Update this path if necessary
    font_manager.fontManager.addfont(font_path)
    plt.rcParams['font.family'] = 'Inter'

    # Calculate scaling factor based on figure width
    scale = figsize[0] / 10  # Assuming 10 inches is the "standard" width

    # Read audio file
    rate, data = wavfile.read(input_file_path)
    if len(data.shape) > 1:
        data = data[:, 0]  # Take one channel if stereo

    # Convert start_time and end_time to sample indices
    start_sample = int(start_time * rate)
    end_sample = int(end_time * rate) if end_time else len(data)

    # Slice the data to the specified time range
    data = data[start_sample:end_sample]
    
    # Normalize audio
    epsilon = 1e-10
    data = data / (np.max(np.abs(data)) + epsilon)

    # Generate spectrogram
    frequencies, times, Sxx = spectrogram(data, rate, window=np.hamming(256), noverlap=128, nperseg=256)

    # Convert to dBFS, adding a small epsilon to avoid log(0)
   
    Sxx_dbfs = 10 * np.log10(Sxx / np.max(Sxx) + epsilon)

    # Convert frequencies to kHz
    frequencies = frequencies / 1000

    # Adaptive DPI based on output format
    # Use 150 DPI for web/general use, 200 for high-quality while keeping file size reasonable
    dpi = 250
    
    # Plot spectrogram
    plt.figure(figsize=figsize, facecolor='white', dpi=dpi)
    plt.imshow(Sxx_dbfs, aspect='auto', cmap="Greens_r", origin='lower',
               extent=[times.min(), times.max(), frequencies.min(), frequencies.max()],
               vmin=SPECTROGRAM_MIN_DBFS, vmax=SPECTROGRAM_MAX_DBFS,
               interpolation='bilinear')  # Smoother rendering
    
    plt.title(graph_title, fontsize=14*scale, fontweight='bold', pad=10*scale)
    plt.ylabel('Frequency [kHz]', fontsize=12*scale, labelpad=3*scale)

    cbar = plt.colorbar(pad=0.01)
    cbar.set_label('Intensity [dBFS]', fontsize=12*scale, labelpad=3*scale)
    cbar.ax.tick_params(labelsize=10*scale)

    plt.xticks([]) 
    plt.yticks([0,6,12])
    plt.yticks(fontsize=10*scale)
    plt.ylim(SPECTROGRAM_MIN_FREQ_IN_KHZ, SPECTROGRAM_MAX_FREQ_IN_KHZ)

    # Adjust margins manually
    plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.1)

    # Save as WebP for better compression (~87% smaller than PNG)
    # First save to buffer as PNG, then convert to WebP with PIL
    buf = BytesIO()
    plt.savefig(buf, dpi=dpi, bbox_inches='tight', format='png')
    plt.close()

    # Convert to WebP using PIL
    buf.seek(0)
    img = Image.open(buf)
    img.save(output_file_path, 'WEBP', quality=85)
    buf.close()


def select_audio_chunks(detected_chunk_index, total_chunks):
    """
    Select the chunks of audio to be stitched together based on the index of the detected chunk.
    
    Args:
    detected_chunk_index (int): The index of the chunk where the audio event was detected (0-based).
    total_chunks (int): The total number of chunks in the audio.
    
    Returns:
    list: A list of indices of the chunks to be stitched together.
    """
    if detected_chunk_index < 0 or detected_chunk_index >= total_chunks:
        raise ValueError("detected_chunk_index must be within the range of total_chunks")
    
    if total_chunks < 3:
        return list(range(total_chunks))  # Return all chunks if there are fewer than 3
    
    if detected_chunk_index == 0:
        return [0, 1]  # First two chunks if the first chunk is detected
    elif detected_chunk_index == total_chunks - 1:
        return [total_chunks - 2, total_chunks - 1]  # Last two chunks if the last chunk is detected
    else:
        # For middle chunks, return three chunks centered on the detected chunk
        start = max(0, detected_chunk_index - 1)
        end = min(total_chunks, detected_chunk_index + 2)
        return (start, end)


def convert_wav_to_mp3(input_file_name, output_file_name, bitrate="320k"):
    command = [
        "ffmpeg",
        "-y",  # Overwrite output file if it exists
        "-loglevel", "error",  # Suppress most of the output
        "-i", input_file_name,
        "-ac", "1", # Convert to mono
        "-codec:a", "libmp3lame",
        "-b:a", bitrate,
        output_file_name
    ]
    subprocess.run(command, check=True)