"""Tests for media reconciliation (core.media_reconciliation).

Covers both sweep directions: disk-direction orphan repair (exact-nonce
reattach, refusal + removal of cross-history residue — the reattachment
half of the restored-backup test deferred from M1 — .part GC, legacy files
left to the frontier) and DB-direction audits (vanished files, deleted
owners, size restat, denormalized-sum repair).

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 1).
"""
import os
import time

import pytest

from tests.database.conftest import media_count, stamped_bytes


@pytest.fixture
def recon_env(test_db_manager, tmp_path, monkeypatch):
    """(module, db, audio_dir, spec_dir) with dirs patched on the live
    ownership module the reconciliation chain reads KIND_DIRS from."""
    import core.media_ownership as mo
    import core.media_reconciliation as mr
    audio_dir = tmp_path / 'audio'
    spec_dir = tmp_path / 'spec'
    audio_dir.mkdir()
    spec_dir.mkdir()
    monkeypatch.setitem(mo.KIND_DIRS, 'audio', str(audio_dir))
    monkeypatch.setitem(mo.KIND_DIRS, 'spectrogram', str(spec_dir))
    return mr, test_db_manager, audio_dir, spec_dir


def resolved_row(db, sample_detection):
    detection_id = db.insert_detection(sample_detection)
    return detection_id, db.get_media_nonce(detection_id)


