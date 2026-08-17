"""Tests for the resolution frontier (core.media_frontier).

Covers the cursor invariant (atomic batch + resume), multi-era resolution
(dash, legacy colon normalization, source-suffix duplicates with per-kind
ranks), first-owner-wins collisions, dirty-day enqueueing, the computed
completeness check, and the weekly corrective rewind for rows an older
release writes behind a caught-up frontier.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 2).
"""

import pytest

from tests.database.conftest import (
    insert_legacy,
    media_rows,
    stamped_bytes,
)


@pytest.fixture
def frontier_env(test_db_manager, tmp_path, monkeypatch):
    """(frontier module, db, audio_dir, spec_dir) with media dirs patched on
    the live module chain (KIND_DIRS is shared by object identity)."""
    import core.media_frontier as mf
    audio_dir = tmp_path / 'audio'
    spec_dir = tmp_path / 'spec'
    audio_dir.mkdir()
    spec_dir.mkdir()
    monkeypatch.setitem(mf.KIND_DIRS, 'audio', str(audio_dir))
    monkeypatch.setitem(mf.KIND_DIRS, 'spectrogram', str(spec_dir))
    return mf, test_db_manager, audio_dir, spec_dir


class TestAdvanceFrontier:

    def test_resolves_dash_and_colon_era_files(self, frontier_env):
        mf, db, audio_dir, spec_dir = frontier_env
        # Row A: current dash-pattern files on disk
        id_a = insert_legacy(db, '2024-01-15T10:30:00')
        (audio_dir / 'American_Robin_90_2024-01-15-birdnet-10-30-00.mp3').write_bytes(b'aaaa')
        (spec_dir / 'American_Robin_90_2024-01-15-birdnet-10-30-00.webp').write_bytes(b'ss')
        # Row B: legacy colon-pattern audio, normalized during resolution
        id_b = insert_legacy(db, '2024-01-16T11:00:00')
        (audio_dir / 'American_Robin_90_2024-01-16-birdnet-11:00:00.mp3').write_bytes(b'bbb')
        # Row C: no files left (aged out)
        id_c = insert_legacy(db, '2024-01-17T09:00:00')

        result = mf.advance_frontier(db)

        assert result['rows_resolved'] == 3
        assert stamped_bytes(db, id_a) == 6
        assert [m['kind'] for m in media_rows(db, id_a)] == ['audio', 'spectrogram']
        # colon file renamed on disk and recorded under the dash name
        assert stamped_bytes(db, id_b) == 3
        assert (audio_dir / 'American_Robin_90_2024-01-16-birdnet-11-00-00.mp3').exists()
        assert not (audio_dir / 'American_Robin_90_2024-01-16-birdnet-11:00:00.mp3').exists()
        assert stamped_bytes(db, id_c) == 0
        assert media_rows(db, id_c) == []

    def test_duplicate_era_copies_get_per_kind_ranks(self, frontier_env):
        """A transition-era row (audio_source id, no saved label) can own a
        suffixed AND an unsuffixed copy; the first found is canonical."""
        mf, db, audio_dir, _ = frontier_env
        detection_id = insert_legacy(
            db, '2024-02-01T08:00:00', audio_source='source_0')
        (audio_dir / 'American_Robin_90_2024-02-01-birdnet-08-00-00_source_0.mp3').write_bytes(b'11')
        (audio_dir / 'American_Robin_90_2024-02-01-birdnet-08-00-00.mp3').write_bytes(b'2')

        mf.advance_frontier(db)

        rows = media_rows(db, detection_id)
        assert [(r['rank'], r['filename'].endswith('_source_0.mp3')) for r in rows] == [
            (0, True), (1, False)]
        assert stamped_bytes(db, detection_id) == 3

    def test_collision_first_owner_wins(self, frontier_env):
        """Two rows with identical lossy fields resolve to the same file;
        the first resolver owns it, the later claimant owns nothing."""
        mf, db, audio_dir, _ = frontier_env
        first = insert_legacy(db, '2024-03-01T07:00:00')
        second = insert_legacy(db, '2024-03-01T07:00:00')  # imported duplicate
        (audio_dir / 'American_Robin_90_2024-03-01-birdnet-07-00-00.mp3').write_bytes(b'x')

        mf.advance_frontier(db)

        assert stamped_bytes(db, first) == 1
        assert stamped_bytes(db, second) == 0
        assert media_rows(db, second) == []

    def test_resume_after_kill_mid_walk(self, frontier_env):
        mf, db, audio_dir, _ = frontier_env
        ids = [insert_legacy(db, f'2024-04-0{d}T06:00:00') for d in range(1, 6)]
        for d in range(1, 6):
            (audio_dir / f'American_Robin_90_2024-04-0{d}-birdnet-06-00-00.mp3').write_bytes(b'z')

        first = mf.advance_frontier(db, batch_rows=2)
        assert first['rows_resolved'] == 2 and not first['complete']
        # "kill": simply a new call — the cursor was committed with the batch
        while not mf.advance_frontier(db, batch_rows=2)['complete']:
            pass

        assert all(stamped_bytes(db, i) == 1 for i in ids)
        assert mf.frontier_complete(db)

    def test_stamped_rows_skim_without_work(self, frontier_env, sample_detection):
        mf, db, _, _ = frontier_env
        db.insert_detection(sample_detection)  # resolved-empty at insert
        result = mf.advance_frontier(db)
        assert result['rows_seen'] == 1
        assert result['rows_resolved'] == 0

    def test_resolved_rows_enqueue_dirty_days(self, frontier_env):
        mf, db, _, _ = frontier_env
        insert_legacy(db, '2024-05-01T05:00:00')
        insert_legacy(db, '2024-05-01T09:00:00')
        insert_legacy(db, '2024-05-02T05:00:00')

        mf.advance_frontier(db)

        with db.get_db_connection() as conn:
            days = {r[0] for r in conn.execute(
                "SELECT date FROM rollup_dirty_day").fetchall()}
        assert days == {'2024-05-01', '2024-05-02'}

    def test_empty_table_is_complete(self, frontier_env):
        mf, db, _, _ = frontier_env
        assert mf.advance_frontier(db)['complete']
        assert mf.frontier_complete(db)


