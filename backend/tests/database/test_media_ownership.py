"""Tests for the media ownership foundation (migration 4 + core.media_ownership).

Covers the versioned schema step (columns, tables, and the deliberate
absence of the live-media partial index on upgraded databases), nonce
minting on both insert paths, and the ownership API's identity, collision,
idempotency, and recompute semantics.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md.
"""
import os
import re
import sqlite3
import tempfile

import pytest

from core import media_ownership
from core.db import DatabaseManager
from core.db_schema import SCHEMA_VERSION
from core.media_ownership import (
    DetectionMissingError,
    MediaCollisionError,
    get_or_create_media_nonce,
    mint_media_nonce,
    publish_media_file,
    record_media,
    remove_media,
    rename_media,
)
from tests.database.conftest import insert_legacy

NONCE_RE = re.compile(r'^[0-9a-f]{32}$')

# The complete current schema minus everything migration 4 (and the shipped
# 1-3 steps) adds — what a station running the previous release has on disk.
V3_SCHEMA = """
CREATE TABLE detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    group_timestamp DATETIME NOT NULL,
    scientific_name VARCHAR(100) NOT NULL,
    common_name VARCHAR(100) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    cutoff DECIMAL(4,3),
    sensitivity DECIMAL(4,3),
    overlap DECIMAL(4,3),
    week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED,
    extra TEXT DEFAULT '{}',
    audio_source TEXT
);
CREATE INDEX idx_detections_timestamp ON detections(timestamp DESC);
PRAGMA user_version = 3;
"""


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    os.unlink(db_path)  # let sqlite create it fresh
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


def columns(db_path, table='detections'):
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def index_names(db_path):
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}


class TestMigration4:

    def test_v3_database_upgrades_without_live_media_index(self, temp_db_path):
        """An existing station's DB gains the columns and tables via the
        chain, but the O(rows) partial index is left to the coordinated
        main-container build — never startup."""
        with sqlite3.connect(temp_db_path) as conn:
            conn.executescript(V3_SCHEMA)

        DatabaseManager(db_path=temp_db_path)

        assert {'media_bytes', 'media_nonce'} <= columns(temp_db_path)
        assert {'detection_media', 'meta', 'rollup_dirty_day'} <= table_names(temp_db_path)
        assert 'idx_detections_live_media' not in index_names(temp_db_path)
        with sqlite3.connect(temp_db_path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    def test_fresh_database_gets_live_media_index(self, temp_db_path):
        DatabaseManager(db_path=temp_db_path)
        assert 'idx_detections_live_media' in index_names(temp_db_path)
        assert 'ux_detection_media_canonical' in index_names(temp_db_path)

    def test_migration_is_idempotent(self, temp_db_path):
        with sqlite3.connect(temp_db_path) as conn:
            conn.executescript(V3_SCHEMA)
        DatabaseManager(db_path=temp_db_path)
        DatabaseManager(db_path=temp_db_path)  # replay must be a no-op
        assert {'media_bytes', 'media_nonce'} <= columns(temp_db_path)

    def test_existing_rows_stay_null_unresolved(self, temp_db_path):
        """Pre-migration rows are the frontier's job — the schema step must
        not invent resolution state for them."""
        with sqlite3.connect(temp_db_path) as conn:
            conn.executescript(V3_SCHEMA)
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence) "
                "VALUES ('2026-01-01T00:00:00', '2026-01-01T00:00:00', "
                "'Turdus merula', 'Common Blackbird', 0.9)")
            conn.commit()
        DatabaseManager(db_path=temp_db_path)
        with sqlite3.connect(temp_db_path) as conn:
            row = conn.execute(
                "SELECT media_bytes, media_nonce FROM detections").fetchone()
        assert row == (None, None)


