"""
Tests for utility functions in api.py

These tests focus on:
- Caching functions
- Settings management
- Helper functions
"""
import json
import time
from unittest.mock import Mock, mock_open, patch


class TestImageCaching:
    """Test the image caching functionality."""

    def test_cache_miss(self):
        """Test cache miss returns None."""
        from core.api import get_cached_image

        # Clear any existing cache
        with patch('core.api.image_cache', {}):
            result = get_cached_image('Unknown Bird')
            assert result is None

    def test_cache_hit(self):
        """Test cache hit returns cached data."""
        from core.api import get_cached_image, set_cached_image

        # Clear cache and add test data
        with patch('core.api.image_cache', {}):
            test_data = {'imageUrl': 'http://example.com/bird.jpg'}
            set_cached_image('Test Bird', test_data)

            # Retrieve from cache
            result = get_cached_image('Test Bird')
            assert result == test_data

    def test_cache_expiration(self):
        """Test that expired cache entries return None."""
        from core.api import CACHE_EXPIRATION, get_cached_image

        # Create expired cache entry
        expired_time = time.time() - CACHE_EXPIRATION - 1
        mock_cache = {
            'Old Bird': {
                'data': {'imageUrl': 'http://old.jpg'},
                'timestamp': expired_time
            }
        }

        with patch('core.api.image_cache', mock_cache):
            result = get_cached_image('Old Bird')
            assert result is None  # Should return None for expired entry


class TestSettingsManagement:
    """Test settings loading and saving functions."""

    def test_load_user_settings_default(self):
        """Test loading settings returns defaults when file doesn't exist."""
        from core.api import load_user_settings

        with patch('os.path.exists', return_value=False):
            settings = load_user_settings()

            # Check default structure
            assert 'location' in settings
            assert settings['location']['latitude'] == 42.47
            assert 'detection' in settings
            assert settings['detection']['sensitivity'] == 0.75
            assert 'audio' in settings
            assert 'spectrogram' in settings

    def test_load_user_settings_from_file(self):
        """Test loading settings from existing file."""
        from core.api import load_user_settings

        user_settings = {
            'location': {'latitude': 40.0, 'longitude': -70.0},
            'detection': {'sensitivity': 0.9}
        }

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(user_settings))):
                settings = load_user_settings()

                # User settings should override defaults
                assert settings['location']['latitude'] == 40.0
                assert settings['detection']['sensitivity'] == 0.9
                # But other defaults should remain
                assert settings['audio']['sample_rate'] == 48000

    def test_save_user_settings_atomic(self):
        """Test atomic save of user settings."""
        from core.api import save_user_settings

        test_settings = {'test': 'data'}

        with patch('os.makedirs') as mock_makedirs:
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('os.rename') as mock_rename:
                    save_user_settings(test_settings)

                    # Should create directory
                    mock_makedirs.assert_called_once()

                    # Should write to temp file
                    mock_file.assert_called()
                    written_path = mock_file.call_args[0][0]
                    assert written_path.endswith('.tmp')

                    # Should rename temp file to final
                    mock_rename.assert_called_once()
                    assert mock_rename.call_args[0][1].endswith('user_settings.json')


class TestFlagFileWriting:
    """Test flag file functionality."""

    def test_write_flag(self):
        """Test writing flag files."""
        from core.api import write_flag

        with patch('os.makedirs') as mock_makedirs:
            with patch('builtins.open', mock_open()) as mock_file:
                write_flag('test-flag')

                # Should create flags directory
                mock_makedirs.assert_called_once()

                # Should write timestamp to flag file
                mock_file.assert_called()
                written_path = mock_file.call_args[0][0]
                assert 'test-flag' in written_path
                assert written_path.endswith('test-flag')


class TestBroadcastDetection:
    """Test WebSocket broadcasting functionality."""

    def test_broadcast_detection_with_socketio(self):
        """Test broadcasting when socketio is available."""
        from core.api import broadcast_detection

        mock_socketio = Mock()

        with patch('core.api.socketio', mock_socketio):
            test_data = {
                'common_name': 'Test Bird',
                'confidence': 0.95
            }

            broadcast_detection(test_data)

            # Should emit to 'bird_detected' event
            mock_socketio.emit.assert_called_once_with('bird_detected', test_data)

    def test_broadcast_detection_no_socketio(self):
        """Test broadcasting when socketio is None."""
        from core.api import broadcast_detection

        with patch('core.api.socketio', None):
            # Should not raise error even if socketio is None
            broadcast_detection({'test': 'data'})  # Should complete without error


# Test for deep merge functionality in load_user_settings
class TestSettingsMerge:
    """Test the settings merge functionality."""

    def test_deep_merge_preserves_defaults(self):
        """Test that deep merge preserves default values not in user settings."""
        from core.api import load_user_settings

        # User only specifies some settings
        partial_settings = {
            'location': {'latitude': 50.0},  # Only latitude, not longitude
            'audio': {'stream_url': 'http://custom.stream'}
        }

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(partial_settings))):
                settings = load_user_settings()

                # User values should be there
                assert settings['location']['latitude'] == 50.0
                assert settings['audio']['stream_url'] == 'http://custom.stream'

                # Default values should still be there
                assert settings['location']['longitude'] == -76.45  # default
                assert settings['audio']['sample_rate'] == 48000  # default
                assert settings['detection']['sensitivity'] == 0.75  # completely default section
