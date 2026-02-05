"""
Tests for split_audio function with overlap support.

These tests verify that the audio chunking logic correctly handles
different overlap values for BirdNET-Pi compatibility.
"""
import os
import tempfile

import numpy as np
import pytest
from scipy.io import wavfile


class TestSplitAudioOverlap:
    """Test split_audio function with various overlap settings."""

    @pytest.fixture
    def sample_rate(self):
        return 48000

    @pytest.fixture
    def chunk_length(self):
        return 3  # 3 seconds, as required by BirdNET

    @pytest.fixture
    def create_test_wav(self, sample_rate):
        """Create a temporary WAV file with specified duration."""
        def _create(duration_seconds):
            # Create a simple sine wave
            t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
            audio = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

            # Write to temp file
            fd, path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)
            wavfile.write(path, sample_rate, audio)
            return path
        return _create

    def test_no_overlap_9s(self, create_test_wav, sample_rate, chunk_length):
        """9-second recording with no overlap should produce 3 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=0.0)
            assert len(chunks) == 3
            # Each chunk should be exactly 3 seconds = 144000 samples
            for chunk in chunks:
                assert len(chunk) == chunk_length * sample_rate
        finally:
            os.remove(wav_path)

    def test_overlap_1_0_9s(self, create_test_wav, sample_rate, chunk_length):
        """9-second recording with 1.0s overlap should produce 4 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=1.0)
            # Step = 3-1 = 2s, so: 0-3, 2-5, 4-7, 6-9 = 4 chunks
            assert len(chunks) == 4
            for chunk in chunks:
                assert len(chunk) == chunk_length * sample_rate
        finally:
            os.remove(wav_path)

    def test_overlap_1_5_9s(self, create_test_wav, sample_rate, chunk_length):
        """9-second recording with 1.5s overlap should produce 6 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=1.5)
            # Step = 1.5s: 0-3, 1.5-4.5, 3-6, 4.5-7.5, 6-9, 7.5-9* (padded) = 6 chunks
            assert len(chunks) == 6
            for chunk in chunks:
                assert len(chunk) == chunk_length * sample_rate
        finally:
            os.remove(wav_path)

    def test_overlap_2_0_9s(self, create_test_wav, sample_rate, chunk_length):
        """9-second recording with 2.0s overlap should produce 8 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=2.0)
            # Step = 1s: 0-3, 1-4, 2-5, 3-6, 4-7, 5-8, 6-9, 7-9* (padded) = 8 chunks
            assert len(chunks) == 8
            for chunk in chunks:
                assert len(chunk) == chunk_length * sample_rate
        finally:
            os.remove(wav_path)

    def test_overlap_0_5_9s_with_padding(self, create_test_wav, sample_rate, chunk_length):
        """9-second recording with 0.5s overlap - last chunk should be padded."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=0.5)
            # Step = 3-0.5 = 2.5s: 0-3, 2.5-5.5, 5-8, 7.5-9 (1.5s, padded to 3s)
            assert len(chunks) == 4
            for chunk in chunks:
                assert len(chunk) == chunk_length * sample_rate
        finally:
            os.remove(wav_path)

    def test_no_overlap_12s(self, create_test_wav, sample_rate, chunk_length):
        """12-second recording with no overlap should produce 4 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(12)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 12, overlap=0.0)
            assert len(chunks) == 4
        finally:
            os.remove(wav_path)

    def test_no_overlap_15s(self, create_test_wav, sample_rate, chunk_length):
        """15-second recording with no overlap should produce 5 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(15)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 15, overlap=0.0)
            assert len(chunks) == 5
        finally:
            os.remove(wav_path)

    def test_overlap_1_5_15s(self, create_test_wav, sample_rate, chunk_length):
        """15-second recording with 1.5s overlap should produce 10 chunks."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(15)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 15, overlap=1.5)
            # Step = 1.5s: 0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5* (padded) = 10 chunks
            # At 13.5: remaining = 1.5s = minlen, so it's kept and padded
            assert len(chunks) == 10
        finally:
            os.remove(wav_path)

    def test_short_chunk_discarded(self, create_test_wav, sample_rate, chunk_length):
        """Chunks shorter than minlen (1.5s) should be discarded."""
        from model_service.inference_server import split_audio

        # Create a 5-second file
        wav_path = create_test_wav(5)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 5, overlap=0.0)
            # With step=3s: 0-3, 3-5 (2s, >= minlen 1.5s, so padded)
            # Actually 5-3=2s which is >= minlen, so it should be padded
            assert len(chunks) == 2
        finally:
            os.remove(wav_path)

    def test_chunk_too_short_discarded(self, create_test_wav, sample_rate, chunk_length):
        """Chunks shorter than minlen (1.5s) should be discarded."""
        from model_service.inference_server import split_audio

        # Create 4-second file with overlap that leaves <1.5s at end
        wav_path = create_test_wav(4)
        try:
            chunks = split_audio(wav_path, chunk_length, sample_rate, 4, overlap=0.0)
            # With step=3s: 0-3 (full), 3-4 (1s < minlen 1.5s, discarded)
            assert len(chunks) == 1
        finally:
            os.remove(wav_path)

    def test_backward_compatibility_default_overlap(self, create_test_wav, sample_rate, chunk_length):
        """Default overlap of 0.0 should maintain backward compatibility."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            # Call without overlap parameter - should default to 0.0
            chunks = split_audio(wav_path, chunk_length, sample_rate, 9)
            assert len(chunks) == 3
        finally:
            os.remove(wav_path)

    def test_all_chunks_correct_size(self, create_test_wav, sample_rate, chunk_length):
        """All chunks should be exactly chunk_length * sample_rate samples."""
        from model_service.inference_server import split_audio

        wav_path = create_test_wav(9)
        try:
            for overlap in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
                chunks = split_audio(wav_path, chunk_length, sample_rate, 9, overlap=overlap)
                expected_samples = chunk_length * sample_rate
                for i, chunk in enumerate(chunks):
                    assert len(chunk) == expected_samples, \
                        f"Chunk {i} with overlap {overlap} has {len(chunk)} samples, expected {expected_samples}"
        finally:
            os.remove(wav_path)