class TestInsertPathStamping:

    def test_insert_detection_mints_identity(self, test_db_manager, sample_detection):
        detection_id = test_db_manager.insert_detection(sample_detection)
        with test_db_manager.get_db_connection() as conn:
            row = conn.execute(
                "SELECT media_bytes, media_nonce FROM detections WHERE id = ?",
                (detection_id,)).fetchone()
        assert row['media_bytes'] == 0
        assert NONCE_RE.match(row['media_nonce'])

    def test_nonces_are_unique_per_row(self, test_db_manager, sample_detection):
        ids = [test_db_manager.insert_detection(sample_detection) for _ in range(5)]
        with test_db_manager.get_db_connection() as conn:
            nonces = [conn.execute(
                "SELECT media_nonce FROM detections WHERE id = ?",
                (i,)).fetchone()[0] for i in ids]
        assert len(set(nonces)) == len(nonces)


class TestNonceLifecycle:

    def test_mint_is_32_hex_chars(self):
        nonce = mint_media_nonce()
        assert NONCE_RE.match(nonce)
        assert mint_media_nonce() != nonce

    def test_lazy_init_converges_and_is_immutable(self, test_db_manager):
        detection_id = insert_legacy(test_db_manager, '2026-01-01T00:00:00')
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            first = get_or_create_media_nonce(cur, detection_id)
            second = get_or_create_media_nonce(cur, detection_id)
            conn.commit()
        assert NONCE_RE.match(first)
        assert first == second

    def test_lazy_init_missing_row_raises_before_any_publish(self, test_db_manager):
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            with pytest.raises(DetectionMissingError):
                get_or_create_media_nonce(cur, 999999)


class TestPublication:

    def test_publish_claims_final_name_and_removes_part(self, tmp_path):
        part = tmp_path / 'clip.mp3.part'
        part.write_bytes(b'audio-bytes')
        final = tmp_path / 'clip.mp3'
        size = publish_media_file(str(part), str(final))
        assert size == len(b'audio-bytes')
        assert final.exists() and not part.exists()

    def test_publish_never_clobbers(self, tmp_path):
        """An existing final name (another history's file) must surface as a
        collision, never be silently replaced — POSIX rename would replace,
        which is why publication uses link+unlink."""
        final = tmp_path / 'clip.mp3'
        final.write_bytes(b'previous-history')
        part = tmp_path / 'clip.mp3.part'
        part.write_bytes(b'new-history')
        with pytest.raises(MediaCollisionError):
            publish_media_file(str(part), str(final))
        assert final.read_bytes() == b'previous-history'
        assert part.exists()  # caller cleans up; nothing was destroyed


