"""
Tests for api_utils.py functions.

These tests focus on:
- serve_file_with_fallback() with legacy filename migration
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    """Create a minimal Flask app for testing."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


class TestServeFileWithFallback:
    """Tests for serve_file_with_fallback() function."""

    def test_serves_existing_file(self, app):
        """Should serve file directly when it exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = os.path.join(tmpdir, 'test_file.mp3')
            with open(test_file, 'w') as f:
                f.write('audio content')

            # Create default file
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response
                    serve_file_with_fallback(tmpdir, 'test_file.mp3', default_file, 'audio')

                    # Should serve the requested file
                    mock_send.assert_called_with(tmpdir, 'test_file.mp3')

    def test_migrates_legacy_colon_file_to_dash(self, app):
        """Should rename legacy colon-pattern file to dash-pattern and serve."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a legacy file with colon pattern
            legacy_file = os.path.join(tmpdir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3')
            with open(legacy_file, 'w') as f:
                f.write('audio content')

            # Create default file
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response
                    # Request with dash pattern (new format)
                    serve_file_with_fallback(
                        tmpdir,
                        'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3',
                        default_file,
                        'audio'
                    )

                    # Should have renamed the file
                    new_file = os.path.join(tmpdir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')
                    assert os.path.exists(new_file), "File should be renamed to dash pattern"
                    assert not os.path.exists(legacy_file), "Legacy file should no longer exist"

                    # Should serve the new filename
                    mock_send.assert_called_with(tmpdir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')

    def test_serves_default_when_file_not_found(self, app):
        """Should serve default file when neither pattern exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create default file only
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response
                    serve_file_with_fallback(
                        tmpdir,
                        'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3',
                        default_file,
                        'audio'
                    )

                    # Should serve the default file
                    mock_send.assert_called_with(tmpdir, 'default.mp3')

    def test_rejects_path_traversal(self, app):
        """Should reject filenames with path traversal attempts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create default file
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response

                    # Try path traversal
                    serve_file_with_fallback(
                        tmpdir,
                        '../../../etc/passwd',
                        default_file,
                        'audio'
                    )

                    # Should serve the default file, not the traversal path
                    mock_send.assert_called_with(tmpdir, 'default.mp3')

    def test_handles_rename_failure_gracefully(self, app):
        """Should serve from legacy location if rename fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a legacy file with colon pattern
            legacy_file = os.path.join(tmpdir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3')
            with open(legacy_file, 'w') as f:
                f.write('audio content')

            # Create default file
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response

                    # Mock os.rename to fail
                    with patch('core.api_utils.os.rename', side_effect=OSError("Permission denied")):
                        serve_file_with_fallback(
                            tmpdir,
                            'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3',
                            default_file,
                            'audio'
                        )

                        # Should serve from legacy location
                        mock_send.assert_called_with(
                            tmpdir,
                            'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3'
                        )

    def test_no_fallback_for_non_birdnet_files(self, app):
        """Should not try fallback for files without -birdnet- marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create default file only
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'w') as f:
                f.write('default')

            from core.api_utils import serve_file_with_fallback

            with app.app_context():
                with patch('core.api_utils.send_from_directory') as mock_send:
                    mock_response = MagicMock()
                    mock_send.return_value = mock_response
                    serve_file_with_fallback(
                        tmpdir,
                        'random_file.mp3',
                        default_file,
                        'audio'
                    )

                    # Should serve the default file
                    mock_send.assert_called_with(tmpdir, 'default.mp3')


@pytest.fixture
def recording_dirs():
    """A temp audio dir and spectrogram dir for recording_has_media() tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_dir = os.path.join(tmpdir, 'audio')
        spectrogram_dir = os.path.join(tmpdir, 'spectrograms')
        os.makedirs(audio_dir)
        os.makedirs(spectrogram_dir)
        yield audio_dir, spectrogram_dir


class TestRecordingHasMedia:
    """Tests for recording_has_media()."""

    def test_true_when_both_files_present(self, recording_dirs):
        from core.api_utils import recording_has_media
        audio_dir, spectrogram_dir = recording_dirs
        open(os.path.join(audio_dir, 'a.mp3'), 'wb').close()
        open(os.path.join(spectrogram_dir, 's.webp'), 'wb').close()
        rec = {'audio_filename': 'a.mp3', 'spectrogram_filename': 's.webp'}
        assert recording_has_media(rec, audio_dir, spectrogram_dir) is True

    def test_false_when_audio_missing(self, recording_dirs):
        from core.api_utils import recording_has_media
        audio_dir, spectrogram_dir = recording_dirs
        open(os.path.join(spectrogram_dir, 's.webp'), 'wb').close()
        rec = {'audio_filename': 'a.mp3', 'spectrogram_filename': 's.webp'}
        assert recording_has_media(rec, audio_dir, spectrogram_dir) is False

    def test_false_when_spectrogram_missing(self, recording_dirs):
        from core.api_utils import recording_has_media
        audio_dir, spectrogram_dir = recording_dirs
        open(os.path.join(audio_dir, 'a.mp3'), 'wb').close()
        rec = {'audio_filename': 'a.mp3', 'spectrogram_filename': 's.webp'}
        assert recording_has_media(rec, audio_dir, spectrogram_dir) is False

    def test_false_when_filename_absent_from_record(self, recording_dirs):
        from core.api_utils import recording_has_media
        audio_dir, spectrogram_dir = recording_dirs
        # No filenames in the record at all.
        assert recording_has_media({}, audio_dir, spectrogram_dir) is False
        # Audio name present but spectrogram name missing.
        open(os.path.join(audio_dir, 'a.mp3'), 'wb').close()
        rec = {'audio_filename': 'a.mp3'}
        assert recording_has_media(rec, audio_dir, spectrogram_dir) is False
