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

    def test_keeps_top_n_per_species(self, populated_db_for_cleanup):
        """Should not return top N recordings by confidence for each species."""
        # With keep_per_species=60:
        # - Common Bird (100 detections): 40 should be candidates
        # - Rare Bird (50 detections): 0 candidates (all within limit)
        # - Very Rare Bird (10 detections): 0 candidates (all within limit)
        candidates = populated_db_for_cleanup.get_cleanup_candidates(keep_per_species=60)

        species_in_candidates = set(c['common_name'] for c in candidates)
        assert 'Common Bird' in species_in_candidates
        assert 'Rare Bird' not in species_in_candidates  # Only 50, all kept
        assert 'Very Rare Bird' not in species_in_candidates  # Only 10, all kept

        # Should have exactly 40 candidates (100 - 60 from Common Bird)
        assert len(candidates) == 40

    def test_returns_oldest_first(self, populated_db_for_cleanup):
        """Should order results by timestamp ascending (oldest first)."""
        candidates = populated_db_for_cleanup.get_cleanup_candidates(keep_per_species=60)

        timestamps = [c['timestamp'] for c in candidates]
        assert timestamps == sorted(timestamps)

    def test_respects_limit(self, populated_db_for_cleanup):
        """Should respect the limit parameter."""
        candidates = populated_db_for_cleanup.get_cleanup_candidates(keep_per_species=60, limit=10)
        assert len(candidates) == 10

    def test_no_candidates_when_all_within_limit(self, test_db_manager):
        """Should return empty when all species have fewer than keep_per_species."""
        # Insert only 30 detections for one species
        from datetime import datetime, timedelta
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for i in range(30):
            detection = {
                'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'group_timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'scientific_name': 'Testus birdus',
                'common_name': 'Test Bird',
                'confidence': 0.75 + (i % 20) * 0.01,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        candidates = test_db_manager.get_cleanup_candidates(keep_per_species=60)
        assert len(candidates) == 0


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


class TestEstimateDeletableSize:
    """Tests for storage_manager.estimate_deletable_size()"""

    def test_estimates_size_correctly(self, populated_db_for_cleanup):
        """Should estimate deletable size based on candidate count."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                from core.storage_manager import estimate_deletable_size

                estimated_bytes, count = estimate_deletable_size(
                    populated_db_for_cleanup, keep_per_species=60
                )

                # Should have 40 candidates (100 - 60 from Common Bird)
                assert count == 40
                # Estimated at ~300KB each
                assert estimated_bytes == 40 * 300 * 1024

    def test_returns_zero_when_no_candidates(self, test_db_manager):
        """Should return zero when all within keep limit."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                from core.storage_manager import estimate_deletable_size

                estimated_bytes, count = estimate_deletable_size(
                    test_db_manager, keep_per_species=60
                )

                assert count == 0
                assert estimated_bytes == 0


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
                # Mock disk usage at 70% (below 80% target)
                with patch('core.storage_manager.get_disk_usage') as mock_usage:
                    mock_usage.return_value = {
                        'total_bytes': 100 * 1024**3,
                        'used_bytes': 70 * 1024**3,
                        'free_bytes': 30 * 1024**3,
                        'percent_used': 70.0
                    }

                    from core.storage_manager import cleanup_storage

                    result = cleanup_storage(populated_db_for_cleanup, target_percent=80)

                    assert result['files_deleted'] == 0
                    assert result['bytes_freed'] == 0
                    assert result['target_reached'] == True

    def test_cleanup_respects_keep_per_species(self, populated_db_for_cleanup):
        """Should keep top N recordings per species by confidence."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.EXTRACTED_AUDIO_DIR', '/tmp/audio'):
                with patch('config.settings.SPECTROGRAM_DIR', '/tmp/spectrograms'):
                    with patch('config.settings.user_settings', {'storage': {}}):
                        # Mock disk usage at 90%
                        with patch('core.storage_manager.get_disk_usage') as mock_usage:
                            mock_usage.return_value = {
                                'total_bytes': 100 * 1024**3,
                                'used_bytes': 90 * 1024**3,
                                'free_bytes': 10 * 1024**3,
                                'percent_used': 90.0
                            }

                            with patch('core.storage_manager.get_file_size') as mock_size:
                                mock_size.return_value = 300 * 1024  # 300KB per file

                                with patch('core.storage_manager.delete_detection_files') as mock_delete:
                                    mock_delete.return_value = {
                                        'deleted_audio': True,
                                        'deleted_spectrogram': True,
                                        'bytes_freed': 300 * 1024
                                    }

                                    from core.storage_manager import cleanup_storage

                                    result = cleanup_storage(
                                        populated_db_for_cleanup,
                                        target_percent=80,
                                        keep_per_species=60
                                    )

                                    # Should only delete from candidates (40 available)
                                    # Not all 160 detections
                                    assert result['files_deleted'] <= 40

    def test_warns_when_target_unachievable(self, populated_db_for_cleanup):
        """Should set target_achievable=False when BirdNET data insufficient."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.EXTRACTED_AUDIO_DIR', '/tmp/audio'):
                with patch('config.settings.SPECTROGRAM_DIR', '/tmp/spectrograms'):
                    with patch('config.settings.user_settings', {'storage': {}}):
                        # Mock disk usage at 90% - needs 10GB to reach 80%
                        with patch('core.storage_manager.get_disk_usage') as mock_usage:
                            mock_usage.return_value = {
                                'total_bytes': 100 * 1024**3,
                                'used_bytes': 90 * 1024**3,
                                'free_bytes': 10 * 1024**3,
                                'percent_used': 90.0
                            }

                            # But only 40 candidates * 300KB = 12MB available
                            with patch('core.storage_manager.get_file_size') as mock_size:
                                mock_size.return_value = 300 * 1024

                                with patch('core.storage_manager.delete_detection_files') as mock_delete:
                                    mock_delete.return_value = {
                                        'deleted_audio': True,
                                        'deleted_spectrogram': True,
                                        'bytes_freed': 300 * 1024
                                    }

                                    from core.storage_manager import cleanup_storage

                                    result = cleanup_storage(
                                        populated_db_for_cleanup,
                                        target_percent=80,
                                        keep_per_species=60
                                    )

                                    # Should flag that target is not achievable
                                    assert result['target_achievable'] == False
                                    assert result['target_reached'] == False