class TestRecordMedia:

    def _files(self, detection_id, nonce):
        suffix = media_ownership.media_name_suffix(detection_id, nonce)
        return [
            {'filename': f'Common_Blackbird_90_2026-01-01-birdnet-00-00-00_{suffix}.mp3',
             'kind': 'audio', 'rank': 0, 'bytes': 270_000},
            {'filename': f'Common_Blackbird_90_2026-01-01-birdnet-00-00-00_{suffix}.webp',
             'kind': 'spectrogram', 'rank': 0, 'bytes': 30_000},
        ]

    def _insert_and_record(self, manager, sample_detection):
        detection_id = manager.insert_detection(sample_detection)
        with manager.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = cur.execute(
                "SELECT media_nonce FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0]
            files = self._files(detection_id, nonce)
            record_media(cur, detection_id, files)
            conn.commit()
        return detection_id, files

    def test_records_ownership_and_recomputes_bytes(self, test_db_manager, sample_detection):
        detection_id, files = self._insert_and_record(test_db_manager, sample_detection)
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT media_bytes FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0] == 300_000
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media WHERE detection_id = ?",
                (detection_id,)).fetchone()[0] == 2

    def test_retry_is_a_no_op(self, test_db_manager, sample_detection):
        detection_id, files = self._insert_and_record(test_db_manager, sample_detection)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            record_media(cur, detection_id, files)  # same owner, same claim
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 2

    def test_foreign_claim_is_a_collision(self, test_db_manager, sample_detection):
        detection_id, files = self._insert_and_record(test_db_manager, sample_detection)
        other_id = test_db_manager.insert_detection(sample_detection)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            with pytest.raises(MediaCollisionError):
                record_media(cur, other_id, [dict(files[0])])

    def test_missing_detection_leaves_no_residue(self, test_db_manager):
        """A delete winning the race must not produce ownership rows."""
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            with pytest.raises(DetectionMissingError):
                record_media(cur, 424242, [
                    {'filename': 'ghost.mp3', 'kind': 'audio',
                     'rank': 0, 'bytes': 1}])
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0

    def test_second_canonical_per_kind_is_impossible(self, test_db_manager, sample_detection):
        """The rank-0 invariant is enforced by the database, not convention."""
        detection_id, _ = self._insert_and_record(test_db_manager, sample_detection)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            with pytest.raises(sqlite3.IntegrityError):
                cur.execute(
                    "INSERT INTO detection_media "
                    "(filename, detection_id, kind, rank, bytes) "
                    "VALUES ('second-canonical.mp3', ?, 'audio', 0, 1)",
                    (detection_id,))

    def test_remove_media_recomputes_and_keeps_survivors(self, test_db_manager, sample_detection):
        detection_id, files = self._insert_and_record(test_db_manager, sample_detection)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            affected = remove_media(cur, [files[0]['filename']])
            conn.commit()
            assert affected == {detection_id}
            # Partial unlink: the surviving spectrogram is still owned and
            # the row is NOT stamped to zero.
            assert conn.execute(
                "SELECT media_bytes FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0] == 30_000

    def test_rename_media_follows_lazy_migration(self, test_db_manager, sample_detection):
        detection_id, files = self._insert_and_record(test_db_manager, sample_detection)
        old = files[0]['filename']
        new = old.replace('.mp3', '.renamed.mp3')
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            assert rename_media(cur, old, new) is True
            assert rename_media(cur, 'never-existed.mp3', 'x.mp3') is False
            conn.commit()
            assert conn.execute(
                "SELECT detection_id FROM detection_media WHERE filename = ?",
                (new,)).fetchone()[0] == detection_id


class TestReadContract:
    """_normalize_detection: resolved rows use recorded names only;
    unresolved rows keep synthesized names; identity fields never leak."""

    def _resolved_with_media(self, manager, sample_detection):
        detection_id = manager.insert_detection(sample_detection)
        with manager.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = cur.execute(
                "SELECT media_nonce FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0]
            suffix = media_ownership.media_name_suffix(detection_id, nonce)
            record_media(cur, detection_id, [
                {'filename': f'American_Robin_95_x_{suffix}.mp3',
                 'kind': 'audio', 'rank': 0, 'bytes': 100},
                {'filename': f'American_Robin_95_x_{suffix}.webp',
                 'kind': 'spectrogram', 'rank': 0, 'bytes': 50},
            ])
            conn.commit()
        return detection_id, suffix

    def test_resolved_row_serves_recorded_names(self, test_db_manager, sample_detection):
        detection_id, suffix = self._resolved_with_media(test_db_manager, sample_detection)
        detection = test_db_manager.get_detection_by_id(detection_id)
        assert detection['audio_filename'] == f'American_Robin_95_x_{suffix}.mp3'
        assert detection['spectrogram_filename'] == f'American_Robin_95_x_{suffix}.webp'

    def test_resolved_zero_owner_presents_no_media(self, test_db_manager, sample_detection):
        """A resolved row that owns nothing must never fall back to a
        reconstructed name that could belong to another row."""
        detection_id = test_db_manager.insert_detection(sample_detection)
        detection = test_db_manager.get_detection_by_id(detection_id)
        assert detection['audio_filename'] is None
        assert detection['spectrogram_filename'] is None

    def test_unresolved_legacy_row_keeps_synthesized_names(self, test_db_manager):
        detection_id = insert_legacy(
            test_db_manager, '2026-01-01T10:30:00', confidence=0.95)
        detection = test_db_manager.get_detection_by_id(detection_id)
        assert detection['audio_filename'] == \
            'American_Robin_95_2026-01-01-birdnet-10-30-00.mp3'

    def test_identity_fields_never_leak_into_payloads(self, test_db_manager, sample_detection):
        detection_id, _ = self._resolved_with_media(test_db_manager, sample_detection)
        detection = test_db_manager.get_detection_by_id(detection_id)
        assert 'media_nonce' not in detection
        assert 'media_bytes' not in detection

    def test_list_path_prefetches_recorded_names(self, test_db_manager, sample_detection):
        detection_id, suffix = self._resolved_with_media(test_db_manager, sample_detection)
        detections, total = test_db_manager.get_paginated_detections(page=1, per_page=10)
        assert total == 1
        assert detections[0]['audio_filename'] == f'American_Robin_95_x_{suffix}.mp3'


class TestDeletionOrder:
    """Row deletion: unlink first, then row + ownership rows in one txn."""

    def _resolved_with_disk_files(self, manager, sample_detection, tmp_path, monkeypatch):
        audio_dir = tmp_path / 'audio'
        spec_dir = tmp_path / 'spec'
        audio_dir.mkdir()
        spec_dir.mkdir()
        # Patch the module instance core.db actually holds: reset_imports
        # evicts 'core.*' submodules but not the 'core' package itself, so
        # a re-imported core.db can bind the package's surviving (stale)
        # media_ownership attribute while a fresh 'import core.media_ownership'
        # would create a different instance.
        import core.db as live_db
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'spectrogram', str(spec_dir))

        detection_id = manager.insert_detection(sample_detection)
        with manager.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = cur.execute(
                "SELECT media_nonce FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0]
            suffix = media_ownership.media_name_suffix(detection_id, nonce)
            audio_name = f'American_Robin_95_x_{suffix}.mp3'
            spec_name = f'American_Robin_95_x_{suffix}.webp'
            record_media(cur, detection_id, [
                {'filename': audio_name, 'kind': 'audio', 'rank': 0, 'bytes': 3},
                {'filename': spec_name, 'kind': 'spectrogram', 'rank': 0, 'bytes': 3},
            ])
            conn.commit()
        (audio_dir / audio_name).write_bytes(b'aud')
        (spec_dir / spec_name).write_bytes(b'spc')
        return detection_id, audio_dir / audio_name, spec_dir / spec_name

    def test_resolved_delete_unlinks_recorded_files_and_ownership(
            self, test_db_manager, sample_detection, tmp_path, monkeypatch):
        detection_id, audio_path, spec_path = self._resolved_with_disk_files(
            test_db_manager, sample_detection, tmp_path, monkeypatch)

        deleted = test_db_manager.delete_detection(detection_id)

        assert deleted is not None
        assert sorted(deleted['files_deleted']) == sorted(
            [audio_path.name, spec_path.name])
        assert not audio_path.exists() and not spec_path.exists()
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detections WHERE id = ?",
                (detection_id,)).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media WHERE detection_id = ?",
                (detection_id,)).fetchone()[0] == 0

    def test_already_missing_file_still_cleans_ownership(
            self, test_db_manager, sample_detection, tmp_path, monkeypatch):
        """A recorded file already gone from disk reaches its goal state —
        the delete proceeds and no ownership residue remains."""
        detection_id, audio_path, _ = self._resolved_with_disk_files(
            test_db_manager, sample_detection, tmp_path, monkeypatch)
        audio_path.unlink()

        deleted = test_db_manager.delete_detection(detection_id)

        assert audio_path.name in deleted['files_deleted']
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0

    def test_resolved_empty_row_deletes_cleanly(self, test_db_manager, sample_detection):
        """A row that owns nothing (fresh insert) deletes with no file work."""
        detection_id = test_db_manager.insert_detection(sample_detection)
        deleted = test_db_manager.delete_detection(detection_id)
        assert deleted['files_deleted'] == []

    def test_rename_detection_media_follows_disk_rename(
            self, test_db_manager, sample_detection, tmp_path, monkeypatch):
        detection_id, audio_path, _ = self._resolved_with_disk_files(
            test_db_manager, sample_detection, tmp_path, monkeypatch)
        new_name = audio_path.name.replace('.mp3', '.moved.mp3')

        assert test_db_manager.rename_detection_media(audio_path.name, new_name)
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT detection_id FROM detection_media WHERE filename = ?",
                (new_name,)).fetchone()[0] == detection_id


