"""
Tests for the storage_manager module.

Tests cover:
- Disk usage calculation
- Protected species detection
- Cleanup candidate selection
- File deletion and filename-variant resolution
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

    # core.db imports core.storage_manager at import time (delete path),
    # so the module is usually already loaded with the real dirs bound
    # before these patches run — patch its attributes directly as well.
    with patch('config.settings.BASE_DIR', str(tmp_path)), \
            patch('config.settings.EXTRACTED_AUDIO_DIR', audio_dir), \
            patch('config.settings.SPECTROGRAM_DIR', spectrogram_dir), \
            patch('config.settings.user_settings', {'storage': {}}), \
            patch('core.storage_manager.EXTRACTED_AUDIO_DIR', audio_dir), \
            patch('core.storage_manager.SPECTROGRAM_DIR', spectrogram_dir):
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


class TestGetCleanupCandidatesBatch:
    """Candidate batches come from the live-media partial index: only rows
    that still own files, oldest first, keyset-resumable."""

    def _resolved_row(self, db, timestamp, size=100):
        detection_id = db.insert_detection(make_detection(timestamp))
        with db.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = db.get_media_nonce(detection_id)
            import core.media_ownership as mo
            mo.record_media(cur, detection_id, [
                {'filename': f'c_{detection_id}-{nonce}.mp3',
                 'kind': 'audio', 'rank': 0, 'bytes': size}])
            conn.commit()
        return detection_id

    def test_only_rows_with_files_are_candidates(self, test_db_manager):
        with_files = self._resolved_row(test_db_manager, '2024-01-02T10:00:00')
        test_db_manager.insert_detection(
            make_detection('2024-01-01T10:00:00'))  # resolved-empty

        batch = test_db_manager.get_cleanup_candidates_batch(limit=10)
        assert [row['id'] for row in batch] == [with_files]

    def test_oldest_first_keyset_walk(self, test_db_manager):
        ids = [self._resolved_row(test_db_manager, f'2024-01-0{d}T10:00:00')
               for d in (3, 1, 2)]
        first = test_db_manager.get_cleanup_candidates_batch(limit=2)
        assert [r['id'] for r in first] == [ids[1], ids[2]]
        rest = test_db_manager.get_cleanup_candidates_batch(
            after_timestamp=first[-1]['timestamp'], after_id=first[-1]['id'],
            limit=2)
        assert [r['id'] for r in rest] == [ids[0]]

    def test_uses_the_partial_index(self, test_db_manager):
        self._resolved_row(test_db_manager, '2024-01-01T10:00:00')
        with test_db_manager.get_db_connection() as conn:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT id, timestamp, media_bytes "
                "FROM detections WHERE media_bytes > 0 "
                "ORDER BY timestamp ASC, id ASC LIMIT 10").fetchall()
        assert any('idx_detections_live_media' in row[3] for row in plan)


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


class TestEstimateDeletableSize:
    """Exact recorded bytes for resolved rows; labeled estimate while the
    frontier still has unresolved history."""

    def test_exact_when_frontier_complete(self, test_db_manager):
        detection_id = test_db_manager.insert_detection(
            make_detection('2024-01-01T10:00:00'))
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            import core.media_ownership as mo
            nonce = test_db_manager.get_media_nonce(detection_id)
            mo.record_media(cur, detection_id, [
                {'filename': f'e_{detection_id}-{nonce}.mp3',
                 'kind': 'audio', 'rank': 0, 'bytes': 12345}])
            conn.commit()
        from core.media_frontier import advance_frontier
        while not advance_frontier(test_db_manager)['complete']:
            pass

        from core.storage_manager import estimate_deletable_size
        deletable, exact = estimate_deletable_size(
            test_db_manager, keep_per_species=0, keep_recent_per_species=0)
        assert exact is True
        assert deletable == 12345

    def test_estimates_unresolved_history(self, test_db_manager):
        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, media_bytes) "
                "VALUES ('2024-01-01T10:00:00', '2024-01-01T10:00:00', "
                "'Turdus migratorius', 'American Robin', 0.9, NULL)")
            conn.commit()

        from core.storage_manager import (
            ESTIMATED_SIZE_PER_DETECTION,
            estimate_deletable_size,
        )
        deletable, exact = estimate_deletable_size(
            test_db_manager, keep_per_species=0, keep_recent_per_species=0)
        assert exact is False
        assert deletable == ESTIMATED_SIZE_PER_DETECTION


def write_media_file(path, size=100):
    with open(path, 'wb') as f:
        f.write(b'x' * size)


class TestDeleteDetectionFiles:
    """Tests for storage_manager.delete_detection_files()

    Deletion resolves every filename variant a row can own (source label,
    transition-era source id, unsuffixed, legacy colon pattern) and removes
    all copies it finds — a survivor would be orphaned forever, since
    cleanup only ever revisits DB rows.
    """

    def test_deletes_existing_files(self, storage_dirs):
        """Canonical dash-pattern files are deleted and reported audio-first."""
        audio_dir, spectrogram_dir = storage_dirs
        audio_file = os.path.join(
            audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')
        spectrogram_file = os.path.join(
            spectrogram_dir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.webp')
        write_media_file(audio_file, 1000)
        write_media_file(spectrogram_file, 500)

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection('2024-01-15T10:30:00'))

        assert result['deleted_filenames'] == [
            'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3',
            'Test_Bird_85_2024-01-15-birdnet-10-30-00.webp',
        ]
        assert result['bytes_freed'] == 1500
        assert not os.path.exists(audio_file)
        assert not os.path.exists(spectrogram_file)

    def test_handles_missing_files_gracefully(self, storage_dirs):
        """No files on disk means an empty report, not an error."""
        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection('2024-01-15T10:30:00'))

        assert result == {'deleted_filenames': [], 'bytes_freed': 0}

    def test_deletes_source_label_files(self, storage_dirs):
        """Rows with a saved source label delete their suffixed files."""
        audio_dir, spectrogram_dir = storage_dirs

        from core.utils import build_detection_filenames

        names = build_detection_filenames(
            'Test Bird', 0.85, '2024-01-15T10:30:00',
            audio_source='Backyard_Mic')
        write_media_file(os.path.join(audio_dir, names['audio_filename']))
        write_media_file(
            os.path.join(spectrogram_dir, names['spectrogram_filename']))

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection(
            '2024-01-15T10:30:00',
            extra='{"source_label": "Backyard_Mic"}',
            audio_source='source_0'))

        assert result['deleted_filenames'] == [
            names['audio_filename'], names['spectrogram_filename']]

    def test_deletes_legacy_source_id_files(self, storage_dirs):
        """Transition-era rows delete files suffixed with the raw source id."""
        audio_dir, spectrogram_dir = storage_dirs

        from core.utils import build_detection_filenames

        names = build_detection_filenames(
            'Test Bird', 0.85, '2024-01-15T10:30:00', audio_source='source_0')
        write_media_file(os.path.join(audio_dir, names['audio_filename']))
        write_media_file(
            os.path.join(spectrogram_dir, names['spectrogram_filename']))

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection(
            '2024-01-15T10:30:00', extra='{}', audio_source='source_0'))

        assert result['deleted_filenames'] == [
            names['audio_filename'], names['spectrogram_filename']]

    def test_source_id_row_deletes_unsuffixed_files(self, storage_dirs):
        """Imported rows with a source id can still own unsuffixed files."""
        audio_dir, _ = storage_dirs
        unsuffixed_audio = os.path.join(
            audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3')
        write_media_file(unsuffixed_audio)

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection(
            '2024-01-15T10:30:00', extra='{}', audio_source='source_0'))

        assert result['deleted_filenames'] == [
            'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3']
        assert not os.path.exists(unsuffixed_audio)

    def test_deletes_legacy_colon_pattern_files(self, storage_dirs):
        """Legacy colon-pattern files are found and reported by their real names."""
        audio_dir, spectrogram_dir = storage_dirs
        colon_audio = os.path.join(
            audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3')
        colon_spectrogram = os.path.join(
            spectrogram_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.webp')
        write_media_file(colon_audio)
        write_media_file(colon_spectrogram)

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection('2024-01-15T10:30:00'))

        assert result['deleted_filenames'] == [
            'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3',
            'Test_Bird_85_2024-01-15-birdnet-10:30:00.webp',
        ]
        assert not os.path.exists(colon_audio)
        assert not os.path.exists(colon_spectrogram)

    def test_deletes_all_coexisting_variants(self, storage_dirs):
        """A row owning copies under several naming eras loses all of them."""
        audio_dir, _ = storage_dirs

        from core.utils import build_detection_filenames

        suffixed = build_detection_filenames(
            'Test Bird', 0.85, '2024-01-15T10:30:00',
            audio_source='source_0')['audio_filename']
        unsuffixed = 'Test_Bird_85_2024-01-15-birdnet-10-30-00.mp3'
        colon = 'Test_Bird_85_2024-01-15-birdnet-10:30:00.mp3'
        for name in (suffixed, unsuffixed, colon):
            write_media_file(os.path.join(audio_dir, name), 100)

        from core.storage_manager import delete_detection_files

        result = delete_detection_files(make_detection(
            '2024-01-15T10:30:00', extra='{}', audio_source='source_0'))

        assert sorted(result['deleted_filenames']) == sorted(
            [suffixed, unsuffixed, colon])
        assert result['bytes_freed'] == 300
        assert not os.listdir(audio_dir)


class TestCleanupStorage:
    """The query-driven cleanup: partial-index candidates, exact accounting,
    pressure-driven frontier advance, no full-table re-walks."""

    def _media_env(self, monkeypatch, tmp_path):
        """Patch KIND_DIRS on the instance the cleanup chain actually uses
        (storage_manager imports unlink_owned_files by value from the
        freshest core.media_ownership generation)."""
        import core.media_ownership as mo
        import core.storage_manager  # noqa: F401 - ensure the chain is loaded
        audio_dir = tmp_path / 'audio'
        spec_dir = tmp_path / 'spec'
        audio_dir.mkdir(exist_ok=True)
        spec_dir.mkdir(exist_ok=True)
        monkeypatch.setitem(mo.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(mo.KIND_DIRS, 'spectrogram', str(spec_dir))
        return mo, audio_dir, spec_dir

    def _resolved_row_with_file(self, db, mo, audio_dir, timestamp, size,
                                species=('American Robin', 'Turdus migratorius')):
        common, sci = species
        detection_id = db.insert_detection(make_detection(
            timestamp, common_name=common, scientific_name=sci))
        nonce = db.get_media_nonce(detection_id)
        name = f'f_{detection_id}-{nonce}.mp3'
        with db.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': size}])
            conn.commit()
        (audio_dir / name).write_bytes(b'x' * size)
        return detection_id, audio_dir / name

    def test_no_cleanup_if_below_target(self, test_db_manager):
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(0, target_percent=70)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(test_db_manager, target_percent=80)
        assert result['files_deleted'] == 0
        assert result['target_reached']

    def test_gated_until_index_exists(self, test_db_manager, monkeypatch, tmp_path):
        self._media_env(monkeypatch, tmp_path)
        with test_db_manager.get_db_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_detections_live_media")
            conn.commit()
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(test_db_manager, target_percent=80)
        assert result['files_deleted'] == 0
        assert not result['target_reached']

    def test_deletes_oldest_unprotected_until_target(
            self, test_db_manager, monkeypatch, tmp_path):
        mo, audio_dir, _ = self._media_env(monkeypatch, tmp_path)
        rows = [self._resolved_row_with_file(
                    test_db_manager, mo, audio_dir,
                    f'2024-01-0{d}T10:00:00', 400 * 1024)
                for d in range(1, 6)]
        # Need ~1MB freed: the two oldest 400KB files plus one more
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(1024 * 1024)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['target_reached']
        assert result['files_deleted'] == 3
        # deleted oldest-first: first three gone, newest two remain
        assert not rows[0][1].exists() and not rows[1][1].exists()
        assert rows[3][1].exists() and rows[4][1].exists()
        # their ownership rows and stamps followed
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT media_bytes FROM detections WHERE id = ?",
                (rows[0][0],)).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 2

    def test_protected_rows_keep_their_files(
            self, test_db_manager, monkeypatch, tmp_path):
        mo, audio_dir, _ = self._media_env(monkeypatch, tmp_path)
        old_id, old_file = self._resolved_row_with_file(
            test_db_manager, mo, audio_dir, '2024-01-01T10:00:00', 1000)
        new_id, new_file = self._resolved_row_with_file(
            test_db_manager, mo, audio_dir, '2024-01-02T10:00:00', 1000)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=1, keep_recent_per_species=0)

        # top-1 by confidence is protected; both rows share confidence so
        # protection lands deterministically on one of them
        assert result['files_deleted'] == 1
        assert old_file.exists() != new_file.exists()

    def test_partial_unlink_survivor_stays_candidate(
            self, test_db_manager, monkeypatch, tmp_path):
        """A file that fails to unlink keeps its ownership row and its
        row's media_bytes contribution — retried next run, never stamped
        away while it still exists."""
        mo, audio_dir, _ = self._media_env(monkeypatch, tmp_path)
        detection_id, path = self._resolved_row_with_file(
            test_db_manager, mo, audio_dir, '2024-01-01T10:00:00', 1000)

        real_remove = os.remove

        def failing_remove(p):
            if p.endswith(path.name):
                raise PermissionError('EACCES')
            return real_remove(p)

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)), \
             patch('core.media_ownership.os.remove', side_effect=failing_remove):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['files_deleted'] == 0
        assert path.exists()
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT media_bytes FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0] == 1000

    def test_pressure_drives_the_frontier(self, test_db_manager, monkeypatch, tmp_path):
        """With no resolved candidates but unresolved history on disk,
        cleanup advances the frontier synchronously and then deletes the
        surfaced files — one implementation, no disabled window."""
        mo, audio_dir, _ = self._media_env(monkeypatch, tmp_path)
        import core.media_frontier as mf
        monkeypatch.setitem(mf.KIND_DIRS, 'audio', mo.KIND_DIRS['audio'])
        monkeypatch.setitem(mf.KIND_DIRS, 'spectrogram', mo.KIND_DIRS['spectrogram'])

        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, extra) "
                "VALUES ('2024-01-01T10:30:00', '2024-01-01T10:30:00', "
                "'Turdus migratorius', 'American Robin', 0.9, '{}')")
            conn.commit()
        legacy_file = audio_dir / 'American_Robin_90_2024-01-01-birdnet-10-30-00.mp3'
        legacy_file.write_bytes(b'legacy')

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['files_deleted'] == 1
        assert not legacy_file.exists()
        assert result['frontier_complete']

    def test_unachievable_is_single_pass_when_frontier_complete(
            self, test_db_manager, monkeypatch, tmp_path):
        """The stuck-disk state costs one cheap candidate pass — never the
        old every-cycle full-table re-walk."""
        mo, audio_dir, _ = self._media_env(monkeypatch, tmp_path)
        self._resolved_row_with_file(
            test_db_manager, mo, audio_dir, '2024-01-01T10:00:00', 1000)
        from core.media_frontier import advance_frontier
        while not advance_frontier(test_db_manager)['complete']:
            pass

        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(10 * 1024**3)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['target_achievable'] is False
        assert result['target_reached'] is False
        assert result['files_deleted'] == 1  # freed what it could, once
        assert result['frontier_complete'] is True


class TestScheduledPolicies:
    """Retention and media-budget policies through the shared executor:
    protections always win, daily durable gating, off by default."""

    def _media_env(self, monkeypatch, tmp_path):
        import core.media_ownership as mo
        import core.storage_manager  # noqa: F401
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir(exist_ok=True)
        monkeypatch.setitem(mo.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(mo.KIND_DIRS, 'spectrogram', str(tmp_path))
        return mo, audio_dir

    def _row(self, db, mo, audio_dir, timestamp, size=1000):
        detection_id = db.insert_detection(make_detection(timestamp))
        nonce = db.get_media_nonce(detection_id)
        name = f'p_{detection_id}-{nonce}.mp3'
        with db.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': size}])
            conn.commit()
        (audio_dir / name).write_bytes(b'x' * size)
        return detection_id, audio_dir / name

    def _config(self, **overrides):
        base = {
            'auto_cleanup_enabled': True, 'trigger_percent': 85,
            'target_percent': 80, 'keep_per_species': 0,
            'keep_recent_per_species': 0, 'check_interval_minutes': 30,
            'retention_days': 0, 'media_budget_gb': 0,
        }
        base.update(overrides)
        return base

    def test_disabled_policies_do_nothing(self, test_db_manager, monkeypatch, tmp_path):
        self._media_env(monkeypatch, tmp_path)
        with patch('core.storage_manager._get_storage_config',
                   return_value=self._config()):
            from core.storage_manager import run_scheduled_policies
            assert run_scheduled_policies(test_db_manager) is None

    def test_retention_deletes_only_older_unprotected(
            self, test_db_manager, monkeypatch, tmp_path):
        mo, audio_dir = self._media_env(monkeypatch, tmp_path)
        from datetime import datetime, timedelta
        now = datetime(2026, 8, 15, 12, 0, 0)
        old_id, old_file = self._row(
            test_db_manager, mo, audio_dir, (now - timedelta(days=30)).isoformat())
        new_id, new_file = self._row(
            test_db_manager, mo, audio_dir, (now - timedelta(days=2)).isoformat())

        with patch('core.storage_manager._get_storage_config',
                   return_value=self._config(retention_days=7)), \
             patch('core.storage_manager.local_now', create=True), \
             patch('core.timezone_service.local_now', return_value=now):
            from core.storage_manager import run_scheduled_policies
            results = run_scheduled_policies(test_db_manager)

        assert results['retention']['files_deleted'] == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_retention_respects_protection(self, test_db_manager, monkeypatch, tmp_path):
        """Protections always win: a protected row keeps its media no
        matter how old (composition rule)."""
        mo, audio_dir = self._media_env(monkeypatch, tmp_path)
        from datetime import datetime
        now = datetime(2026, 8, 15, 12, 0, 0)
        _, old_file = self._row(test_db_manager, mo, audio_dir, '2020-01-01T00:00:00')

        with patch('core.storage_manager._get_storage_config',
                   return_value=self._config(retention_days=7,
                                             keep_per_species=60)), \
             patch('core.timezone_service.local_now', return_value=now):
            from core.storage_manager import run_scheduled_policies
            results = run_scheduled_policies(test_db_manager)

        assert results['retention']['files_deleted'] == 0
        assert old_file.exists()

    def test_budget_frees_down_to_the_cap(self, test_db_manager, monkeypatch, tmp_path):
        mo, audio_dir = self._media_env(monkeypatch, tmp_path)
        gb = 1024 ** 3
        files = [self._row(test_db_manager, mo, audio_dir,
                           f'2024-01-0{d}T10:00:00', size=1000)[1]
                 for d in range(1, 4)]
        # budget of ~2000 bytes expressed in GB
        budget_gb = 2000 / gb

        with patch('core.storage_manager._get_storage_config',
                   return_value=self._config(media_budget_gb=budget_gb)):
            from core.storage_manager import run_scheduled_policies
            results = run_scheduled_policies(test_db_manager)

        # 3000 bytes total, 2000 budget -> oldest file freed
        assert results['budget']['files_deleted'] == 1
        assert not files[0].exists() and files[1].exists() and files[2].exists()

    def test_daily_gate_is_durable(self, test_db_manager, monkeypatch, tmp_path):
        mo, audio_dir = self._media_env(monkeypatch, tmp_path)
        self._row(test_db_manager, mo, audio_dir, '2020-01-01T00:00:00')
        from datetime import datetime
        now = datetime(2026, 8, 15, 12, 0, 0)
        with patch('core.storage_manager._get_storage_config',
                   return_value=self._config(retention_days=7)), \
             patch('core.timezone_service.local_now', return_value=now):
            from core.storage_manager import run_scheduled_policies
            first = run_scheduled_policies(test_db_manager, today='2026-08-15')
            second = run_scheduled_policies(test_db_manager, today='2026-08-15')
            third = run_scheduled_policies(test_db_manager, today='2026-08-16')
        assert first is not None
        assert second is None  # same day: gated, durably (meta)
        assert third is not None  # next day runs again


class TestPreviewPolicy:

    def _setup(self, db, monkeypatch, tmp_path, timestamp='2020-01-01T00:00:00'):
        import core.media_ownership as mo
        import core.storage_manager  # noqa: F401
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir(exist_ok=True)
        monkeypatch.setitem(mo.KIND_DIRS, 'audio', str(audio_dir))
        detection_id = db.insert_detection(make_detection(timestamp))
        nonce = db.get_media_nonce(detection_id)
        name = f'q_{detection_id}-{nonce}.mp3'
        with db.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': 5000}])
            conn.commit()

    def test_retention_preview_is_exact_when_frontier_complete(
            self, test_db_manager, monkeypatch, tmp_path):
        self._setup(test_db_manager, monkeypatch, tmp_path)
        from core.media_frontier import advance_frontier
        while not advance_frontier(test_db_manager)['complete']:
            pass
        from datetime import datetime
        config = {'auto_cleanup_enabled': True, 'trigger_percent': 85,
                  'target_percent': 80, 'keep_per_species': 0,
                  'keep_recent_per_species': 0, 'check_interval_minutes': 30,
                  'retention_days': 7, 'media_budget_gb': 0}
        with patch('core.storage_manager._get_storage_config',
                   return_value=config), \
             patch('core.timezone_service.local_now',
                   return_value=datetime(2026, 8, 15, 12, 0, 0)):
            from core.storage_manager import preview_policy
            preview = preview_policy(test_db_manager, 'retention')
        assert preview == {'policy': 'retention', 'enabled': True,
                           'bytes': 5000, 'rows': 1, 'exact': True}

    def test_retention_preview_labels_unresolved_history(
            self, test_db_manager, monkeypatch, tmp_path):
        self._setup(test_db_manager, monkeypatch, tmp_path)
        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, media_bytes) "
                "VALUES ('2019-01-01T00:00:00', '2019-01-01T00:00:00', "
                "'Turdus migratorius', 'American Robin', 0.9, NULL)")
            conn.commit()
        from datetime import datetime

        from core.storage_manager import ESTIMATED_SIZE_PER_DETECTION
        config = {'auto_cleanup_enabled': True, 'trigger_percent': 85,
                  'target_percent': 80, 'keep_per_species': 0,
                  'keep_recent_per_species': 0, 'check_interval_minutes': 30,
                  'retention_days': 7, 'media_budget_gb': 0}
        with patch('core.storage_manager._get_storage_config',
                   return_value=config), \
             patch('core.timezone_service.local_now',
                   return_value=datetime(2026, 8, 15, 12, 0, 0)):
            from core.storage_manager import preview_policy
            preview = preview_policy(test_db_manager, 'retention')
        assert preview['exact'] is False
        assert preview['bytes'] == 5000 + ESTIMATED_SIZE_PER_DETECTION
        assert preview['rows'] == 2


class TestImplementationReviewFixes:
    """Regression pins for the 2026-08-15 implementation review findings."""

    def test_protected_unresolved_rows_are_not_counted_deletable(
            self, test_db_manager):
        """Finding 5: a protected row outside the frontier must not appear
        in the deletable estimate."""
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, media_bytes) "
                "VALUES ('2024-01-01T08:00:00', '2024-01-01T08:00:00', "
                "'Turdus migratorius', 'American Robin', 0.9, NULL)")
            conn.commit()
            row_id = cur.lastrowid
        # old-code inserts bypass the species rollup; protection reads it
        # (production heals this via the startup consistency rebuild)
        test_db_manager.rebuild_species_table()

        accounting = test_db_manager.get_media_accounting({row_id})
        assert accounting['unresolved_rows'] == 0

        from core.storage_manager import estimate_deletable_size
        deletable, exact = estimate_deletable_size(
            test_db_manager, keep_per_species=60, keep_recent_per_species=16)
        assert deletable == 0

    def test_achievable_verdict_follows_the_walk_not_the_estimate(
            self, test_db_manager, monkeypatch, tmp_path):
        """Finding 5: a legacy file bigger than the per-row estimate can
        reach the target even when the estimate said it could not — the
        result must never say unachievable AND reached."""
        import core.media_frontier as mf
        import core.media_ownership as mo
        import core.storage_manager  # noqa: F401
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(mo.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(mf.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(mf.KIND_DIRS, 'spectrogram', str(tmp_path))

        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, extra) "
                "VALUES ('2024-01-01T10:30:00', '2024-01-01T10:30:00', "
                "'Turdus migratorius', 'American Robin', 0.9, '{}')")
            conn.commit()
        big = audio_dir / 'American_Robin_90_2024-01-01-birdnet-10-30-00.mp3'
        big.write_bytes(b'x' * (1024 * 1024))  # 1MB vs 300KB estimate

        # need ~1MB freed: estimate (300KB) says unachievable, walk succeeds
        with patch('core.storage_manager.get_disk_usage',
                   return_value=mock_disk_usage_needing(1000 * 1024)):
            from core.storage_manager import cleanup_storage
            result = cleanup_storage(
                test_db_manager, target_percent=80,
                keep_per_species=0, keep_recent_per_species=0)

        assert result['target_reached'] is True
        assert result['target_achievable'] is True  # never contradictory
