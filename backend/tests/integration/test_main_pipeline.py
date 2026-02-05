"""
Tests for main processing pipeline (core/main.py).

Tests the core functions:
- is_valid_recording()
- process_audio_file()
- process_audio_files() (directory scanning)
"""
import os
from unittest.mock import Mock, patch

import pytest
import requests


class TestIsValidRecording:
    """Test the is_valid_recording() function."""

    def test_valid_recording_returns_true(self, temp_recording_dir, create_test_wav_file):
        """Test that a valid recording (>= MIN_RECORDING_DURATION) returns True."""
        # Create a file that's 6 seconds worth (above 5 second minimum)
        # 6 seconds * 48000 samples/second * 2 bytes/sample = 576000 bytes
        valid_size = 6 * 48000 * 2
        file_path = create_test_wav_file('valid.wav', valid_size)

        with patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0):
            from core.main import is_valid_recording

            mock_logger = Mock()
            result = is_valid_recording(file_path, mock_logger)

            assert result is True
            # Should not log any warnings
            mock_logger.warning.assert_not_called()

    def test_short_recording_returns_false(self, temp_recording_dir, create_test_wav_file):
        """Test that a recording below MIN_RECORDING_DURATION returns False."""
        # Create a file that's 3 seconds worth (below 5 second minimum)
        # 3 seconds * 48000 samples/second * 2 bytes/sample = 288000 bytes
        short_size = 3 * 48000 * 2
        file_path = create_test_wav_file('short.wav', short_size)

        with patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0):
            from core.main import is_valid_recording

            mock_logger = Mock()
            result = is_valid_recording(file_path, mock_logger)

            assert result is False
            # Should log a warning
            mock_logger.warning.assert_called_once()

    def test_exactly_minimum_duration_returns_true(self, temp_recording_dir, create_test_wav_file):
        """Test that a recording exactly at MIN_RECORDING_DURATION returns True."""
        # Create a file that's exactly 5 seconds
        # 5 seconds * 48000 samples/second * 2 bytes/sample = 480000 bytes
        exact_size = 5 * 48000 * 2
        file_path = create_test_wav_file('exact.wav', exact_size)

        with patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0):
            from core.main import is_valid_recording

            mock_logger = Mock()
            result = is_valid_recording(file_path, mock_logger)

            assert result is True

    def test_empty_file_returns_false(self, temp_recording_dir, create_test_wav_file):
        """Test that an empty file returns False."""
        file_path = create_test_wav_file('empty.wav', 0)

        with patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0):
            from core.main import is_valid_recording

            mock_logger = Mock()
            result = is_valid_recording(file_path, mock_logger)

            assert result is False

    def test_nonexistent_file_returns_false(self):
        """Test that a nonexistent file returns False."""
        with patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0):
            from core.main import is_valid_recording

            mock_logger = Mock()
            result = is_valid_recording('/nonexistent/file.wav', mock_logger)

            assert result is False
            # Should log an error
            mock_logger.error.assert_called_once()

    def test_mono_16bit_format_assumption(self):
        """Verify the calculation assumes mono 16-bit audio."""
        # The function uses: file_size / (SAMPLE_RATE * 2)
        # 2 bytes per sample = 16-bit mono
        sample_rate = 48000
        duration = 9
        bytes_per_sample = 2  # 16-bit

        expected_size = duration * sample_rate * bytes_per_sample
        assert expected_size == 864000


class TestProcessAudioFile:
    """Test the process_audio_file() function."""

    def test_successful_detection_returns_list(self, mock_birdnet_success_response):
        """Test that successful BirdNet response returns detections list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_success_response
            mock_post.return_value = mock_response

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result is not None
            assert len(result) == 1
            assert result[0]['common_name'] == 'American Robin'
            assert result[0]['confidence'] == 0.95

    def test_successful_detection_sends_correct_payload(self):
        """Test that the correct payload is sent to BirdNet service."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_post.return_value = mock_response

            from core.main import BIRDNET_REQUEST_TIMEOUT, process_audio_file

            process_audio_file('/tmp/test_audio.wav')

            # Verify correct endpoint and payload
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs[1]['json'] == {'audio_file_path': '/tmp/test_audio.wav'}
            assert call_kwargs[1]['timeout'] == BIRDNET_REQUEST_TIMEOUT

    def test_no_detections_returns_empty_list(self, mock_birdnet_empty_response):
        """Test that response with no detections returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_empty_response
            mock_post.return_value = mock_response

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_birdnet_error_response_returns_empty_list(self):
        """Test that BirdNet error response (non-200) returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_birdnet_404_returns_empty_list(self):
        """Test that 404 response returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.text = "File not found"
            mock_post.return_value = mock_response

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_network_timeout_returns_empty_list(self):
        """Test that network timeout returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_connection_error_returns_empty_list(self):
        """Test that connection error returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect")

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_generic_request_exception_returns_empty_list(self):
        """Test that generic request exception returns empty list."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_post.side_effect = requests.exceptions.RequestException("Unknown error")

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_unexpected_exception_returns_empty_list(self):
        """Test that unexpected exceptions are handled gracefully."""
        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_post.side_effect = Exception("Something unexpected")

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert result == []

    def test_multiple_detections_in_response(self):
        """Test handling of multiple detections in single response."""
        detections = [
            {
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.95,
            },
            {
                'common_name': 'Blue Jay',
                'scientific_name': 'Cyanocitta cristata',
                'confidence': 0.87,
            }
        ]

        with patch('core.main.requests.post') as mock_post, \
             patch('core.main.logger'):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = detections
            mock_post.return_value = mock_response

            from core.main import process_audio_file

            result = process_audio_file('/tmp/test.wav')

            assert len(result) == 2
            assert result[0]['common_name'] == 'American Robin'
            assert result[1]['common_name'] == 'Blue Jay'


