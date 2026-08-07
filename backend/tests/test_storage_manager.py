"""
Tests for the storage_manager module.

Tests cover:
- Disk usage calculation
- File path construction
- Protected species detection
- Cleanup candidate selection
- File deletion logic
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


def make_detection(timestamp, **overrides):
    """Detection insert payload where only the varied fields stand out."""
    detection = {
        'timestamp': timestamp,
        'group_timestamp': timestamp,
        'scientific_name': 'Testus birdus',
        'common_name': 'Test Bird',
        'confidence': 0.85,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25,
    }
    detection.update(overrides)
    return detection


def create_detection_files(detections, audio_dir, spectrogram_dir,
                           audio_size=1000, spectrogram_size=500):
    """Write real (sparse) files matching each detection's expected filenames."""
    import json

    from core.utils import build_detection_filenames

    for detection in detections:
        extra = detection.get('extra') or {}
        if isinstance(extra, str):
            extra = json.loads(extra)
        names = build_detection_filenames(
            detection['common_name'], detection['confidence'],
            detection['timestamp'],
            audio_source=extra.get('source_label') or None)
        for name, directory, size in (
                (names['audio_filename'], audio_dir, audio_size),
                (names['spectrogram_filename'], spectrogram_dir, spectrogram_size)):
            with open(os.path.join(directory, name), 'wb') as f:
                f.seek(size - 1)
                f.write(b'\0')


def mock_disk_usage_needing(bytes_to_free, total_bytes=100 * 1024**3,
                            target_percent=80):
    """Disk usage dict where reaching target_percent requires bytes_to_free."""
    used = int(total_bytes * target_percent / 100) + bytes_to_free
    return {
        'total_bytes': total_bytes,
        'used_bytes': used,
        'free_bytes': total_bytes - used,
        # unrounded so a small bytes_to_free still reads as above-target
        'percent_used': used / total_bytes * 100
    }


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
            test_db_manager.insert_detection(make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                common_name=common,
                scientific_name=scientific,
                confidence=0.75 + (i % 20) * 0.01,
            ))

    return test_db_manager


@pytest.fixture
def storage_dirs(tmp_path):
    """Real media directories, with the config patches cleanup reads applied.

    Yields (audio_dir, spectrogram_dir). The patches stay active for the
    test body, so `from core.storage_manager import ...` inside the test
    (re-imported per test by conftest's reset_imports) picks them up.
    """
    audio_dir = str(tmp_path / 'audio')
    spectrogram_dir = str(tmp_path / 'spectrograms')
    os.makedirs(audio_dir)
    os.makedirs(spectrogram_dir)

    with patch('config.settings.BASE_DIR', str(tmp_path)), \
            patch('config.settings.EXTRACTED_AUDIO_DIR', audio_dir), \
            patch('config.settings.SPECTROGRAM_DIR', spectrogram_dir), \
            patch('config.settings.user_settings', {'storage': {}}):
        yield audio_dir, spectrogram_dir