class TestResolutionLatch:

    def test_latch_survives_new_detections(self, frontier_env,
                                           sample_detection):
        """THE production bug pin: once backfill completes, a new
        (born-resolved) detection moves the live edge past the cursor —
        frontier_complete flips False until the next idle slice, but
        resolution_complete must stay True or the recordings exact branch
        turns off on every active station."""
        mf, db, _, _ = frontier_env
        insert_legacy(db, '2024-01-10T08:00:00')
        while not mf.advance_frontier(db)['complete']:
            pass
        assert mf.resolution_complete(db)

        db.insert_detection(sample_detection)  # edge moves, row resolved
        assert not mf.frontier_complete(db)
        assert mf.resolution_complete(db)

    def test_rewind_clears_and_readvance_restores(self, frontier_env):
        """Downgrade-era NULL rows behind the cursor: the weekly rewind
        clears the latch (exact consumers fall back) and the ordinary walk
        re-closes the gap and restores it."""
        mf, db, _, _ = frontier_env
        insert_legacy(db, '2024-02-10T08:00:00')
        while not mf.advance_frontier(db)['complete']:
            pass
        assert mf.resolution_complete(db)

        insert_legacy(db, '2024-01-05T07:00:00')  # behind the cursor
        assert mf.corrective_rewind(db)
        assert not mf.resolution_complete(db)

        while not mf.advance_frontier(db)['complete']:
            pass
        assert mf.resolution_complete(db)