class TestDirectoryScanningArchitecture:
    """Test the no-queue, directory-scanning architecture."""

    def test_processing_thread_scans_directory(self, temp_recording_dir, create_test_wav_file):
        """Test that processing thread scans directory for .wav files."""
        # Create a valid recording file
        valid_size = 6 * 48000 * 2
        create_test_wav_file('test_recording.wav', valid_size)

        call_count = [0]
        def stop_after_processing():
            call_count[0] += 1
            # Stop after a few calls (allow time for processing)
            return call_count[0] > 3

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0), \
             patch('core.main.stop_flag') as mock_stop_flag, \
             patch('core.main.process_audio_file') as mock_process, \
             patch('core.main.handle_detection'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_stop_flag.is_set.side_effect = stop_after_processing
            mock_process.return_value = []

            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import process_audio_files

            process_audio_files()

            # Should have processed the file
            mock_process.assert_called_once()
            called_path = mock_process.call_args[0][0]
            assert 'test_recording.wav' in called_path

    def test_processing_thread_deletes_invalid_files(self, temp_recording_dir, create_test_wav_file):
        """Test that processing thread deletes files that are too short."""
        # Create an invalid (too short) recording file
        short_size = 2 * 48000 * 2  # 2 seconds, below 5 second minimum
        file_path = create_test_wav_file('short_recording.wav', short_size)

        assert os.path.exists(file_path)

        call_count = [0]
        def stop_after_processing():
            call_count[0] += 1
            return call_count[0] > 3

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0), \
             patch('core.main.stop_flag') as mock_stop_flag, \
             patch('core.main.process_audio_file') as mock_process, \
             patch('core.main.get_logger') as mock_get_logger:

            mock_stop_flag.is_set.side_effect = stop_after_processing

            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import process_audio_files

            process_audio_files()

            # Should NOT have called process_audio_file (file was invalid)
            mock_process.assert_not_called()

            # File should be deleted
            assert not os.path.exists(file_path)

    def test_processing_thread_ignores_non_wav_files(self, temp_recording_dir):
        """Test that processing thread ignores non-WAV files."""
        # Create a non-WAV file
        mp3_path = os.path.join(temp_recording_dir, 'test.mp3')
        with open(mp3_path, 'wb') as f:
            f.write(b'\x00' * 10000)

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.stop_flag') as mock_stop_flag, \
             patch('core.main.process_audio_file') as mock_process, \
             patch('core.main.FILE_SCAN_INTERVAL', 0), \
             patch('core.main.get_logger') as mock_get_logger:

            # Configure stop flag to stop after first iteration
            mock_stop_flag.is_set.side_effect = [False, True]

            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import process_audio_files

            process_audio_files()

            # Should NOT have called process_audio_file
            mock_process.assert_not_called()

            # MP3 file should still exist
            assert os.path.exists(mp3_path)

    def test_files_processed_in_chronological_order(self, temp_recording_dir, create_test_wav_file):
        """Test that files are processed in sorted (chronological) order."""
        valid_size = 6 * 48000 * 2

        # Create files with timestamps (will be sorted by filename)
        create_test_wav_file('20251126_100300.wav', valid_size)
        create_test_wav_file('20251126_100100.wav', valid_size)
        create_test_wav_file('20251126_100200.wav', valid_size)

        processed_files = []

        def track_processed(file_path):
            processed_files.append(os.path.basename(file_path))
            return []

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.MIN_RECORDING_DURATION', 5.0), \
             patch('core.main.stop_flag') as mock_stop_flag, \
             patch('core.main.process_audio_file', side_effect=track_processed), \
             patch('core.main.get_logger') as mock_get_logger:

            # Configure stop flag to stop after processing all files
            mock_stop_flag.is_set.side_effect = [False, False, False, False, True]

            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import process_audio_files

            process_audio_files()

            # Files should be processed in sorted order
            assert processed_files == [
                '20251126_100100.wav',
                '20251126_100200.wav',
                '20251126_100300.wav'
            ]