class TestImporterStages:
    """Stage 2 (audio copy) and Stage 3 (spectrogram gen) go through the
    ownership boundary: lazy nonce init, id+nonce names, atomic publication,
    recorded ownership."""

    def test_stage2_initializes_nonce_and_records_ownership(
            self, test_db_manager, tmp_path, monkeypatch):
        from core.migration_audio import import_audio_files
        audio_dir = tmp_path / 'extracted'
        audio_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))

        detection_id = insert_legacy(test_db_manager, '2024-01-15T10:30:00')
        source = tmp_path / 'source.mp3'
        source.write_bytes(b'imported audio')

        result = import_audio_files(
            test_db_manager, [(detection_id, str(source), 14)], 'import-1')

        assert result == {'imported': 1, 'skipped': 0, 'errors': 0}
        nonce = test_db_manager.get_media_nonce(detection_id)
        assert nonce is not None
        media = test_db_manager.get_detection_media(detection_id)
        assert len(media) == 1 and media[0]['kind'] == 'audio'
        assert f'{detection_id}-{nonce}' in media[0]['filename']
        assert (audio_dir / media[0]['filename']).read_bytes() == b'imported audio'
        # Re-run: the row already owns audio -> skipped, nothing duplicated
        rerun = import_audio_files(
            test_db_manager, [(detection_id, str(source), 14)], 'import-2')
        assert rerun == {'imported': 0, 'skipped': 1, 'errors': 0}

    def test_stage2_completes_prior_crashed_publish(
            self, test_db_manager, tmp_path, monkeypatch):
        """A file already published under our id+nonce name (crash before
        record_media) is adopted, not duplicated or clobbered."""
        from core.migration_audio import import_audio_files
        from core.utils import build_detection_filenames
        audio_dir = tmp_path / 'extracted'
        audio_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))

        detection_id = insert_legacy(test_db_manager, '2024-01-15T10:30:00')
        nonce = test_db_manager.get_or_create_media_nonce(detection_id)
        base = build_detection_filenames(
            'American Robin', 0.9, '2024-01-15T10:30:00',
            audio_extension='mp3')['audio_filename']
        published_name = media_ownership.with_media_suffix(base, detection_id, nonce)
        (audio_dir / published_name).write_bytes(b'previously published')

        source = tmp_path / 'source.mp3'
        source.write_bytes(b'previously published')
        result = import_audio_files(
            test_db_manager, [(detection_id, str(source), 20)], 'import-3')

        assert result['imported'] == 1
        assert (audio_dir / published_name).read_bytes() == b'previously published'
        media = test_db_manager.get_detection_media(detection_id)
        assert [m['filename'] for m in media] == [published_name]

    def test_stage3_records_ownership_for_owned_audio(
            self, test_db_manager, tmp_path, monkeypatch):
        from core.migration_audio import generate_spectrograms_batch, import_audio_files
        audio_dir = tmp_path / 'extracted'
        spec_dir = tmp_path / 'spectrograms'
        audio_dir.mkdir()
        spec_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))
        monkeypatch.setattr('core.migration_audio.SPECTROGRAM_DIR', str(spec_dir))
        monkeypatch.setattr('core.migration_audio._convert_to_wav_if_needed',
                            lambda path: (path, False))
        monkeypatch.setattr(
            'core.migration_audio.generate_spectrogram',
            lambda wav, out, title, **kw: open(out, 'wb').write(b'webp'))

        detection_id = insert_legacy(test_db_manager, '2024-01-15T10:30:00')
        source = tmp_path / 'source.mp3'
        source.write_bytes(b'audio')
        import_audio_files(test_db_manager, [(detection_id, str(source), 5)], 'import-4')
        audio_name = test_db_manager.get_detection_media(detection_id)[0]['filename']

        result = generate_spectrograms_batch(
            [audio_name], 'gen-1', db_manager=test_db_manager)

        assert result['generated'] == 1
        media = test_db_manager.get_detection_media(detection_id)
        kinds = {m['kind'] for m in media}
        assert kinds == {'audio', 'spectrogram'}
        spec_name = next(m['filename'] for m in media if m['kind'] == 'spectrogram')
        assert (spec_dir / spec_name).exists()

    def test_stage3_legacy_audio_generates_without_ownership(
            self, test_db_manager, tmp_path, monkeypatch):
        """Audio under a legacy (unowned) name still gets its spectrogram;
        ownership waits for the frontier, which resolves both files."""
        from core.migration_audio import generate_spectrograms_batch
        audio_dir = tmp_path / 'extracted'
        spec_dir = tmp_path / 'spectrograms'
        audio_dir.mkdir()
        spec_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))
        monkeypatch.setattr('core.migration_audio.SPECTROGRAM_DIR', str(spec_dir))
        monkeypatch.setattr('core.migration_audio._convert_to_wav_if_needed',
                            lambda path: (path, False))
        monkeypatch.setattr(
            'core.migration_audio.generate_spectrogram',
            lambda wav, out, title, **kw: open(out, 'wb').write(b'webp'))

        legacy_name = 'American_Robin_90_2024-01-15-birdnet-10-30-00.mp3'
        (audio_dir / legacy_name).write_bytes(b'audio')

        result = generate_spectrograms_batch(
            [legacy_name], 'gen-2', db_manager=test_db_manager)

        assert result['generated'] == 1
        assert (spec_dir / legacy_name.replace('.mp3', '.webp')).exists()
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0