class TestCursorRollbackCompat:

    def test_persisted_cursor_stays_three_element(self, frontier_env):
        """The stored form must remain [timestamp, None, id]: earlier
        builds unpack exactly three elements on read, so a two-element
        cursor would crash the parent build after a rollback."""
        mf, db, audio_dir, _ = frontier_env
        insert_legacy(db, '2024-01-15T10:30:00')
        insert_legacy(db, '2024-01-16T11:00:00')
        mf.advance_frontier(db, batch_rows=1)

        import json
        with db.get_db_connection() as conn:
            raw = conn.execute("SELECT value FROM meta WHERE key = ?",
                               ('media_frontier_cursor',)).fetchone()[0]
        ts, middle, rowid = json.loads(raw)  # old-reader unpack shape
        assert middle is None
        assert ts == '2024-01-15T10:30:00'


class TestCorrectiveRewind:

    def test_downgraded_importer_hole_rewinds_and_recloses(self, frontier_env):
        """Historical NULL rows behind a caught-up frontier (an old
        release's importer) are invisible to the monotone walk AND to
        frontier_complete — the weekly rewind is what re-opens the gap."""
        mf, db, audio_dir, _ = frontier_env
        insert_legacy(db, '2024-06-10T10:00:00')
        while not mf.advance_frontier(db)['complete']:
            pass
        assert mf.frontier_complete(db)

        # Downgrade: old importer inserts a historical row, no stamping
        hole = insert_legacy(db, '2024-01-01T00:00:00')
        (audio_dir / 'American_Robin_90_2024-01-01-birdnet-00-00-00.mp3').write_bytes(b'h')
        assert mf.frontier_complete(db)  # the blind spot, by design

        assert mf.corrective_rewind(db) is True
        while not mf.advance_frontier(db)['complete']:
            pass
        assert stamped_bytes(db, hole) == 1
        assert mf.corrective_rewind(db) is False  # nothing left to heal

    def test_rewind_revisits_all_rows_at_equal_timestamp(self, frontier_env):
        """The rewind lands BEFORE every row sharing the minimum NULL
        timestamp (complete-key semantics), not after the first of them."""
        mf, db, audio_dir, _ = frontier_env
        insert_legacy(db, '2024-07-01T12:00:00')
        while not mf.advance_frontier(db)['complete']:
            pass

        ts = '2024-03-03T03:00:00'
        first = insert_legacy(db, ts, common='Blue Jay',
                              scientific='Cyanocitta cristata')
        second = insert_legacy(db, ts)
        (audio_dir / 'Blue_Jay_90_2024-03-03-birdnet-03-00-00.mp3').write_bytes(b'j')
        (audio_dir / 'American_Robin_90_2024-03-03-birdnet-03-00-00.mp3').write_bytes(b'r')

        assert mf.corrective_rewind(db)
        while not mf.advance_frontier(db)['complete']:
            pass
        assert stamped_bytes(db, first) == 1
        assert stamped_bytes(db, second) == 1

    def test_no_rewind_before_walk_starts(self, frontier_env):
        mf, db, _, _ = frontier_env
        insert_legacy(db, '2024-08-01T08:00:00')
        assert mf.corrective_rewind(db) is False  # no cursor yet


class TestIdleBackfillSlice:

    def test_slice_completes_small_backlog_and_reports_done(self, frontier_env):
        import threading
        mf, db, audio_dir, _ = frontier_env
        insert_legacy(db, '2024-09-01T08:00:00')
        stop = threading.Event()
        assert mf.idle_backfill_slice(db, stop, max_wall_seconds=30) is True
        assert mf.frontier_complete(db)

    def test_slice_respects_stop_flag(self, frontier_env):
        import threading
        mf, db, _, _ = frontier_env
        insert_legacy(db, '2024-09-02T08:00:00')
        stop = threading.Event()
        stop.set()
        assert mf.idle_backfill_slice(db, stop, max_wall_seconds=30) is False