def age_file(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


class TestDiskScan:

    def test_exact_nonce_match_reattaches_orphan(self, recon_env, sample_detection):
        """Crash between publish and record_media: the complete file under
        its id+nonce name is reattached — identity proven by the persisted
        nonce, not the reusable id."""
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        # the canonical-field sanity check requires a genuinely derived name
        from core.media_ownership import with_media_suffix
        from core.utils import build_detection_filenames
        base = build_detection_filenames(
            sample_detection['common_name'], sample_detection['confidence'],
            sample_detection['timestamp'], audio_extension='mp3')['audio_filename']
        orphan = audio_dir / with_media_suffix(base, detection_id, nonce)
        orphan.write_bytes(b'complete audio')

        stats = mr.scan_disk(db)

        assert stats['reattached'] == 1
        assert stamped_bytes(db, detection_id) == len(b'complete audio')
        detection = db.get_detection_by_id(detection_id)
        assert detection['audio_filename'] == orphan.name

    def test_restored_history_id_reuse_is_refused_and_removed(
            self, recon_env, sample_detection):
        """The M1-deferred restore test: a leftover file from an abandoned
        DB history parses to a reused id with IDENTICAL semantic fields —
        only the nonce mismatch separates the histories. It must never be
        attached, and after the grace period it is removed as residue."""
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        from core.media_ownership import mint_media_nonce
        old_history_nonce = mint_media_nonce()
        assert old_history_nonce != nonce
        residue = audio_dir / f'American_Robin_95_x_{detection_id}-{old_history_nonce}.mp3'
        residue.write_bytes(b'other history')
        age_file(residue, mr.ORPHAN_GRACE_SECONDS + 60)

        stats = mr.scan_disk(db)

        assert stats['reattached'] == 0
        assert stats['residue_removed'] == 1
        assert not residue.exists()
        assert media_count(db) == 0
        assert stamped_bytes(db, detection_id) == 0

    def test_young_orphan_waits_out_the_grace_period(self, recon_env, sample_detection):
        """A mismatched file inside the grace window may still be
        mid-creation elsewhere — counted, not touched."""
        mr, db, audio_dir, _ = recon_env
        detection_id, _ = resolved_row(db, sample_detection)
        from core.media_ownership import mint_media_nonce
        young = audio_dir / f'x_{detection_id}-{mint_media_nonce()}.mp3'
        young.write_bytes(b'y')

        stats = mr.scan_disk(db)

        assert stats['pending_grace'] == 1
        assert young.exists()

    def test_missing_row_residue_removed_after_grace(self, recon_env):
        mr, db, audio_dir, _ = recon_env
        from core.media_ownership import mint_media_nonce
        residue = audio_dir / f'gone_424242-{mint_media_nonce()}.mp3'
        residue.write_bytes(b'r')
        age_file(residue, mr.ORPHAN_GRACE_SECONDS + 60)

        stats = mr.scan_disk(db)

        assert stats['residue_removed'] == 1
        assert not residue.exists()

    def test_stale_part_files_are_garbage_collected(self, recon_env):
        mr, db, audio_dir, _ = recon_env
        stale = audio_dir / 'clip.mp3.part'
        stale.write_bytes(b'partial')
        age_file(stale, mr.PART_GRACE_SECONDS + 60)
        fresh = audio_dir / 'writing.mp3.part'
        fresh.write_bytes(b'in-progress')

        stats = mr.scan_disk(db)

        assert stats['parts_removed'] == 1
        assert not stale.exists() and fresh.exists()

    def test_legacy_files_are_left_to_the_frontier(self, recon_env):
        """Unowned legacy-pattern files are never auto-deleted here — the
        frontier owns their resolution; the sweep only counts them."""
        mr, db, audio_dir, _ = recon_env
        legacy = audio_dir / 'American_Robin_90_2024-01-01-birdnet-10-30-00.mp3'
        legacy.write_bytes(b'legacy')
        age_file(legacy, mr.ORPHAN_GRACE_SECONDS * 10)

        stats = mr.scan_disk(db)

        assert stats['legacy_unowned'] == 1
        assert legacy.exists()


class TestOwnershipAudit:

    def _record(self, db, detection_id, name, size, kind='audio'):
        import core.media_ownership as mo
        with db.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, detection_id, [
                {'filename': name, 'kind': kind, 'rank': 0, 'bytes': size}])
            conn.commit()

    def test_vanished_file_loses_its_row(self, recon_env, sample_detection):
        mr, db, _, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        self._record(db, detection_id, f'v_{detection_id}-{nonce}.mp3', 100)

        stats = mr.audit_ownership(db)

        assert stats['vanished_rows_removed'] == 1
        assert media_count(db) == 0
        assert stamped_bytes(db, detection_id) == 0

    def test_deleted_owner_row_finishes_the_delete(self, recon_env, sample_detection):
        """Old-code deletion (no FK) leaves media rows behind: the audit
        unlinks the file and drops the row."""
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        name = f'd_{detection_id}-{nonce}.mp3'
        self._record(db, detection_id, name, 4)
        (audio_dir / name).write_bytes(b'data')
        with db.get_db_connection() as conn:
            # old code: DELETE the row only, no ownership cleanup
            conn.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
            conn.commit()

        stats = mr.audit_ownership(db)

        assert stats['deleted_owner_files'] == 1
        assert not (audio_dir / name).exists()
        assert media_count(db) == 0

    def test_size_drift_is_restat(self, recon_env, sample_detection):
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        name = f's_{detection_id}-{nonce}.mp3'
        self._record(db, detection_id, name, 999)
        (audio_dir / name).write_bytes(b'four')

        stats = mr.audit_ownership(db)

        assert stats['sizes_updated'] == 1
        assert stamped_bytes(db, detection_id) == 4

    def test_denormalized_sum_drift_is_rederived(self, recon_env, sample_detection):
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        name = f'n_{detection_id}-{nonce}.mp3'
        self._record(db, detection_id, name, 7)
        (audio_dir / name).write_bytes(b'0' * 7)
        with db.get_db_connection() as conn:
            conn.execute("UPDATE detections SET media_bytes = 12345 WHERE id = ?",
                         (detection_id,))
            conn.commit()

        stats = mr.audit_ownership(db)

        assert stats['sums_fixed'] == 1
        assert stamped_bytes(db, detection_id) == 7

    def test_clean_state_is_a_no_op(self, recon_env, sample_detection):
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        name = f'c_{detection_id}-{nonce}.mp3'
        self._record(db, detection_id, name, 2)
        (audio_dir / name).write_bytes(b'ok')

        stats = mr.run_reconciliation(db)

        assert all(v == 0 for v in stats.values())
        assert media_count(db) == 1


    def test_nonce_match_with_mismatched_fields_is_not_attached(
            self, recon_env, sample_detection):
        """A nonce match whose filename the row's own fields would never
        generate is reported, never attached (implementation review:
        canonical-field sanity assertion behind the nonce)."""
        mr, db, audio_dir, _ = recon_env
        detection_id, nonce = resolved_row(db, sample_detection)
        odd = audio_dir / f'Wrong_Species_10_x_{detection_id}-{nonce}.mp3'
        odd.write_bytes(b'odd')

        stats = mr.scan_disk(db)

        assert stats['reattached'] == 0
        assert stats['unrecognized'] == 1
        assert odd.exists()