class TestGetCleanupProtectedIds:
    """Tests for db.get_cleanup_protected_ids()"""

    def test_keeps_top_n_per_species(self, populated_db_for_cleanup):
        """Protection covers the top N by confidence for each species."""
        # With keep_per_species=60, keep_recent_per_species=0:
        # - Common Bird (100 detections): 60 protected, 40 candidates
        # - Rare Bird (50) and Very Rare Bird (10): fully protected
        protected, total = populated_db_for_cleanup.get_cleanup_protected_ids(
            keep_per_species=60, keep_recent_per_species=0
        )

        assert total == 160
        assert len(protected) == 120  # 60 + 50 + 10
        assert total - len(protected) == 40  # candidates: Common Bird only

        # The unprotected rows must all be Common Bird
        with populated_db_for_cleanup.get_db_connection() as conn:
            rows = conn.execute("SELECT id, common_name FROM detections").fetchall()
        unprotected_species = {r['common_name'] for r in rows if r['id'] not in protected}
        assert unprotected_species == {'Common Bird'}

    def test_protects_latest_recordings(self, populated_db_for_cleanup):
        """The N most recent detections per species are protected."""
        protected, total = populated_db_for_cleanup.get_cleanup_protected_ids(
            keep_per_species=0, keep_recent_per_species=16
        )

        assert total == 160
        # 16 newest for Common and Rare Bird; Very Rare Bird has only 10
        assert len(protected) == 16 + 16 + 10

        # For each species, the protected rows must be exactly the 16 newest
        with populated_db_for_cleanup.get_db_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, common_name, timestamp FROM detections").fetchall()]
        from collections import defaultdict
        per_species = defaultdict(list)
        for r in rows:
            per_species[r['common_name']].append(r)
        for species_rows in per_species.values():
            newest_16 = {r['id'] for r in sorted(
                species_rows, key=lambda r: r['timestamp'], reverse=True)[:16]}
            assert newest_16 <= protected

    def test_union_of_confidence_and_recency_protection(self, populated_db_for_cleanup):
        """The protected set is the union of both rules."""
        protected, _ = populated_db_for_cleanup.get_cleanup_protected_ids(
            keep_per_species=60, keep_recent_per_species=16
        )

        # Recompute both sets for Common Bird in Python and compare
        with populated_db_for_cleanup.get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, confidence FROM detections WHERE common_name = 'Common Bird'"
            ).fetchall()
        all_common = [dict(r) for r in rows]
        latest_16_ids = {r['id'] for r in sorted(all_common, key=lambda r: r['timestamp'], reverse=True)[:16]}
        top_60_ids = {r['id'] for r in sorted(all_common, key=lambda r: r['confidence'], reverse=True)[:60]}

        common_protected = {r['id'] for r in all_common} & protected
        # Ties on equal confidence values may pick different rows than the
        # Python sort, so compare sizes plus the unambiguous members.
        assert len(common_protected) == len(latest_16_ids | top_60_ids)
        assert latest_16_ids <= common_protected

    def test_no_candidates_when_all_within_limit(self, test_db_manager):
        """Everything is protected when species are under the keep limit."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for i in range(30):
            test_db_manager.insert_detection(make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                confidence=0.75 + (i % 20) * 0.01,
            ))

        protected, total = test_db_manager.get_cleanup_protected_ids(
            keep_per_species=60, keep_recent_per_species=0
        )
        assert total == 30
        assert len(protected) == 30

    def test_blank_scientific_name_keys_by_common_name(self, test_db_manager):
        """Legacy rows with blank scientific_name are protected per common_name."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for common in ('Legacy Bird A', 'Legacy Bird B'):
            for i in range(5):
                test_db_manager.insert_detection(make_detection(
                    (base_time - timedelta(hours=i)).isoformat(),
                    scientific_name='',
                    common_name=common,
                ))

        protected, total = test_db_manager.get_cleanup_protected_ids(
            keep_per_species=3, keep_recent_per_species=0
        )
        assert total == 10
        assert len(protected) == 6  # 3 per legacy species, not 3 overall


