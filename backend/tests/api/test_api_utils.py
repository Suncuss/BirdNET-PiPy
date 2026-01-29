"""
Tests for api_utils.py functions.

These tests focus on:
- serve_file_with_fallback() with legacy filename migration
"""
import os
import tempfile
from unittest.mock import patch, MagicMock
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