class TestRestoredHistoryIdentity:
    """Restored-backup id reuse: sqlite_sequence regresses, so a new row can
    receive an id whose files from the abandoned history still sit on disk —
    with identical semantic filename fields when the same source data is
    re-imported. Only the nonce separates the histories. (The reattachment
    refusal itself is reconciliation behavior — tested in M4; here we pin
    the M1 guarantees: distinct names, and no clobbering even under a
    forced nonce collision.)"""

    def test_reused_id_with_identical_fields_gets_distinct_name(
            self, test_db_manager, sample_detection):
        """History A's leftover file and history B's new file for the same
        id + identical species/conf/timestamp coexist under different
        names — the new publication never lands on the old file's name."""
        detection_id = test_db_manager.insert_detection(sample_detection)
        nonce_b = test_db_manager.get_media_nonce(detection_id)

        from core.utils import build_detection_filenames
        base = build_detection_filenames(
            sample_detection['common_name'], sample_detection['confidence'],
            sample_detection['timestamp'], audio_extension='mp3')['audio_filename']

        nonce_a = mint_media_nonce()  # the abandoned history's identity
        name_a = media_ownership.with_media_suffix(base, detection_id, nonce_a)
        name_b = media_ownership.with_media_suffix(base, detection_id, nonce_b)
        assert name_a != name_b
        # and B's recorded claim on its own name can't collide with A's file
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            record_media(cur, detection_id, [
                {'filename': name_b, 'kind': 'audio', 'rank': 0, 'bytes': 1}])
            conn.commit()

    def test_forced_nonce_collision_never_overwrites(self, tmp_path):
        """Even if the 2^-128 event happened (or a clone copied a data dir),
        publication surfaces a collision and preserves the existing bytes."""
        final = tmp_path / 'Robin_95_x_7-aa.mp3'
        final.write_bytes(b'history A')
        part = tmp_path / 'Robin_95_x_7-aa.mp3.part'
        part.write_bytes(b'history B')
        with pytest.raises(MediaCollisionError):
            publish_media_file(str(part), str(final))
        assert final.read_bytes() == b'history A'


class TestConcurrentNonceInitializers:

    def test_two_threads_converge_on_one_nonce(self, test_db_manager):
        """Concurrent lazy initializers (Stage 2 vs Stage 3 racing on a
        legacy row) must converge on the stored winner."""
        import threading

        detection_id = insert_legacy(test_db_manager, '2026-01-01T00:00:00')

        results = {}
        barrier = threading.Barrier(2)

        def init(slot):
            barrier.wait()
            results[slot] = test_db_manager.get_or_create_media_nonce(detection_id)

        threads = [threading.Thread(target=init, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results[0] == results[1]
        assert NONCE_RE.match(results[0])
        assert test_db_manager.get_media_nonce(detection_id) == results[0]