class TestGetCleanupScanBatch:
    """Tests for db.get_cleanup_scan_batch()"""

    def test_returns_oldest_first_and_respects_limit(self, populated_db_for_cleanup):
        """Batches come back oldest first, at most `limit` rows."""
        batch = populated_db_for_cleanup.get_cleanup_scan_batch(limit=10)
        assert len(batch) == 10
        keys = [(d['timestamp'], d['id']) for d in batch]
        assert keys == sorted(keys)

    def test_keyset_walk_covers_every_row_once(self, populated_db_for_cleanup):
        """Walking with after_timestamp/after_id visits all rows exactly once."""
        seen = []
        after_timestamp = after_id = None
        while True:
            batch = populated_db_for_cleanup.get_cleanup_scan_batch(
                after_timestamp=after_timestamp, after_id=after_id, limit=50)
            seen.extend(batch)
            if len(batch) < 50:
                break
            after_timestamp = batch[-1]['timestamp']
            after_id = batch[-1]['id']

        assert len(seen) == 160
        assert len({d['id'] for d in seen}) == 160
        keys = [(d['timestamp'], d['id']) for d in seen]
        assert keys == sorted(keys)

    def test_returns_filename_metadata(self, test_db_manager):
        """Scan rows include source metadata for filename reconstruction."""
        import json

        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for i in range(5):
            test_db_manager.insert_detection(make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                confidence=0.75 + i * 0.01,
                extra={'source_label': 'Backyard_Mic'},
                audio_source='alsa_input.usb-test',
            ))

        batch = test_db_manager.get_cleanup_scan_batch(limit=100)
        assert len(batch) == 5
        for detection in batch:
            assert 'extra' in detection
            extra = detection['extra']
            if isinstance(extra, str):
                extra = json.loads(extra)
            assert extra.get('source_label') == 'Backyard_Mic'
            assert detection['audio_source'] == 'alsa_input.usb-test'


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

    def test_constructs_paths_with_source_label(self):
        """Should include source_label suffix in filenames when present in extra."""
        with patch('config.settings.EXTRACTED_AUDIO_DIR', '/app/data/audio/extracted_songs'):
            with patch('config.settings.SPECTROGRAM_DIR', '/app/data/spectrograms'):
                from core.storage_manager import get_detection_files

                detection = {
                    'common_name': 'American Robin',
                    'confidence': 0.85,
                    'timestamp': '2024-01-15T10:30:00',
                    'extra': '{"source_label": "Backyard_Mic"}',
                    'audio_source': 'source_0',
                }

                paths = get_detection_files(detection)

                assert paths['audio_path'].endswith('_Backyard_Mic.mp3')
                assert paths['spectrogram_path'].endswith('_Backyard_Mic.webp')

    def test_falls_back_to_legacy_source_id(self, storage_dirs):
        """Rows from the source-ID transition resolve their suffixed files."""
        audio_dir, spectrogram_dir = storage_dirs

        from core.utils import build_detection_filenames

        names = build_detection_filenames(
            'Test Bird', 0.85, '2024-01-15T10:30:00',
            audio_source='source_0')
        legacy_audio = os.path.join(audio_dir, names['audio_filename'])
        legacy_spectrogram = os.path.join(
            spectrogram_dir, names['spectrogram_filename'])
        with open(legacy_audio, 'w') as f:
            f.write('audio')
        with open(legacy_spectrogram, 'w') as f:
            f.write('spectrogram')

        from core.storage_manager import get_detection_files

        paths = get_detection_files({
            'common_name': 'Test Bird',
            'confidence': 0.85,
            'timestamp': '2024-01-15T10:30:00',
            'extra': '{}',
            'audio_source': 'source_0',
        })

        assert paths['audio_path'] == legacy_audio
        assert paths['spectrogram_path'] == legacy_spectrogram

    def test_source_id_row_can_fall_back_to_unsuffixed_file(self, storage_dirs):
        """Imported rows with a source id can still own unsuffixed files."""
        audio_dir, _ = storage_dirs
        unsuffixed_audio = os.path.join(
            audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')
        with open(unsuffixed_audio, 'w') as f:
            f.write('audio')

        from core.storage_manager import get_detection_files

        paths = get_detection_files({
            'common_name': 'Test Bird',
            'confidence': 0.85,
            'timestamp': '2024-01-15T10:30:00',
            'extra': '{}',
            'audio_source': 'source_0',
        })

        assert paths['audio_path'] == unsuffixed_audio

    def test_fallback_to_legacy_colon_pattern(self, storage_dirs):
        """Should fall back to legacy colon-pattern files if dash-pattern not found."""
        audio_dir, spectrogram_dir = storage_dirs

        # Create legacy files with colon pattern
        legacy_audio = os.path.join(audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3')
        legacy_spectrogram = os.path.join(spectrogram_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.webp')
        with open(legacy_audio, 'w') as f:
            f.write('audio')
        with open(legacy_spectrogram, 'w') as f:
            f.write('spectrogram')

        from core.storage_manager import get_detection_files

        detection = {
            'common_name': 'Test Bird',
            'confidence': 0.85,
            'timestamp': '2024-01-15T10:30:00'
        }

        paths = get_detection_files(detection)

        # Should return the legacy paths since dash-pattern doesn't exist
        assert paths['audio_path'] == legacy_audio
        assert paths['spectrogram_path'] == legacy_spectrogram

    def test_prefers_dash_pattern_when_exists(self, storage_dirs):
        """Should prefer dash-pattern files when they exist."""
        audio_dir, _ = storage_dirs

        # Create both dash and colon pattern files
        dash_audio = os.path.join(audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')
        colon_audio = os.path.join(audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3')
        with open(dash_audio, 'w') as f:
            f.write('dash audio')
        with open(colon_audio, 'w') as f:
            f.write('colon audio')

        from core.storage_manager import get_detection_files

        detection = {
            'common_name': 'Test Bird',
            'confidence': 0.85,
            'timestamp': '2024-01-15T10:30:00'
        }

        paths = get_detection_files(detection)

        # Should return the dash-pattern path (new format)
        assert paths['audio_path'] == dash_audio


class TestEstimateDeletableSize:
    """Tests for storage_manager.estimate_deletable_size()"""

    def test_estimates_size_correctly(self, populated_db_for_cleanup):
        """Should estimate deletable size based on candidate count."""
        with patch('config.settings.BASE_DIR', '/tmp'):
            with patch('config.settings.user_settings', {'storage': {}}):
                from core.storage_manager import estimate_deletable_size

                estimated_bytes, count = estimate_deletable_size(
                    populated_db_for_cleanup, keep_per_species=60, keep_recent_per_species=0
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
                    test_db_manager, keep_per_species=60, keep_recent_per_species=0
                )

                assert count == 0
                assert estimated_bytes == 0


class TestDeleteDetectionFiles:
    """Tests for storage_manager.delete_detection_files()"""

    def test_deletes_existing_files(self, storage_dirs):
        """Should delete files that exist and return bytes freed."""
        audio_dir, spectrogram_dir = storage_dirs

        # Create test files
        audio_file = os.path.join(audio_dir, 'test.mp3')
        spectrogram_file = os.path.join(spectrogram_dir, 'test.webp')

        with open(audio_file, 'wb') as f:
            f.write(b'x' * 1000)  # 1KB audio
        with open(spectrogram_file, 'wb') as f:
            f.write(b'x' * 500)  # 0.5KB spectrogram

        from core.storage_manager import delete_detection_files

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

            assert result['deleted_audio']
            assert result['deleted_spectrogram']
            assert result['deleted_filenames'] == ['test.mp3', 'test.webp']
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

                        assert not result['deleted_audio']
                        assert not result['deleted_spectrogram']
                        assert result['deleted_filenames'] == []
                        assert result['bytes_freed'] == 0


class TestCleanupStorage:
    """Tests for storage_manager.cleanup_storage()"""

    def test_no_cleanup_if_below_target(self, populated_db_for_cleanup, storage_dirs):
        """Should not delete anything if already below target."""
        # Disk usage at 70%, below the 80% target
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(0, target_percent=70)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(populated_db_for_cleanup, target_percent=80)

        assert result['files_deleted'] == 0
        assert result['bytes_freed'] == 0
        assert result['target_reached']

    def test_cleanup_respects_keep_per_species(self, populated_db_for_cleanup, storage_dirs):
        """Deletes only unprotected recordings' files; protected files stay."""
        audio_dir, spectrogram_dir = storage_dirs
        with populated_db_for_cleanup.get_db_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT common_name, confidence, timestamp, extra"
                " FROM detections").fetchall()]
        create_detection_files(rows, audio_dir, spectrogram_dir)

        # Needs 10GB freed — far more than available, so cleanup runs
        # through every candidate
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                populated_db_for_cleanup,
                target_percent=80,
                keep_per_species=60,
                keep_recent_per_species=0
            )

        # Exactly the 40 Common Bird candidates deleted; the 120
        # protected recordings keep their files
        assert result['files_deleted'] == 40
        assert result['skipped_missing'] == 0
        assert len(os.listdir(audio_dir)) == 120
        assert len(os.listdir(spectrogram_dir)) == 120

    def test_warns_when_target_unachievable(self, populated_db_for_cleanup, storage_dirs):
        """Should set target_achievable=False when BirdNET data insufficient."""
        # Needs 10GB, but only 40 candidates * 300KB estimated deletable
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                populated_db_for_cleanup,
                target_percent=80,
                keep_per_species=60,
                keep_recent_per_species=0
            )

        assert not result['target_achievable']
        assert not result['target_reached']

    def test_cleanup_resolves_multi_source_filenames(self, test_db_manager, storage_dirs):
        """Cleanup should correctly resolve filenames for multi-source detections."""
        audio_dir, spectrogram_dir = storage_dirs
        base_time = datetime(2024, 1, 15, 10, 0, 0)

        detections = []
        for i in range(70):
            detection = make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                confidence=0.75 + (i % 20) * 0.01,
                extra={'source_label': 'Backyard_Mic'},
                audio_source='alsa_input.usb-test',
            )
            detections.append(detection)
            test_db_manager.insert_detection(detection)

        create_detection_files(detections, audio_dir, spectrogram_dir)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                test_db_manager,
                target_percent=80,
                keep_per_species=60,
                keep_recent_per_species=0
            )

        # Pre-fix: all would be skipped_missing because the looked-up
        # filenames lacked the _Backyard_Mic suffix
        assert result['skipped_missing'] == 0
        assert result['files_deleted'] == 10  # 70 - 60 protected

    def test_cleanup_deletes_legacy_source_id_files(self, test_db_manager,
                                                    storage_dirs):
        """Cleanup finds files created before source-label filenames."""
        audio_dir, spectrogram_dir = storage_dirs

        from core.utils import build_detection_filenames

        for i in range(3):
            timestamp = f'2024-01-15T10:0{i}:00'
            detection = make_detection(
                timestamp, extra={}, audio_source='source_0')
            test_db_manager.insert_detection(detection)
            names = build_detection_filenames(
                'Test Bird', 0.85, timestamp, audio_source='source_0')
            for name, directory in (
                    (names['audio_filename'], audio_dir),
                    (names['spectrogram_filename'], spectrogram_dir)):
                with open(os.path.join(directory, name), 'wb') as f:
                    f.write(b'x' * 100)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['skipped_missing'] == 0
        assert result['files_deleted'] == 3
        assert len(os.listdir(audio_dir)) == 0
        assert len(os.listdir(spectrogram_dir)) == 0

    def test_cleanup_deletes_legacy_colon_files(self, test_db_manager, storage_dirs):
        """Rows whose files still use the legacy colon pattern are found via
        the normalized directory snapshot and deleted through the legacy
        fallback path resolution."""
        audio_dir, spectrogram_dir = storage_dirs

        from core.utils import build_detection_filenames, get_legacy_filename

        for i in range(3):
            timestamp = f'2024-01-15T10:0{i}:00'
            test_db_manager.insert_detection(make_detection(timestamp))
            names = build_detection_filenames('Test Bird', 0.85, timestamp)
            for name, directory in ((names['audio_filename'], audio_dir),
                                    (names['spectrogram_filename'], spectrogram_dir)):
                with open(os.path.join(directory, get_legacy_filename(name)), 'wb') as f:
                    f.write(b'x' * 100)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['skipped_missing'] == 0
        assert result['files_deleted'] == 3
        assert len(os.listdir(audio_dir)) == 0
        assert len(os.listdir(spectrogram_dir)) == 0

    def test_cleanup_walks_in_bounded_batches(self, test_db_manager, storage_dirs):
        """The walk fetches rows in bounded keyset batches, never all at once."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for i in range(70):
            test_db_manager.insert_detection(make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                confidence=0.75 + (i % 20) * 0.01,
            ))

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)), \
                patch('core.storage_manager._SCAN_BATCH_ROWS', 25), \
                patch.object(test_db_manager, 'get_cleanup_scan_batch',
                             wraps=test_db_manager.get_cleanup_scan_batch) as mock_scan:
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                test_db_manager,
                target_percent=80,
                keep_per_species=0,
                keep_recent_per_species=16
            )

        # 70 rows in batches of 25 → 3 fetches, each bounded
        assert mock_scan.call_count == 3
        for call in mock_scan.call_args_list:
            assert call.kwargs['limit'] == 25
        # 54 candidates (70 - 16 recent), all file-less
        assert result['skipped_missing'] == 54
        assert result['files_deleted'] == 0

    def test_second_run_resumes_past_processed_rows(self, test_db_manager, storage_dirs):
        """A run given the previous run's cursor resumes the walk instead of
        re-scanning the dead prefix."""
        audio_dir, spectrogram_dir = storage_dirs
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        detections = []
        for i in range(20):
            # i=0 is oldest here so the walk order matches insertion order
            detection = make_detection((base_time + timedelta(hours=i)).isoformat())
            detections.append(detection)
            test_db_manager.insert_detection(detection)

        # The 5 oldest rows have no files (a dead prefix); the rest have
        # 600KB of files each
        create_detection_files(
            detections[5:], audio_dir, spectrogram_dir,
            audio_size=600 * 1024, spectrogram_size=1)

        # Each run needs ~1MB freed → two deletions
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(1024**2)):
            from core.storage_manager import cleanup_storage

            first = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)
            second = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0,
                resume_cursor=first['resume_cursor'])

        # First run scans the dead prefix once, then deletes two
        assert first['skipped_missing'] == 5
        assert first['files_deleted'] == 2
        assert first['target_reached']
        # Second run resumes past everything already processed
        assert second['skipped_missing'] == 0
        assert second['files_deleted'] == 2
        assert second['target_reached']

    def test_exhausted_resume_falls_back_to_full_walk(self, test_db_manager, storage_dirs):
        """When the resumed walk can't reach the target, rows behind the
        cursor are re-checked (files regained via migration, protection
        changes)."""
        audio_dir, spectrogram_dir = storage_dirs
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        detections = []
        for i in range(10):
            detection = make_detection((base_time + timedelta(hours=i)).isoformat())
            detections.append(detection)
            test_db_manager.insert_detection(detection)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(400 * 1024)):
            from core.storage_manager import cleanup_storage

            # First run: no files anywhere — walks all rows, cursor ends at
            # the newest row
            first = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

            # A file appears behind the cursor (as after a migration import
            # backfills an old detection)
            create_detection_files(
                detections[2:3], audio_dir, spectrogram_dir,
                audio_size=600 * 1024, spectrogram_size=1)

            second = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0,
                resume_cursor=first['resume_cursor'])

        assert first['files_deleted'] == 0
        assert first['skipped_missing'] == 10
        # Resume finds nothing new; the fallback walk catches the
        # backfilled file behind the cursor
        assert second['files_deleted'] == 1
        assert second['target_reached']
        assert len(os.listdir(audio_dir)) == 0

    def test_target_reached_on_final_deletion(self, test_db_manager, storage_dirs):
        """target_reached should be True when final deletion crosses the threshold."""
        audio_dir, spectrogram_dir = storage_dirs
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        # Insert 62 detections so we get exactly 2 candidates with keep=60
        detections = []
        for i in range(62):
            detection = make_detection(
                (base_time - timedelta(hours=i)).isoformat(),
                confidence=0.75 + (i % 20) * 0.01,
            )
            detections.append(detection)
            test_db_manager.insert_detection(detection)

        # ~600KB per detection; freeing 1MB takes two
        create_detection_files(
            detections, audio_dir, spectrogram_dir,
            audio_size=600 * 1024, spectrogram_size=1)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(1024**2)):
            from core.storage_manager import cleanup_storage

            result = cleanup_storage(
                test_db_manager,
                target_percent=80,
                keep_per_species=60,
                keep_recent_per_species=0
            )

        # 2 candidates, each freeing ~600KB against a 1MB goal:
        # the second deletion crosses the threshold
        assert result['target_reached'] is True
        assert result['files_deleted'] == 2
