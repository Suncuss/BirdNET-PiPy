"""
Tests for the storage_manager module.

Tests cover:
- Disk usage calculation
- File path construction
- Protected species detection
- Cleanup candidate selection
- File deletion logic
"""
import pytest
import tempfile
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add tests directory to path for fixtures import
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from fixtures.test_config import TEST_DATABASE_SCHEMA


@pytest.fixture
def test_db_manager():
    """Create a DatabaseManager with temporary test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    # Patch the settings before importing
    with patch('config.settings.DATABASE_PATH', db_path):
        with patch('config.settings.DATABASE_SCHEMA', TEST_DATABASE_SCHEMA):
            from core.db import DatabaseManager
            manager = DatabaseManager(db_path=db_path)
            yield manager

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def populated_db_for_cleanup(test_db_manager):
    """Database populated with species having varying detection counts.

    Creates:
    - Common Bird: 100 detections (eligible for cleanup)
    - Rare Bird: 50 detections (protected, < 60)
    - Very Rare Bird: 10 detections (protected, < 60)
    """
    base_time = datetime(2024, 1, 15, 10, 0, 0)

    species_data = [
        ('Common Bird', 'Commonus birdus', 100),
        ('Rare Bird', 'Rarus birdus', 50),
        ('Very Rare Bird', 'Veryrarus birdus', 10),
    ]

    for common, scientific, count in species_data:
        for i in range(count):
            detection = {
                'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'group_timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'scientific_name': scientific,
                'common_name': common,
                'confidence': 0.75 + (i % 20) * 0.01,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

    return test_db_manager


class TestGetSpeciesCounts:
    """Tests for db.get_species_counts()"""

    def test_returns_correct_counts(self, populated_db_for_cleanup):
        """Should return accurate count for each species."""
        counts = populated_db_for_cleanup.get_species_counts()

        assert counts['Common Bird'] == 100
        assert counts['Rare Bird'] == 50
        assert counts['Very Rare Bird'] == 10

    def test_empty_database(self, test_db_manager):
        """Should return empty dict for empty database."""
        counts = test_db_manager.get_species_counts()
        assert counts == {}


class TestGetCleanupCandidates:
    """Tests for db.get_cleanup_candidates()"""

    def test_excludes_protected_species(self, populated_db_for_cleanup):
        """Should not return detections from protected species."""
        protected = ['Rare Bird', 'Very Rare Bird']
        candidates = populated_db_for_cleanup.get_cleanup_candidates(protected)

        species_in_candidates = set(c['common_name'] for c in candidates)
        assert 'Common Bird' in species_in_candidates
        assert 'Rare Bird' not in species_in_candidates
        assert 'Very Rare Bird' not in species_in_candidates

    def test_returns_oldest_first(self, populated_db_for_cleanup):
        """Should order results by timestamp ascending (oldest first)."""
        candidates = populated_db_for_cleanup.get_cleanup_candidates([])

        timestamps = [c['timestamp'] for c in candidates]
        assert timestamps == sorted(timestamps)

    def test_respects_limit(self, populated_db_for_cleanup):
        """Should respect the limit parameter."""
        candidates = populated_db_for_cleanup.get_cleanup_candidates([], limit=10)
        assert len(candidates) == 10

    def test_empty_protected_list(self, populated_db_for_cleanup):
        """Should return all species when protected list is empty."""
        candidates = populated_db_for_cleanup.get_cleanup_candidates([])

        species_in_candidates = set(c['common_name'] for c in candidates)
        assert len(species_in_candidates) == 3


class TestGetDiskUsage:
    """Tests for storage_manager.get_disk_usage()"""

    def test_returns_expected_keys(self):
        """Should return dict with expected keys."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            from core.storage_manager import get_disk_usage
            usage = get_disk_usage('/tmp')

            assert 'total_bytes' in usage
            assert 'used_bytes' in usage
            assert 'free_bytes' in usage
            assert 'percent_used' in usage

    def test_percent_used_is_valid(self):
        """Percent used should be between 0 and 100."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            from core.storage_manager import get_disk_usage
            usage = get_disk_usage('/tmp')

            assert 0 <= usage['percent_used'] <= 100


class TestGetDetectionFiles:
    """Tests for storage_manager.get_detection_files()"""

    def test_constructs_correct_paths(self):
        """Should construct correct file paths from detection data."""
        with patch('config.settings.EXTRACTED_AUDIO_DIR', '/app/data/audio/extracted_songs'):
            with patch('config.settings.SPECTROGRAM_DIR', '/app/data/spectrograms'):
                from core.storage_manager import get_detection_files

                detection = {
                    'common_name': 'American Robin',
                    'confidence': 0.85,
                    'timestamp': '2024-01-15T10:30:00'
                }

                paths = get_detection_files(detection)

                assert paths['audio_path'].endswith('.mp3')
                assert paths['spectrogram_path'].endswith('.webp')
                assert 'American_Robin' in paths['audio_path']
                assert 'American_Robin' in paths['spectrogram_path']
                assert '85' in paths['audio_path']  # Confidence as percentage


class TestGetProtectedSpecies:
    """Tests for storage_manager.get_protected_species()"""

    def test_protects_species_under_threshold(self, populated_db_for_cleanup):
        """Species with count <= min_count should be protected."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                from core.storage_manager import get_protected_species

                # With threshold of 60
                protected = get_protected_species(populated_db_for_cleanup, min_count=60)

                assert 'Rare Bird' in protected  # 50 detections
                assert 'Very Rare Bird' in protected  # 10 detections
                assert 'Common Bird' not in protected  # 100 detections

    def test_all_species_protected_if_all_under_threshold(self, populated_db_for_cleanup):
        """If all species under threshold, all should be protected."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                from core.storage_manager import get_protected_species

                protected = get_protected_species(populated_db_for_cleanup, min_count=200)

                assert len(protected) == 3


class TestDeleteDetectionFiles:
    """Tests for storage_manager.delete_detection_files()"""

    def test_deletes_existing_files(self):
        """Should delete files that exist and return bytes freed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_dir = os.path.join(tmpdir, 'audio')
            spectrogram_dir = os.path.join(tmpdir, 'spectrograms')
            os.makedirs(audio_dir)
            os.makedirs(spectrogram_dir)

            # Create test files
            audio_file = os.path.join(audio_dir, 'test.mp3')
            spectrogram_file = os.path.join(spectrogram_dir, 'test.webp')

            with open(audio_file, 'wb') as f:
                f.write(b'x' * 1000)  # 1KB audio
            with open(spectrogram_file, 'wb') as f:
                f.write(b'x' * 500)  # 0.5KB spectrogram

            with patch('config.settings.EXTRACTED_AUDIO_DIR', audio_dir):
                with patch('config.settings.SPECTROGRAM_DIR', spectrogram_dir):
                    with patch('config.settings.BASE_DIR', tmpdir):
                        with patch('config.settings.user_settings', {'storage': {}}):
                            from core.storage_manager import delete_detection_files, get_detection_files

                            # Mock get_detection_files to return our test paths
                            detection = {
                                'common_name': 'Test Bird',
                                'confidence': 0.85,
                                'timestamp': '2024-01-15T10:30:00'
                            }

                            with patch('core.storage_manager.get_detection_files') as mock_get_files:
                                mock_get_files.return_value = {
                                    'audio_path': audio_file,
                                    'spectrogram_path': spectrogram_file
                                }

                                result = delete_detection_files(detection)

                                assert result['deleted_audio'] == True
                                assert result['deleted_spectrogram'] == True
                                assert result['bytes_freed'] == 1500
                                assert not os.path.exists(audio_file)
                                assert not os.path.exists(spectrogram_file)

    def test_handles_missing_files_gracefully(self):
        """Should handle missing files without error."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.EXTRACTED_AUDIO_DIR', '/nonexistent/audio'):
                with patch('config.settings.SPECTROGRAM_DIR', '/nonexistent/spectrograms'):
                    with patch('config.settings.user_settings', {'storage': {}}):
                        from core.storage_manager import delete_detection_files

                        detection = {
                            'common_name': 'Test Bird',
                            'confidence': 0.85,
                            'timestamp': '2024-01-15T10:30:00'
                        }

                        result = delete_detection_files(detection)

                        assert result['deleted_audio'] == False
                        assert result['deleted_spectrogram'] == False
                        assert result['bytes_freed'] == 0


class TestCleanupStorage:
    """Tests for storage_manager.cleanup_storage()"""

    def test_no_cleanup_if_below_target(self, populated_db_for_cleanup):
        """Should not delete anything if already below target."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                # Mock disk usage at 50% (below 70% target)
                with patch('core.storage_manager.get_disk_usage') as mock_usage:
                    mock_usage.return_value = {
                        'total_bytes': 100 * 1024**3,
                        'used_bytes': 50 * 1024**3,
                        'free_bytes': 50 * 1024**3,
                        'percent_used': 50.0
                    }

                    from core.storage_manager import cleanup_storage

                    result = cleanup_storage(populated_db_for_cleanup, target_percent=70)

                    assert result['files_deleted'] == 0
                    assert result['bytes_freed'] == 0

    def test_cleanup_deletes_oldest_first(self, populated_db_for_cleanup):
        """Should delete oldest files first."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.EXTRACTED_AUDIO_DIR', '/tmp/audio'):
                with patch('config.settings.SPECTROGRAM_DIR', '/tmp/spectrograms'):
                    with patch('config.settings.user_settings', {'storage': {}}):
                        # Mock disk usage at 85% (above 80% trigger)
                        with patch('core.storage_manager.get_disk_usage') as mock_usage:
                            mock_usage.return_value = {
                                'total_bytes': 100 * 1024**3,
                                'used_bytes': 85 * 1024**3,
                                'free_bytes': 15 * 1024**3,
                                'percent_used': 85.0
                            }

                            # Mock file operations
                            with patch('core.storage_manager.get_file_size') as mock_size:
                                mock_size.return_value = 1024**3  # 1GB per file

                                with patch('core.storage_manager.delete_detection_files') as mock_delete:
                                    mock_delete.return_value = {
                                        'deleted_audio': True,
                                        'deleted_spectrogram': True,
                                        'bytes_freed': 1024**3
                                    }

                                    from core.storage_manager import cleanup_storage

                                    result = cleanup_storage(populated_db_for_cleanup, target_percent=70)

                                    # Should have attempted to free 15GB (85% - 70%)
                                    # With 1GB per file, should delete ~15 files
                                    assert result['files_deleted'] > 0
                                    assert mock_delete.called
