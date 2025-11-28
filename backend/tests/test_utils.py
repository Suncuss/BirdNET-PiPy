"""
Unit tests for core/utils.py
"""
import pytest
from datetime import datetime
from core.utils import build_detection_filenames


class TestBuildDetectionFilenames:
    """Tests for build_detection_filenames() function"""

    def test_datetime_object_with_microseconds(self):
        """Test that datetime objects with microseconds are normalized"""
        dt = datetime(2025, 11, 25, 11, 38, 39, 123456)
        result = build_detection_filenames('Golden-crowned Kinglet', 0.5690, dt)

        assert result['audio_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        assert result['spectrogram_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.webp'

    def test_datetime_object_without_microseconds(self):
        """Test that datetime objects without microseconds work correctly"""
        dt = datetime(2025, 11, 25, 11, 38, 39)
        result = build_detection_filenames('Golden-crowned Kinglet', 0.5690, dt)

        assert result['audio_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        assert result['spectrogram_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.webp'

    def test_string_timestamp_with_microseconds(self):
        """Test that string timestamps with microseconds are normalized"""
        timestamp = '2025-11-25T11:38:39.000000'
        result = build_detection_filenames('Golden-crowned Kinglet', 0.5690, timestamp)

        assert result['audio_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        assert result['spectrogram_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.webp'

    def test_string_timestamp_without_microseconds(self):
        """Test that string timestamps without microseconds work correctly"""
        timestamp = '2025-11-25T11:38:39'
        result = build_detection_filenames('Golden-crowned Kinglet', 0.5690, timestamp)

        assert result['audio_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        assert result['spectrogram_filename'] == 'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.webp'

    def test_consistent_output_across_formats(self):
        """Test that all timestamp formats produce identical filenames"""
        dt = datetime(2025, 11, 25, 11, 38, 39, 123456)
        ts_with_micro = '2025-11-25T11:38:39.000000'
        ts_without_micro = '2025-11-25T11:38:39'

        result1 = build_detection_filenames('Golden-crowned Kinglet', 0.5690, dt)
        result2 = build_detection_filenames('Golden-crowned Kinglet', 0.5690, ts_with_micro)
        result3 = build_detection_filenames('Golden-crowned Kinglet', 0.5690, ts_without_micro)

        # All three should produce identical filenames
        assert result1['audio_filename'] == result2['audio_filename'] == result3['audio_filename']
        assert result1['spectrogram_filename'] == result2['spectrogram_filename'] == result3['spectrogram_filename']

    def test_species_name_with_spaces(self):
        """Test that spaces in species names are converted to underscores"""
        result = build_detection_filenames('American Robin', 0.85, '2025-11-24T10:30:45')

        assert 'American_Robin' in result['audio_filename']
        assert 'American_Robin' in result['spectrogram_filename']

    def test_confidence_rounding(self):
        """Test that confidence values are properly rounded to percentages"""
        # Test rounding down
        result1 = build_detection_filenames('Test Bird', 0.844, '2025-11-24T10:30:45')
        assert '_84_' in result1['audio_filename']

        # Test rounding up
        result2 = build_detection_filenames('Test Bird', 0.846, '2025-11-24T10:30:45')
        assert '_85_' in result2['audio_filename']

        # Test low confidence
        result3 = build_detection_filenames('Test Bird', 0.05, '2025-11-24T10:30:45')
        assert '_5_' in result3['audio_filename']

    def test_wav_extension(self):
        """Test that WAV extension can be specified for audio files"""
        result = build_detection_filenames(
            'American Robin',
            0.85,
            '2025-11-24T10:30:45',
            audio_extension='wav'
        )

        assert result['audio_filename'].endswith('.wav')
        assert result['spectrogram_filename'].endswith('.webp')  # Spectrogram always .webp

    def test_default_mp3_extension(self):
        """Test that MP3 is the default extension for audio files"""
        result = build_detection_filenames('American Robin', 0.85, '2025-11-24T10:30:45')

        assert result['audio_filename'].endswith('.mp3')

    def test_spectrogram_always_webp(self):
        """Test that spectrogram files always use .webp extension"""
        result1 = build_detection_filenames('Test Bird', 0.85, '2025-11-24T10:30:45', audio_extension='mp3')
        result2 = build_detection_filenames('Test Bird', 0.85, '2025-11-24T10:30:45', audio_extension='wav')

        assert result1['spectrogram_filename'].endswith('.webp')
        assert result2['spectrogram_filename'].endswith('.webp')

    def test_filename_format(self):
        """Test the overall filename format matches expected pattern"""
        result = build_detection_filenames('American Robin', 0.85, '2025-11-24T10:30:45')

        expected_audio = 'American_Robin_85_2025-11-24-birdnet-10:30:45.mp3'
        expected_spec = 'American_Robin_85_2025-11-24-birdnet-10:30:45.webp'

        assert result['audio_filename'] == expected_audio
        assert result['spectrogram_filename'] == expected_spec


class TestSelectAudioChunks:
    """Tests for select_audio_chunks() function"""

    def test_first_chunk_returns_first_two(self):
        """Test that first chunk selection returns [0, 1]"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(0, 3)
        assert result == [0, 1]

    def test_last_chunk_returns_last_two(self):
        """Test that last chunk selection returns last two indices"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(2, 3)  # Last chunk of 3
        assert result == [1, 2]

    def test_middle_chunk_returns_surrounding(self):
        """Test that middle chunk returns surrounding indices"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(1, 3)  # Middle chunk of 3
        assert result == (0, 3)  # Returns tuple with start=0, end=3

    def test_middle_chunk_in_longer_array(self):
        """Test middle chunk in array with more chunks"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(2, 5)  # Middle of 5 chunks
        assert result == (1, 4)  # chunk_index-1 to chunk_index+2

    def test_second_chunk_in_five(self):
        """Test selection of second chunk in 5 chunk array"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(1, 5)
        assert result == (0, 3)

    def test_invalid_negative_index_raises(self):
        """Test that negative index raises ValueError"""
        from core.utils import select_audio_chunks

        with pytest.raises(ValueError, match="detected_chunk_index must be within"):
            select_audio_chunks(-1, 3)

    def test_invalid_index_exceeds_total_raises(self):
        """Test that index >= total_chunks raises ValueError"""
        from core.utils import select_audio_chunks

        with pytest.raises(ValueError, match="detected_chunk_index must be within"):
            select_audio_chunks(3, 3)  # Index 3 is out of range for 3 chunks

    def test_single_chunk_returns_all(self):
        """Test that single chunk returns all (0)"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(0, 1)
        assert result == [0]

    def test_two_chunks_returns_both(self):
        """Test that two chunks returns both"""
        from core.utils import select_audio_chunks

        result = select_audio_chunks(0, 2)
        assert result == [0, 1]

        result2 = select_audio_chunks(1, 2)
        assert result2 == [0, 1]


class TestTrimAudio:
    """Tests for trim_audio() function"""

    def test_trim_audio_calls_sox_transformer(self):
        """Test that trim_audio uses sox.Transformer correctly"""
        from unittest.mock import Mock, patch

        with patch('core.utils.sox.Transformer') as mock_transformer_class:
            mock_transformer = Mock()
            mock_transformer_class.return_value = mock_transformer

            from core.utils import trim_audio

            trim_audio('/input/file.wav', '/output/file.wav', 0.0, 3.0)

            # Verify Transformer was instantiated
            mock_transformer_class.assert_called_once()

            # Verify trim was called with correct arguments
            mock_transformer.trim.assert_called_once_with(0.0, 3.0)

            # Verify build was called with correct paths
            mock_transformer.build.assert_called_once_with(
                '/input/file.wav', '/output/file.wav'
            )

    def test_trim_audio_with_different_times(self):
        """Test trim_audio with various start/end times"""
        from unittest.mock import Mock, patch

        with patch('core.utils.sox.Transformer') as mock_transformer_class:
            mock_transformer = Mock()
            mock_transformer_class.return_value = mock_transformer

            from core.utils import trim_audio

            trim_audio('/input/test.wav', '/output/trimmed.wav', 1.5, 4.5)

            mock_transformer.trim.assert_called_once_with(1.5, 4.5)


class TestConvertWavToMp3:
    """Tests for convert_wav_to_mp3() function"""

    def test_converts_with_correct_ffmpeg_command(self):
        """Test that correct ffmpeg command is built"""
        from unittest.mock import patch

        with patch('core.utils.subprocess.run') as mock_run:
            from core.utils import convert_wav_to_mp3

            convert_wav_to_mp3('/tmp/input.wav', '/tmp/output.mp3')

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]

            # Verify command structure
            assert call_args[0] == 'ffmpeg'
            assert '-y' in call_args  # Overwrite flag
            assert '-i' in call_args
            assert '/tmp/input.wav' in call_args
            assert '/tmp/output.mp3' in call_args
            assert '-codec:a' in call_args
            assert 'libmp3lame' in call_args

    def test_uses_default_320k_bitrate(self):
        """Test that default bitrate is 320k"""
        from unittest.mock import patch

        with patch('core.utils.subprocess.run') as mock_run:
            from core.utils import convert_wav_to_mp3

            convert_wav_to_mp3('/tmp/input.wav', '/tmp/output.mp3')

            call_args = mock_run.call_args[0][0]
            assert '-b:a' in call_args
            bitrate_index = call_args.index('-b:a')
            assert call_args[bitrate_index + 1] == '320k'

    def test_custom_bitrate(self):
        """Test that custom bitrate can be specified"""
        from unittest.mock import patch

        with patch('core.utils.subprocess.run') as mock_run:
            from core.utils import convert_wav_to_mp3

            convert_wav_to_mp3('/tmp/input.wav', '/tmp/output.mp3', bitrate='128k')

            call_args = mock_run.call_args[0][0]
            bitrate_index = call_args.index('-b:a')
            assert call_args[bitrate_index + 1] == '128k'

    def test_converts_to_mono(self):
        """Test that output is mono (-ac 1)"""
        from unittest.mock import patch

        with patch('core.utils.subprocess.run') as mock_run:
            from core.utils import convert_wav_to_mp3

            convert_wav_to_mp3('/tmp/input.wav', '/tmp/output.mp3')

            call_args = mock_run.call_args[0][0]
            assert '-ac' in call_args
            ac_index = call_args.index('-ac')
            assert call_args[ac_index + 1] == '1'

    def test_check_true_for_error_handling(self):
        """Test that subprocess.run is called with check=True"""
        from unittest.mock import patch

        with patch('core.utils.subprocess.run') as mock_run:
            from core.utils import convert_wav_to_mp3

            convert_wav_to_mp3('/tmp/input.wav', '/tmp/output.mp3')

            # Verify check=True is passed for error handling
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get('check') is True