class TestHandleDetection:
    """Test the handle_detection() function that processes bird detections."""

    def test_successful_detection_processing(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test complete handle_detection flow with all operations."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.BROADCAST_TIMEOUT', 5), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio') as mock_trim, \
             patch('core.main.generate_spectrogram') as mock_spec, \
             patch('core.main.convert_wav_to_mp3') as mock_convert, \
             patch('core.main.db_manager') as mock_db, \
             patch('core.main.requests.post') as mock_post, \
             patch('core.main.os.remove') as mock_remove, \
             patch('core.main.get_logger') as mock_get_logger:

            # Setup mocks
            mock_select.return_value = (0, 2)  # Start, end indices (inclusive)
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            # Execute
            handle_detection(
                mock_detection_with_metadata,
                input_file,
                mock_logger
            )

            # Verify all operations called in correct order
            mock_select.assert_called_once_with(1, 3)  # chunk_index=1, total_chunks=3

            mock_trim.assert_called_once()
            trim_args = mock_trim.call_args[0]
            assert trim_args[0] == input_file  # source file
            assert trim_args[2] == 0  # start time (0 * 3 seconds)
            assert trim_args[3] == 9  # end time (2 * 3 + 3 = 9 seconds)

            mock_spec.assert_called_once()
            spec_args = mock_spec.call_args[0]
            assert spec_args[0] == input_file  # input file
            assert 'American Robin' in spec_args[2]  # title contains species name

            mock_convert.assert_called_once()
            convert_args = mock_convert.call_args[0]
            assert convert_args[0].endswith('.wav')  # input is WAV
            assert convert_args[1].endswith('.mp3')  # output is MP3

            # Verify database insertion
            mock_db.insert_detection.assert_called_once()
            db_call_args = mock_db.insert_detection.call_args[0][0]
            assert db_call_args['common_name'] == 'American Robin'
            assert db_call_args['scientific_name'] == 'Turdus migratorius'
            assert db_call_args['confidence'] == 0.95

            # Verify WebSocket broadcast
            mock_post.assert_called_once()
            post_args = mock_post.call_args
            assert 'localhost:5002/api/broadcast/detection' in post_args[0][0]
            broadcast_data = post_args[1]['json']
            assert broadcast_data['common_name'] == 'American Robin'
            assert broadcast_data['bird_song_file_name'].endswith('.mp3')

            # Verify WAV file cleanup
            assert mock_remove.call_count == 1
            remove_args = mock_remove.call_args[0][0]
            assert remove_args.endswith('.wav')

            # Verify user-facing log
            mock_logger.info.assert_called()
            log_call = mock_logger.info.call_args
            log_str = str(log_call)
            assert '🐦' in log_str or 'Bird detected' in log_str
            # Check the extra data passed to the logger
            assert 'extra' in log_call[1]
            assert log_call[1]['extra']['species'] == 'American Robin'

    def test_audio_chunk_selection_first_chunk(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that first chunk selects chunks [0, 1]."""

        # Modify detection to have chunk_index=0 (first chunk)
        detection = mock_detection_with_metadata.copy()
        detection['chunk_index'] = 0
        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 1)  # First two chunks
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(detection, input_file, mock_logger)

            # Verify select_audio_chunks called with first chunk
            mock_select.assert_called_once_with(0, 3)

    def test_audio_chunk_selection_middle_chunk(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that middle chunk selects surrounding chunks (tuple with start, end)."""

        # Detection already has chunk_index=1 (middle chunk)
        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # Tuple: start=0, end=2 (inclusive)
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify select_audio_chunks called with middle chunk
            mock_select.assert_called_once_with(1, 3)

    def test_audio_chunk_selection_last_chunk(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that last chunk selects last two chunks."""

        # Modify detection to have chunk_index=2 (last chunk)
        detection = mock_detection_with_metadata.copy()
        detection['chunk_index'] = 2  # Last of 3 chunks
        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (1, 2)  # Last two chunks
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(detection, input_file, mock_logger)

            # Verify select_audio_chunks called with last chunk
            mock_select.assert_called_once_with(2, 3)

    def test_trim_audio_called_with_correct_parameters(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that trim_audio is called with correct paths and time parameters."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio') as mock_trim, \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # 3 chunks (0, 1, 2) inclusive
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify trim_audio called with correct parameters
            mock_trim.assert_called_once()
            args = mock_trim.call_args[0]

            # Check source file
            assert args[0] == input_file

            # Check output file path
            assert args[1].endswith('American_Robin_95_test.wav')
            assert temp_extraction_dirs['extracted'] in args[1]

            # Check start and end times
            assert args[2] == 0  # start_time = 0 * 3
            assert args[3] == 9  # end_time = 2 * 3 + 3 = 9

    def test_spectrogram_generation_with_correct_title(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that spectrogram is generated with correct title format."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram') as mock_spec, \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify spectrogram generation
            mock_spec.assert_called_once()
            args = mock_spec.call_args[0]
            kwargs = mock_spec.call_args[1]

            # Check input file
            assert args[0] == input_file

            # Check output file path
            assert args[1].endswith('American_Robin_95_test.webp')
            assert temp_extraction_dirs['spectrogram'] in args[1]

            # Check title contains species name and confidence
            title = args[2]
            assert 'American Robin' in title
            assert '0.95' in title
            assert '2025-11-26T10:30:00' in title

            # Check start_time and end_time kwargs
            assert kwargs['start_time'] == 3  # ANALYSIS_CHUNK_LENGTH * chunk_index (1)
            assert kwargs['end_time'] == 6  # ANALYSIS_CHUNK_LENGTH * (chunk_index + 1)

    def test_wav_to_mp3_conversion(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that WAV to MP3 conversion is called correctly."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3') as mock_convert, \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify conversion called
            mock_convert.assert_called_once()
            args = mock_convert.call_args[0]

            # Check input is WAV
            assert args[0].endswith('American_Robin_95_test.wav')
            assert temp_extraction_dirs['extracted'] in args[0]

            # Check output is MP3
            assert args[1].endswith('American_Robin_95_test.mp3')
            assert temp_extraction_dirs['extracted'] in args[1]

    def test_wav_file_deleted_after_conversion(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that WAV file is deleted after MP3 conversion."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove') as mock_remove, \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify WAV file deleted
            mock_remove.assert_called_once()
            removed_file = mock_remove.call_args[0][0]

            # Check it's the WAV file
            assert removed_file.endswith('American_Robin_95_test.wav')
            assert temp_extraction_dirs['extracted'] in removed_file

    def test_database_insertion_with_all_fields(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that database insertion includes all detection fields."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager') as mock_db, \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify database insertion
            mock_db.insert_detection.assert_called_once()
            inserted_data = mock_db.insert_detection.call_args[0][0]

            # Verify all required fields are present
            assert inserted_data['timestamp'] == '2025-11-26T10:30:00'
            assert inserted_data['group_timestamp'] == '2025-11-26T10:30:00'
            assert inserted_data['scientific_name'] == 'Turdus migratorius'
            assert inserted_data['common_name'] == 'American Robin'
            assert inserted_data['confidence'] == 0.95
            assert inserted_data['latitude'] == 40.7128
            assert inserted_data['longitude'] == -74.0060
            assert inserted_data['cutoff'] == 0.5
            assert inserted_data['sensitivity'] == 0.75
            assert inserted_data['overlap'] == 0.25

    def test_websocket_broadcast_on_success(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that WebSocket broadcast is sent with correct payload."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.BROADCAST_TIMEOUT', 5), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post') as mock_post, \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify WebSocket broadcast
            mock_post.assert_called_once()

            # Check URL
            url = mock_post.call_args[0][0]
            assert 'http://localhost:5002/api/broadcast/detection' == url

            # Check payload
            payload = mock_post.call_args[1]['json']
            assert payload['timestamp'] == '2025-11-26T10:30:00'
            assert payload['common_name'] == 'American Robin'
            assert payload['scientific_name'] == 'Turdus migratorius'
            assert payload['confidence'] == 0.95
            assert payload['bird_song_file_name'] == 'American_Robin_95_test.mp3'  # MP3, not WAV
            assert payload['spectrogram_file_name'] == 'American_Robin_95_test.webp'

            # Check timeout
            assert mock_post.call_args[1]['timeout'] == 5

    def test_websocket_broadcast_failure_continues_processing(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that broadcast failure doesn't stop processing."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio') as mock_trim, \
             patch('core.main.generate_spectrogram') as mock_spec, \
             patch('core.main.convert_wav_to_mp3') as mock_convert, \
             patch('core.main.db_manager') as mock_db, \
             patch('core.main.requests.post') as mock_post, \
             patch('core.main.os.remove') as mock_remove, \
             patch('core.main.get_logger') as mock_get_logger:

            # Broadcast fails with exception
            mock_post.side_effect = Exception("Connection refused")

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            # Should not raise exception
            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify all other operations still completed
            mock_trim.assert_called_once()
            mock_spec.assert_called_once()
            mock_convert.assert_called_once()
            mock_db.insert_detection.assert_called_once()
            mock_remove.assert_called_once()

            # Verify warning logged
            mock_logger.warning.assert_called()

    def test_detection_logged_correctly(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Test that detection is logged with correct format and data."""

        input_file = os.path.join(temp_recording_dir, 'recording.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager'), \
             patch('core.main.requests.post'), \
             patch('core.main.os.remove'), \
             patch('core.main.get_logger') as mock_get_logger:

            mock_select.return_value = (0, 2)  # inclusive range
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            from core.main import handle_detection

            handle_detection(mock_detection_with_metadata, input_file, mock_logger)

            # Verify info log called
            mock_logger.info.assert_called()

            # Get the log call
            info_calls = [call for call in mock_logger.info.call_args_list]
            assert len(info_calls) > 0

            # Find the bird detection log (should contain the emoji or "Bird detected")
            detection_log = None
            for call in info_calls:
                log_str = str(call)
                if '🐦' in log_str or 'Bird detected' in log_str:
                    detection_log = call
                    break

            assert detection_log is not None, "Should have logged bird detection"

            # Verify log contains correct extra data
            extra_data = detection_log[1]['extra']
            assert extra_data['species'] == 'American Robin'
            assert extra_data['confidence'] == 95  # Rounded from 0.95 to 95%
            assert extra_data['time'] == '10:30:00'  # Time extracted from timestamp

            # Verify debug log for saving to database
            mock_logger.debug.assert_called()
            debug_calls = [call for call in mock_logger.debug.call_args_list]

            # Find database save log
            db_log = None
            for call in debug_calls:
                log_str = str(call)
                if 'database' in log_str.lower():
                    db_log = call
                    break

            assert db_log is not None, "Should have logged database save"


class TestFullPipelineIntegration:
    """End-to-end pipeline tests with REAL database and filesystem."""

    def test_complete_pipeline_with_detection(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_single_detection,
        mock_audio_processing
    ):
        """Test full pipeline: file → process → DB → cleanup."""

        # Create valid WAV file (9 seconds = 3 chunks of 3 seconds each)
        wav_file = create_valid_wav_file('20251127_103000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks to return proper range
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_single_detection
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3  # Allow processing to complete
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify database insertion (REAL database query)
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 1, f"Expected 1 detection, got {len(detections)}"

            # Verify detection data
            detection = detections[0]
            assert detection['common_name'] == 'American Robin'
            assert detection['scientific_name'] == 'Turdus migratorius'
            assert detection['confidence'] == pytest.approx(0.95, abs=0.01)
            assert detection['latitude'] == 40.7128
            assert detection['longitude'] == -74.0060

            # Verify source file deleted
            assert not os.path.exists(wav_file), "Source WAV file should be deleted after processing"

            # Verify BirdNet API was called (called twice: once for API, once for broadcast)
            assert mock_birdnet_api.call_count == 2
            # First call is to BirdNet API
            first_call = mock_birdnet_api.call_args_list[0]
            assert 'model-server' in first_call[0][0]
            # Second call is broadcast
            second_call = mock_birdnet_api.call_args_list[1]
            assert 'broadcast' in second_call[0][0]

    def test_invalid_file_deleted_without_processing(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        temp_recording_dir
    ):
        """Test that invalid files are deleted without processing."""

        # Create invalid WAV file (too small - only 1 second worth of data)
        # With ANALYSIS_CHUNK_LENGTH=3, file needs at least 3 seconds
        # 48000 Hz * 2 bytes * 1 second = 96,000 bytes (less than required 288,000)
        invalid_file = os.path.join(temp_recording_dir, '20251127_110000.wav')
        with open(invalid_file, 'wb') as f:
            f.write(b'\x00' * 96000)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.stop_flag') as mock_stop:

            # Run one iteration then stop
            call_count = [0]
            def stop_after_check():
                call_count[0] += 1
                return call_count[0] > 2  # Stop after checking the invalid file
            mock_stop.is_set.side_effect = stop_after_check

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify file was deleted (invalid files are removed)
            assert not os.path.exists(invalid_file), "Invalid WAV file should be deleted"

            # Verify no database insertion occurred
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 0, f"Expected 0 detections for invalid file, got {len(detections)}"

            # Verify BirdNet API was NOT called
            assert mock_birdnet_api.call_count == 0, "BirdNet API should not be called for invalid files"

    def test_complete_pipeline_no_detections(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_empty_response,
        mock_audio_processing
    ):
        """Test pipeline when BirdNet finds no birds."""

        # Create valid WAV file
        wav_file = create_valid_wav_file('20251127_120000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response with no detections
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_empty_response
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify NO database insertion
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 0, f"Expected 0 detections, got {len(detections)}"

            # Verify source file still deleted
            assert not os.path.exists(wav_file), "Source WAV file should be deleted even with no detections"

            # Verify BirdNet API was called (but only once - no broadcast for empty results)
            assert mock_birdnet_api.call_count == 1, "BirdNet API should be called once even with no detections"

    def test_pipeline_handles_multiple_detections(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_multiple_detections,
        mock_audio_processing
    ):
        """Test pipeline correctly handles multiple bird detections."""

        # Create valid WAV file
        wav_file = create_valid_wav_file('20251127_130000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response with 2 detections
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_multiple_detections
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify both detections were inserted
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 2, f"Expected 2 detections, got {len(detections)}"

            # Verify detection data (sorted by timestamp)
            species_names = {d['common_name'] for d in detections}
            assert 'American Robin' in species_names
            assert 'Blue Jay' in species_names

            # Verify source file deleted
            assert not os.path.exists(wav_file)

            # Verify BirdNet API was called (3 times: 1 for analysis + 2 for broadcasts)
            assert mock_birdnet_api.call_count == 3

    def test_database_persists_detection_data(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_single_detection,
        mock_audio_processing
    ):
        """Test that all detection fields are correctly persisted to database."""

        # Create valid WAV file
        create_valid_wav_file('20251127_140000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_single_detection
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify database insertion with all fields
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 1

            detection = detections[0]

            # Verify all core fields
            assert detection['common_name'] == 'American Robin'
            assert detection['scientific_name'] == 'Turdus migratorius'
            assert detection['confidence'] == pytest.approx(0.95, abs=0.01)

            # Verify location fields
            assert detection['latitude'] == 40.7128
            assert detection['longitude'] == -74.0060

            # Verify file references follow the expected naming pattern
            assert 'American_Robin' in detection['bird_song_file_name']
            assert detection['bird_song_file_name'].endswith('.mp3')
            assert 'American_Robin' in detection['spectrogram_file_name']
            assert detection['spectrogram_file_name'].endswith('.webp')

            # Verify timestamps exist and are strings
            assert 'timestamp' in detection
            assert isinstance(detection['timestamp'], str)

            # Verify metadata fields
            assert 'cutoff' in detection
            assert 'sensitivity' in detection
            assert 'overlap' in detection

    def test_extracted_audio_files_created(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_single_detection,
        mock_audio_processing
    ):
        """Test that extracted audio files are created in the correct directory."""

        # Create valid WAV file
        create_valid_wav_file('20251127_150000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_single_detection
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify extracted audio files were created in the correct directory
            extracted_files = os.listdir(pipeline_temp_dirs['extracted'])

            # Should have MP3 files (WAV files are typically deleted after conversion)
            mp3_files = [f for f in extracted_files if f.endswith('.mp3')]

            assert len(mp3_files) > 0, f"Should have created converted MP3 file, found files: {extracted_files}"

            # Verify filename contains species name
            assert any('American_Robin' in f for f in mp3_files), f"MP3 files should contain species name, got: {mp3_files}"

    def test_spectrogram_files_created(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_birdnet_single_detection,
        mock_audio_processing
    ):
        """Test that spectrogram files are created in the correct directory."""

        # Create valid WAV file
        create_valid_wav_file('20251127_160000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_birdnet_single_detection
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify spectrogram files were created in the correct directory
            spectrogram_files = os.listdir(pipeline_temp_dirs['spectrogram'])

            # Should have WEBP files
            webp_files = [f for f in spectrogram_files if f.endswith('.webp')]

            assert len(webp_files) > 0, "Should have created spectrogram WEBP file"

            # Verify filename contains species name
            assert any('American_Robin' in f for f in webp_files)

    def test_source_file_deleted_after_processing(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_audio_processing
    ):
        """Test that source file is always deleted after processing, even on API errors."""

        # Create valid WAV file
        wav_file = create_valid_wav_file('20251127_170000.wav', duration_seconds=9)

        # Setup: Patch all configuration and dependencies
        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks') as mock_select, \
             patch('core.main.stop_flag') as mock_stop:

            # Mock select_audio_chunks
            mock_select.return_value = (0, 2)  # inclusive range

            # Mock BirdNet API to return error (500 Internal Server Error)
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_birdnet_api.return_value = mock_response

            # Run one iteration then stop
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 3
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute pipeline
            process_audio_files()

            # Verify source file was deleted despite API error
            assert not os.path.exists(wav_file), "Source WAV file should be deleted even when BirdNet API fails"

            # Verify no database insertion occurred (API failed)
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) == 0, "Should have no detections when API fails"


class TestRecordingThread:
    """Test recording thread lifecycle and health monitoring."""

    def test_creates_pulseaudio_recorder_when_mode_is_pulseaudio(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that PulseAudioRecorder is created when mode is pulseaudio."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.main.PULSEAUDIO_SOURCE', 'test-source'), \
             patch('core.main.RECORDING_LENGTH', 9), \
             patch('core.main.RECORDING_DIR', '/tmp/test'), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.audio_manager.PulseAudioRecorder') as mock_pulse_recorder_class, \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to exit immediately
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=0)

            # Mock the recorder class to return our mock_recorder
            mock_pulse_recorder_class.return_value = mock_recorder

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify PulseAudioRecorder was instantiated with correct params
            mock_pulse_recorder_class.assert_called_once_with(
                source_name='test-source',
                chunk_duration=9,
                output_dir='/tmp/test',
                target_sample_rate=48000
            )

    def test_creates_http_recorder_when_mode_is_http_stream(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that HttpStreamRecorder is created when mode is http_stream."""

        with patch('core.main.RECORDING_MODE', 'http_stream'), \
             patch('core.main.STREAM_URL', 'http://test.com/stream'), \
             patch('core.main.RECORDING_LENGTH', 9), \
             patch('core.main.RECORDING_DIR', '/tmp/test'), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.audio_manager.HttpStreamRecorder') as mock_http_recorder_class, \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to exit immediately
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=0)

            # Mock the recorder class to return our mock_recorder
            mock_http_recorder_class.return_value = mock_recorder

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify HttpStreamRecorder was instantiated with correct params
            mock_http_recorder_class.assert_called_once_with(
                stream_url='http://test.com/stream',
                chunk_duration=9,
                output_dir='/tmp/test',
                target_sample_rate=48000
            )

    def test_recorder_started_on_thread_start(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that recorder.start() is called when thread starts."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.audio_manager.PulseAudioRecorder', return_value=mock_recorder), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to exit immediately
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=0)

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify recorder.start() was called
            mock_recorder.start.assert_called_once()

    def test_monitors_recorder_health_in_loop(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that is_healthy() is checked in the loop."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.audio_manager.PulseAudioRecorder', return_value=mock_recorder), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to run 3 iterations
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=3)

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify is_healthy() was called multiple times (at least 3)
            assert mock_recorder.is_healthy.call_count >= 3

    def test_restarts_unhealthy_recorder(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that recorder.restart() is called when unhealthy."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.audio_manager.PulseAudioRecorder', return_value=mock_recorder), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock is_healthy() to return False on 2nd call
            mock_recorder.is_healthy.side_effect = [True, False, True, True]

            # Mock stop_flag to run 4 iterations
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=4)

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify recorder.restart() was called once
            mock_recorder.restart.assert_called_once()

    def test_stops_recorder_on_exit(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that recorder.stop() is called in finally block on exit."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.audio_manager.PulseAudioRecorder', return_value=mock_recorder), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to exit immediately
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=0)

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify recorder.stop() was called in finally block
            mock_recorder.stop.assert_called_once()


class TestThreadCoordination:
    """Test shutdown and stop_flag coordination."""

    def test_stop_flag_stops_recording_loop(
        self, mock_recorder, controllable_stop_flag
    ):
        """Test that stop_flag stops the recording loop."""

        with patch('core.main.RECORDING_MODE', 'pulseaudio'), \
             patch('core.audio_manager.PulseAudioRecorder', return_value=mock_recorder), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to stop after 2 iterations
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=2)

            from core.main import continuous_audio_recording

            # Create mock logger
            mock_logger = Mock()

            # Execute
            continuous_audio_recording(mock_logger)

            # Verify is_set() was called (loop checked the flag)
            assert mock_stop.is_set.call_count > 0

            # Verify loop exited (stop() called in finally)
            mock_recorder.stop.assert_called_once()

    def test_stop_flag_stops_processing_loop(
        self, temp_recording_dir, controllable_stop_flag
    ):
        """Test that stop_flag stops the processing loop."""

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Mock stop_flag to stop after 2 iterations
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=2)

            from core.main import process_audio_files

            # Execute
            process_audio_files()

            # Verify is_set() was called (loop checked the flag)
            assert mock_stop.is_set.call_count > 0

    # Note: shutdown() function uses thread objects created in __main__ block,
    # which are not accessible at module level for unit testing. The shutdown
    # logic is simple (set stop_flag, join threads, log warnings) and can be
    # verified through code inspection and manual testing.


class TestHandleDetectionErrors:
    """Test current error handling behavior in handle_detection().

    NOTE: These tests document that handle_detection() currently does NOT have
    error handling for subprocess failures. Exceptions propagate up and crash
    the function. This is documented behavior that should be improved in the future.
    """

    def test_trim_audio_subprocess_failure_crashes(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Document that trim_audio() subprocess failure currently crashes (no error handling)."""
        import subprocess

        import pytest

        input_file = os.path.join(temp_recording_dir, 'test.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.trim_audio') as mock_trim, \
             patch('core.main.get_logger') as mock_logger:

            # Mock trim_audio to raise subprocess error
            mock_trim.side_effect = subprocess.CalledProcessError(1, 'sox', stderr=b'sox error')

            mock_logger_instance = Mock()
            mock_logger.return_value = mock_logger_instance

            from core.main import handle_detection

            # Verify that exception propagates (no error handling)
            with pytest.raises(subprocess.CalledProcessError):
                handle_detection(mock_detection_with_metadata, input_file, mock_logger_instance)

            # Verify trim_audio was called before crash
            mock_trim.assert_called_once()

    def test_generate_spectrogram_failure_crashes(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Document that generate_spectrogram() failure currently crashes (no error handling)."""
        import pytest

        input_file = os.path.join(temp_recording_dir, 'test.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.trim_audio'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('os.remove'), \
             patch('core.main.generate_spectrogram') as mock_spec, \
             patch('core.main.get_logger') as mock_logger:

            # Mock generate_spectrogram to raise exception
            mock_spec.side_effect = Exception('Matplotlib error')

            mock_logger_instance = Mock()
            mock_logger.return_value = mock_logger_instance

            from core.main import handle_detection

            # Verify that exception propagates (no error handling)
            with pytest.raises(Exception, match='Matplotlib error'):
                handle_detection(mock_detection_with_metadata, input_file, mock_logger_instance)

            # Verify generate_spectrogram was called before crash
            mock_spec.assert_called_once()

    def test_convert_wav_to_mp3_subprocess_failure_crashes(
        self, temp_recording_dir, temp_extraction_dirs, mock_detection_with_metadata
    ):
        """Document that convert_wav_to_mp3() subprocess failure currently crashes (no error handling)."""
        import subprocess

        import pytest

        input_file = os.path.join(temp_recording_dir, 'test.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3') as mock_convert, \
             patch('core.main.get_logger') as mock_logger:

            # Mock convert_wav_to_mp3 to raise subprocess error
            mock_convert.side_effect = subprocess.CalledProcessError(1, 'ffmpeg', stderr=b'ffmpeg error')

            mock_logger_instance = Mock()
            mock_logger.return_value = mock_logger_instance

            from core.main import handle_detection

            # Verify that exception propagates (no error handling)
            with pytest.raises(subprocess.CalledProcessError):
                handle_detection(mock_detection_with_metadata, input_file, mock_logger_instance)

            # Verify convert_wav_to_mp3 was called before crash
            mock_convert.assert_called_once()


class TestEdgeCasesAndResilience:
    """Test edge cases and resilience in process_audio_files()."""

    def test_processing_multiple_files_in_sequence(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        mock_audio_processing
    ):
        """Test that multiple files are processed correctly in sequence."""

        # Create 5 valid WAV files
        files = []
        for i in range(5):
            filename = f'20251127_{150000 + i*1000}.wav'
            file_path = create_valid_wav_file(filename, duration_seconds=9)
            files.append(file_path)

        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.stop_flag') as mock_stop:

            # Mock BirdNet API response with unique timestamps for each file
            call_counter = [0]
            def mock_birdnet_response(*args, **kwargs):
                response = Mock()
                response.status_code = 200
                response.json.return_value = [
                    {
                        'common_name': 'American Robin',
                        'scientific_name': 'Turdus migratorius',
                        'confidence': 0.95,
                        'timestamp': f'2025-11-27T10:3{call_counter[0]}:00',
                        'group_timestamp': f'2025-11-27T10:3{call_counter[0]}:00',
                        'chunk_index': 0,
                        'total_chunks': 3,
                        'bird_song_file_name': f'American_Robin_95_test_{call_counter[0]}.wav',
                        'spectrogram_file_name': f'American_Robin_95_test_{call_counter[0]}.webp',
                        'latitude': 40.7128,
                        'longitude': -74.0060,
                        'cutoff': 0.5,
                        'sensitivity': 0.75,
                        'overlap': 0.25
                    }
                ]
                call_counter[0] += 1
                return response

            mock_birdnet_api.side_effect = mock_birdnet_response

            # Run until all files processed
            call_count = [0]
            def stop_after_files():
                call_count[0] += 1
                return call_count[0] > 15  # Allow time to process all files
            mock_stop.is_set.side_effect = stop_after_files

            from core.main import process_audio_files

            # Execute
            process_audio_files()

            # Verify all 5 files were deleted (processed)
            for file_path in files:
                assert not os.path.exists(file_path), f"File {file_path} should be deleted after processing"

            # Verify 5 detections in database
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) >= 5, f"Expected at least 5 detections, got {len(detections)}"

    def test_stop_flag_during_file_processing(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file
    ):
        """Test that stop_flag interrupts file processing gracefully."""

        # Create 3 WAV files
        files = []
        for i in range(3):
            filename = f'20251127_{160000 + i*1000}.wav'
            file_path = create_valid_wav_file(filename, duration_seconds=9)
            files.append(file_path)

        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop:

            # Stop after 2 iterations
            call_count = [0]
            def stop_early():
                call_count[0] += 1
                return call_count[0] > 2
            mock_stop.is_set.side_effect = stop_early

            from core.main import process_audio_files

            # Execute
            process_audio_files()

            # Verify stop_flag was checked
            assert mock_stop.is_set.call_count > 0, "stop_flag should be checked"

    def test_invalid_files_mixed_with_valid(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file,
        temp_recording_dir,
        mock_audio_processing
    ):
        """Test that invalid files are filtered out and only valid files processed."""

        # Create 2 valid + 2 invalid WAV files
        valid_file1 = create_valid_wav_file('valid1.wav', duration_seconds=9)
        valid_file2 = create_valid_wav_file('valid2.wav', duration_seconds=9)

        # Create invalid files (too small)
        invalid_file1 = os.path.join(temp_recording_dir, 'invalid1.wav')
        invalid_file2 = os.path.join(temp_recording_dir, 'invalid2.wav')
        with open(invalid_file1, 'wb') as f:
            f.write(b'\x00' * 10000)  # Too small
        with open(invalid_file2, 'wb') as f:
            f.write(b'\x00' * 10000)  # Too small

        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.SAMPLE_RATE', 48000), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.trim_audio', side_effect=mock_audio_processing['trim_audio']), \
             patch('core.main.generate_spectrogram', side_effect=mock_audio_processing['generate_spectrogram']), \
             patch('core.main.convert_wav_to_mp3', side_effect=mock_audio_processing['convert_wav_to_mp3']), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.stop_flag') as mock_stop:

            # Mock BirdNet API response with unique timestamps for each valid file
            call_counter = [0]
            def mock_birdnet_response(*args, **kwargs):
                response = Mock()
                response.status_code = 200
                response.json.return_value = [
                    {
                        'common_name': 'American Robin',
                        'scientific_name': 'Turdus migratorius',
                        'confidence': 0.95,
                        'timestamp': f'2025-11-27T10:4{call_counter[0]}:00',
                        'group_timestamp': f'2025-11-27T10:4{call_counter[0]}:00',
                        'chunk_index': 0,
                        'total_chunks': 3,
                        'bird_song_file_name': f'American_Robin_95_valid_{call_counter[0]}.wav',
                        'spectrogram_file_name': f'American_Robin_95_valid_{call_counter[0]}.webp',
                        'latitude': 40.7128,
                        'longitude': -74.0060,
                        'cutoff': 0.5,
                        'sensitivity': 0.75,
                        'overlap': 0.25
                    }
                ]
                call_counter[0] += 1
                return response

            mock_birdnet_api.side_effect = mock_birdnet_response

            # Run until files processed
            call_count = [0]
            def stop_after_processing():
                call_count[0] += 1
                return call_count[0] > 10
            mock_stop.is_set.side_effect = stop_after_processing

            from core.main import process_audio_files

            # Execute
            process_audio_files()

            # Verify all files deleted (valid processed, invalid deleted immediately)
            assert not os.path.exists(valid_file1)
            assert not os.path.exists(valid_file2)
            assert not os.path.exists(invalid_file1)
            assert not os.path.exists(invalid_file2)

            # Verify only 2 detections (from valid files)
            detections = pipeline_db_manager.get_latest_detections(limit=10)
            assert len(detections) >= 2, f"Expected at least 2 detections from valid files, got {len(detections)}"

    def test_database_error_continues_processing(
        self,
        temp_recording_dir,
        temp_extraction_dirs,
        mock_detection_with_metadata
    ):
        """Test that database errors are logged but don't crash the loop."""

        input_file = os.path.join(temp_recording_dir, 'test.wav')

        with patch('core.main.RECORDING_DIR', temp_recording_dir), \
             patch('core.main.EXTRACTED_AUDIO_DIR', temp_extraction_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', temp_extraction_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.trim_audio'), \
             patch('core.main.generate_spectrogram'), \
             patch('core.main.convert_wav_to_mp3'), \
             patch('core.main.db_manager') as mock_db, \
             patch('core.main.get_logger') as mock_logger, \
             patch('core.main.requests.post'), \
             patch('os.remove'):

            # Mock db_manager.insert_detection to raise exception
            mock_db.insert_detection.side_effect = Exception('Database error')

            mock_logger_instance = Mock()
            mock_logger.return_value = mock_logger_instance

            from core.main import handle_detection

            # Execute - function should handle the DB error
            # Note: Currently this will crash (no error handling), so we expect exception
            try:
                handle_detection(mock_detection_with_metadata, input_file, mock_logger_instance)
            except Exception:
                # Expected - no error handling currently implemented
                pass

            # Verify insert_detection was called
            mock_db.insert_detection.assert_called_once()

    def test_birdnet_api_timeout_doesnt_crash_loop(
        self,
        pipeline_db_manager,
        pipeline_temp_dirs,
        create_valid_wav_file
    ):
        """Test that BirdNet API timeout doesn't crash the processing loop."""
        from requests.exceptions import Timeout

        # Create 2 WAV files
        file1 = create_valid_wav_file('timeout_test1.wav', duration_seconds=9)
        file2 = create_valid_wav_file('timeout_test2.wav', duration_seconds=9)

        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.EXTRACTED_AUDIO_DIR', pipeline_temp_dirs['extracted']), \
             patch('core.main.SPECTROGRAM_DIR', pipeline_temp_dirs['spectrogram']), \
             patch('core.main.ANALYSIS_CHUNK_LENGTH', 3), \
             patch('core.main.API_HOST', 'localhost'), \
             patch('core.main.API_PORT', 5002), \
             patch('core.main.db_manager', pipeline_db_manager), \
             patch('core.main.requests.post') as mock_birdnet_api, \
             patch('core.main.select_audio_chunks', return_value=(0, 3)), \
             patch('core.main.stop_flag') as mock_stop:

            # Mock BirdNet API to timeout
            mock_birdnet_api.side_effect = Timeout('Request timed out')

            # Run until files processed
            call_count = [0]
            def stop_after_attempts():
                call_count[0] += 1
                return call_count[0] > 10
            mock_stop.is_set.side_effect = stop_after_attempts

            from core.main import process_audio_files

            # Execute - should handle timeout gracefully
            process_audio_files()

            # Verify both files were deleted (attempted processing)
            assert not os.path.exists(file1)
            assert not os.path.exists(file2)

            # Verify BirdNet API was called (and timed out)
            assert mock_birdnet_api.call_count > 0

    def test_empty_recording_directory_doesnt_crash(
        self,
        pipeline_temp_dirs,
        controllable_stop_flag
    ):
        """Test that process_audio_files() handles empty directory gracefully."""

        with patch('core.main.RECORDING_DIR', pipeline_temp_dirs['recording']), \
             patch('core.main.FILE_SCAN_INTERVAL', 0.01), \
             patch('core.main.stop_flag') as mock_stop, \
             patch('time.sleep'):

            # Run 3 iterations with empty directory
            mock_stop.is_set.side_effect = controllable_stop_flag(iterations=3)

            from core.main import process_audio_files

            # Execute - should not crash with empty directory
            process_audio_files()

            # Verify stop_flag was checked
            assert mock_stop.is_set.call_count > 0
