"""Tests for the time-axis rollups (core.db_rollups) and the summary
conversion they power.

The parity oracle throughout is audit_rollups: it compares complete raw
buckets (hour and species tuples, both directions) against the rollup
tables, so "audit finds nothing" IS the incremental-matches-rebuild
property. Convergence of the always-on hooks with the day-bucket builder,
bypass-writer dirty days, readiness/revision semantics, and the
rollup-vs-raw summary equality are all pinned here.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 3).
"""
from datetime import datetime

import core.db_rollups as db_rollups


def detection(timestamp, common='American Robin',
              scientific='Turdus migratorius', confidence=0.9):
    return {
        'timestamp': timestamp,
        'group_timestamp': timestamp,
        'scientific_name': scientific,
        'common_name': common,
        'confidence': confidence,
        'latitude': None, 'longitude': None,
        'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
    }


def old_code_insert(db, timestamp, common='Old Bird', scientific='Oldus birdus'):
    """A row as a downgraded release writes it: no rollup hooks, no dirty day."""
    with db.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO detections (timestamp, group_timestamp, "
            "scientific_name, common_name, confidence) VALUES (?, ?, ?, ?, 0.9)",
            (timestamp, timestamp, scientific, common))
        conn.commit()
        return cur.lastrowid


def build_all(db):
    while not db_rollups.advance_build(db, max_days=2):
        pass


def audit_clean(db):
    return db_rollups.audit_rollups(db) == set()


def ready(db):
    with db.get_db_connection() as conn:
        return db_rollups.rollups_ready(conn.cursor())


class TestHookParity:

    def test_insert_hooks_match_rebuild(self, test_db_manager):
        for hour in (0, 8, 8, 23):
            test_db_manager.insert_detection(
                detection(f'2024-01-15T{hour:02d}:30:00'))
        test_db_manager.insert_detection(
            detection('2024-01-16T08:30:00', common='Blue Jay',
                      scientific='Cyanocitta cristata', confidence=0.7))
        build_all(test_db_manager)  # builder replaces — convergence check
        assert audit_clean(test_db_manager)

    def test_delete_hooks_match_rebuild(self, test_db_manager):
        ids = [test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00', confidence=0.5 + i / 10))
            for i in range(4)]
        build_all(test_db_manager)
        # delete the max-confidence row (boundary field) and a middle one
        test_db_manager.delete_detection(ids[-1])
        test_db_manager.delete_detection(ids[1])
        assert audit_clean(test_db_manager)

    def test_deleting_the_last_row_of_a_bucket_empties_it(self, test_db_manager):
        detection_id = test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00'))
        test_db_manager.delete_detection(detection_id)
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM species_day").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM hour_day").fetchone()[0] == 0


class TestConvergentBuild:

    def test_mutations_on_both_sides_of_the_cursor_converge(self, test_db_manager):
        """Inserts and deletes landing before AND after the build cursor,
        plus a historical bypass insert, all converge — no snapshot/delta
        coordination, just bucket replacement + always-on hooks."""
        for day in (10, 11, 12, 13):
            test_db_manager.insert_detection(detection(f'2024-01-{day}T06:00:00'))
        assert not db_rollups.advance_build(test_db_manager, max_days=2)  # cursor mid-table

        # behind the cursor: hooked insert + delete
        behind_id = test_db_manager.insert_detection(detection('2024-01-10T07:00:00'))
        test_db_manager.delete_detection(behind_id)
        # ahead of the cursor: hooked insert
        test_db_manager.insert_detection(detection('2024-01-13T09:00:00'))
        # historical bypass write (old importer style) + its dirty day
        old_code_insert(test_db_manager, '2024-01-11T03:00:00')
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-11'])
            conn.commit()

        build_all(test_db_manager)
        while db_rollups.consume_dirty_days(test_db_manager):
            pass
        assert audit_clean(test_db_manager)
        assert ready(test_db_manager)

    def test_crash_resume_is_idempotent(self, test_db_manager):
        for day in range(10, 16):
            test_db_manager.insert_detection(detection(f'2024-01-{day}T06:00:00'))
        db_rollups.advance_build(test_db_manager, max_days=2)
        # "crash": a fresh call just resumes from the persisted cursor;
        # re-running a completed day (recompute) is idempotent by nature
        build_all(test_db_manager)
        build_all(test_db_manager)
        assert audit_clean(test_db_manager)


class TestBypassWriters:

    def test_importer_batches_record_dirty_days_durably(self, test_db_manager):
        from core.migration import BirdNETPiMigrator
        migrator = BirdNETPiMigrator(test_db_manager)
        records = [detection('2023-06-01T05:00:00'),
                   detection('2023-06-02T06:00:00')]
        for r in records:
            r['extra'] = '{}'
        imported, errors = migrator._insert_batch(records)
        assert (imported, errors) == (2, 0)
        with test_db_manager.get_db_connection() as conn:
            days = {r[0] for r in conn.execute(
                "SELECT date FROM rollup_dirty_day").fetchall()}
        # durable in the SAME transaction as the rows — a crash before any
        # completion hook cannot lose them
        assert {'2023-06-01', '2023-06-02'} <= days

    def test_consume_dirty_days_repairs_and_drains(self, test_db_manager):
        old_code_insert(test_db_manager, '2023-06-01T05:00:00')
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2023-06-01'])
            conn.commit()
        build_all(test_db_manager)
        assert not ready(test_db_manager)  # dirty day pending
        assert db_rollups.consume_dirty_days(test_db_manager) == 1
        assert ready(test_db_manager)
        assert audit_clean(test_db_manager)


class TestReadinessAndRevision:

    def test_not_ready_before_build(self, test_db_manager):
        test_db_manager.insert_detection(detection('2024-01-15T08:30:00'))
        assert not ready(test_db_manager)

    def test_revision_bumps_on_every_transition(self, test_db_manager):
        revisions = [test_db_manager.get_rollup_revision()]
        test_db_manager.insert_detection(detection('2024-01-15T08:30:00'))
        build_all(test_db_manager)
        revisions.append(test_db_manager.get_rollup_revision())
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-15'])
            conn.commit()
        revisions.append(test_db_manager.get_rollup_revision())
        db_rollups.consume_dirty_days(test_db_manager)
        revisions.append(test_db_manager.get_rollup_revision())
        assert revisions == sorted(set(revisions))  # strictly increasing


class TestDowngradeAudit:

    def test_count_preserving_cross_day_pair_is_detected(self, test_db_manager):
        """An old-code insert on day B plus an old-code delete on day A
        preserves the global count while corrupting both days — exactly
        what a count-only backstop cannot see."""
        keep_id = test_db_manager.insert_detection(detection('2024-01-10T08:00:00'))
        test_db_manager.insert_detection(detection('2024-01-11T08:00:00'))
        build_all(test_db_manager)
        assert audit_clean(test_db_manager)

        with test_db_manager.get_db_connection() as conn:
            conn.execute("DELETE FROM detections WHERE id = ?", (keep_id,))
            conn.commit()
        old_code_insert(test_db_manager, '2024-01-11T09:00:00')

        dirty = db_rollups.audit_rollups(test_db_manager)
        assert dirty == {'2024-01-10', '2024-01-11'}
        while db_rollups.consume_dirty_days(test_db_manager):
            pass
        assert audit_clean(test_db_manager)

    def test_same_day_hour_move_is_detected(self, test_db_manager):
        detection_id = test_db_manager.insert_detection(
            detection('2024-01-10T08:00:00'))
        build_all(test_db_manager)
        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "UPDATE detections SET timestamp = '2024-01-10T09:00:00' "
                "WHERE id = ?", (detection_id,))
            conn.commit()
        assert db_rollups.audit_rollups(test_db_manager) == {'2024-01-10'}

    def test_same_count_boundary_change_is_detected(self, test_db_manager):
        detection_id = test_db_manager.insert_detection(
            detection('2024-01-10T08:00:00', confidence=0.9))
        build_all(test_db_manager)
        with test_db_manager.get_db_connection() as conn:
            conn.execute("UPDATE detections SET confidence = 0.4 WHERE id = ?",
                         (detection_id,))
            conn.commit()
        assert db_rollups.audit_rollups(test_db_manager) == {'2024-01-10'}


class TestSummaryConversion:

    def _seed(self, db):
        # midnight detection pins the '00' hour formatting parity
        db.insert_detection(detection('2024-01-15T00:10:00'))
        for _ in range(3):
            db.insert_detection(detection('2024-01-15T08:30:00'))
        db.insert_detection(detection('2024-01-16T08:45:00', common='Blue Jay',
                                      scientific='Cyanocitta cristata',
                                      confidence=0.7))

    def test_rollup_summary_equals_raw_summary(self, test_db_manager, frozen_db_now):
        """The killer parity check: the same period computed off rollups
        (ready) and off the raw CTEs (forced fallback) must be identical."""
        self._seed(test_db_manager)
        build_all(test_db_manager)
        assert ready(test_db_manager)

        period_start = datetime(2024, 1, 1)
        from_rollups = test_db_manager.get_summary_stats_for_period(period_start)

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-15'])
            conn.commit()
        from_raw = test_db_manager.get_summary_stats_for_period(period_start)

        assert from_rollups == from_raw
        assert from_rollups['totalObservations'] == 5
        assert from_rollups['uniqueSpecies'] == 2
        assert from_rollups['mostActiveHour'] == '08:00'
        assert from_rollups['mostCommonSpecies'] == 'American Robin'
        assert from_rollups['rarestSpecies'] == 'Blue Jay'

    def test_all_periods_rollup_equals_raw(self, test_db_manager, frozen_db_now):
        self._seed(test_db_manager)
        build_all(test_db_manager)

        starts = (datetime(2026, 5, 20), datetime(2026, 5, 14), datetime(2026, 4, 20))
        from_rollups = test_db_manager.get_summary_stats_all_periods(*starts)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-15'])
            conn.commit()
        from_raw = test_db_manager.get_summary_stats_all_periods(*starts)
        assert from_rollups == from_raw
        assert from_rollups['allTime']['totalObservations'] == 5

    def test_midnight_hour_is_not_collapsed_to_na(self, test_db_manager, frozen_db_now):
        test_db_manager.insert_detection(detection('2024-01-15T00:10:00'))
        build_all(test_db_manager)
        summary = test_db_manager.get_summary_stats_for_period(datetime(2024, 1, 1))
        assert summary['mostActiveHour'] == '00:00'


class TestTrendsConversion:

    def test_trends_rollup_equals_raw(self, test_db_manager):
        """Daily counts from hour_day (ready) and from the sargable raw
        fallback (not ready) must be identical, zeros included."""
        for day, n in (('2024-01-10', 2), ('2024-01-12', 1)):
            for i in range(n):
                test_db_manager.insert_detection(
                    detection(f'{day}T0{i + 1}:00:00'))
        build_all(test_db_manager)

        from_rollups = test_db_manager.get_daily_detection_counts(
            '2024-01-09', '2024-01-13')
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-10'])
            conn.commit()
        from_raw = test_db_manager.get_daily_detection_counts(
            '2024-01-09', '2024-01-13')

        assert from_rollups == from_raw
        assert from_rollups['labels'] == [
            '2024-01-09', '2024-01-10', '2024-01-11', '2024-01-12', '2024-01-13']
        assert from_rollups['data'] == [0, 2, 0, 1, 0]


class TestExpressionIndexRetirement:
    """Migration 5's EXPLAIN verification: the retired date(timestamp)
    expression indexes are gone, and no kept-raw query plan wants them."""

    def test_unused_expression_index_is_dropped_and_prefix_one_kept(
            self, test_db_manager):
        """EXPLAIN verification's verdict: timestamp_date had no consumers
        left; species_date SURVIVES because its common_name prefix serves
        legacy name lookups (migration 3 depends on it)."""
        with test_db_manager.get_db_connection() as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'idx_detections_timestamp_date' not in names
        assert 'idx_detections_species_date' in names

    def test_migration_5_drops_them_on_existing_databases(self, tmp_path):
        import sqlite3

        from core.db import DatabaseManager
        db_path = str(tmp_path / 'v4.db')
        with sqlite3.connect(db_path) as conn:
            conn.executescript("""
CREATE TABLE detections (id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp DATETIME NOT NULL, group_timestamp DATETIME NOT NULL,
  scientific_name VARCHAR(100) NOT NULL, common_name VARCHAR(100) NOT NULL,
  confidence DECIMAL(5,4) NOT NULL, latitude DECIMAL(10,8),
  longitude DECIMAL(11,8), cutoff DECIMAL(4,3), sensitivity DECIMAL(4,3),
  overlap DECIMAL(4,3), extra TEXT DEFAULT '{}', audio_source TEXT,
  media_bytes INTEGER, media_nonce TEXT);
CREATE INDEX idx_detections_timestamp_date ON detections(date(timestamp));
CREATE INDEX idx_detections_species_date ON detections(common_name, date(timestamp));
PRAGMA user_version = 4;
""")
        DatabaseManager(db_path=db_path)
        with sqlite3.connect(db_path) as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'idx_detections_timestamp_date' not in names
        assert 'idx_detections_species_date' in names

    def test_kept_raw_queries_use_surviving_indexes(self, test_db_manager):
        """The kept-raw access paths run off the surviving indexes — the
        retired expressions appear in no plan (they no longer exist, and
        nothing scans the table for these shapes)."""
        test_db_manager.insert_detection(detection('2024-01-15T08:30:00'))
        with test_db_manager.get_db_connection() as conn:
            # per-species distribution range (kept raw)
            plan = ' '.join(r[3] for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM detections "
                "WHERE scientific_name IN (?) AND timestamp BETWEEN ? AND ?",
                ('Turdus migratorius', '2024-01-01T00:00:00',
                 '2024-12-31T23:59:59')))
            assert 'idx_detections_scientific_timestamp' in plan
            # single-day activity overview window (kept raw)
            plan = ' '.join(r[3] for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM detections "
                "WHERE timestamp >= ? AND timestamp < ?",
                ('2024-01-15T00:00:00', '2024-01-16T00:00:00')))
            assert 'idx_detections_timestamp' in plan
            # trends raw fallback (sargable, plain timestamp index)
            plan = ' '.join(r[3] for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT substr(timestamp, 1, 10), COUNT(*) "
                "FROM detections WHERE timestamp >= ? "
                "AND timestamp < datetime(?, '+1 day') GROUP BY 1",
                ('2024-01-01T00:00:00', '2024-01-31T00:00:00')))
            assert 'idx_detections_timestamp' in plan


class TestImplementationReviewFixes:
    """Regression pins for the 2026-08-15 implementation review findings."""

    def test_rolling_window_keeps_exact_time_boundary(self, test_db_manager):
        """Finding 1: a week window starting mid-day must exclude the
        boundary day's earlier detections even when rollups are ready."""
        test_db_manager.insert_detection(detection('2026-08-08T10:00:00'))  # before cutoff
        test_db_manager.insert_detection(detection('2026-08-08T16:00:00'))  # after cutoff
        build_all(test_db_manager)
        assert ready(test_db_manager)

        week_start = datetime(2026, 8, 8, 15, 0, 0)
        result = test_db_manager.get_summary_stats_for_period(week_start)
        assert result['totalObservations'] == 1  # raw semantics, not 2

    def test_all_periods_rolling_windows_stay_exact_when_ready(
            self, test_db_manager, frozen_db_now):
        """Finding 1 (all-periods): the ready branch serves week/month via
        exact raw bounds while allTime rides the rollups."""
        # frozen now = 2026-05-20T12:00: week window starts 05-13T12:00
        test_db_manager.insert_detection(detection('2026-05-13T09:00:00'))  # outside week
        test_db_manager.insert_detection(detection('2026-05-13T13:00:00'))  # inside week
        build_all(test_db_manager)

        starts = (datetime(2026, 5, 20), datetime(2026, 5, 13, 12, 0, 0),
                  datetime(2026, 4, 20, 12, 0, 0))
        result = test_db_manager.get_summary_stats_all_periods(*starts)
        assert result['week']['totalObservations'] == 1
        assert result['allTime']['totalObservations'] == 2

    def test_future_dated_rows_stay_out_of_rollup_alltime(
            self, test_db_manager, frozen_db_now):
        """Finding 1: the rollup path's upper bound keeps future-dated rows
        out, matching the raw path's `.. AND now`."""
        test_db_manager.insert_detection(detection('2026-05-19T08:00:00'))
        test_db_manager.insert_detection(detection('2030-01-01T08:00:00'))  # pathological
        build_all(test_db_manager)
        result = test_db_manager.get_summary_stats_for_period(datetime.min)
        assert result['totalObservations'] == 1

    def test_null_resolution_via_record_media_enqueues_dirty_day(
            self, test_db_manager):
        """Finding 3: Stage 2 resolving an old-code NULL row must hand the
        date to the rollup queue like a frontier resolution would."""
        row_id = old_code_insert(test_db_manager, '2023-03-03T03:00:00')
        build_all(test_db_manager)
        while db_rollups.consume_dirty_days(test_db_manager):
            pass
        # rollups now falsely believe they're ready if nothing enqueues
        import core.media_ownership as mo
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, row_id, [
                {'filename': f'null_{row_id}-x.mp3', 'kind': 'audio',
                 'rank': 0, 'bytes': 5}])
            conn.commit()
        assert not ready(test_db_manager)  # dirty day pending
        while db_rollups.consume_dirty_days(test_db_manager):
            pass
        assert audit_clean(test_db_manager)

    def test_repeat_enqueue_of_dirty_date_still_bumps_revision(
            self, test_db_manager):
        """Finding 4: a second importer batch for an already-dirty date
        changed raw data — the revision must move regardless."""
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-01'])
            conn.commit()
        first = test_db_manager.get_rollup_revision()
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            db_rollups.enqueue_dirty_days(cur, ['2024-01-01'])  # already dirty
            conn.commit()
        assert test_db_manager.get_rollup_revision() > first

    def test_canonical_replacement_demotes_not_errors(self, test_db_manager):
        """Smaller gap: a new rank-0 file for a kind demotes the previous
        canonical instead of hitting the unique constraint."""
        import core.media_ownership as mo
        detection_id = test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00'))
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            mo.record_media(cur, detection_id, [
                {'filename': 'old-canonical.mp3', 'kind': 'audio',
                 'rank': 0, 'bytes': 1}])
            mo.record_media(cur, detection_id, [
                {'filename': 'new-canonical.mp3', 'kind': 'audio',
                 'rank': 0, 'bytes': 2}])
            conn.commit()
            rows = conn.execute(
                "SELECT filename, rank FROM detection_media "
                "WHERE detection_id = ? ORDER BY rank", (detection_id,)).fetchall()
        assert [tuple(r) for r in rows] == [
            ('new-canonical.mp3', 0), ('old-canonical.mp3', 1)]


class TestReReviewFixes:
    """Regression pins for the implementation re-review residuals (R1-R5)."""

    def test_same_day_future_timestamp_stays_out_of_ready_rollups(
            self, test_db_manager, frozen_db_now):
        """R3: with now frozen at 12:00, a detection later today must not
        appear — the rollup path's upper bound is `timestamp <= now`, not
        `date <= today`."""
        test_db_manager.insert_detection(detection('2026-05-20T08:00:00'))
        test_db_manager.insert_detection(detection('2026-05-20T18:00:00'))
        build_all(test_db_manager)
        assert ready(test_db_manager)

        result = test_db_manager.get_summary_stats_for_period(datetime.min)
        assert result['totalObservations'] == 1  # not 2

    def test_delete_race_republished_same_name_never_survives_owned(
            self, test_db_manager, tmp_path, monkeypatch):
        """R1: a same-name file recreated on disk after the in-lock unlink
        cannot end up owned — the writer lock spans the ownership read,
        the unlinks, and the row deletes, so the worst case is a
        recognizable nonce-named orphan that reconciliation removes."""
        import core.db as live_db
        import core.media_reconciliation as mr
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'audio', str(audio_dir))

        detection_id = test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00'))
        nonce = test_db_manager.get_media_nonce(detection_id)
        name = f'race_{detection_id}-{nonce}.mp3'
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            live_db.media_ownership.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': 4}])
            conn.commit()
        path = audio_dir / name
        path.write_bytes(b'orig')

        real_unlink = live_db.media_ownership.unlink_owned_files

        def republishing_unlink(owned):
            removed = real_unlink(owned)
            # the racing creator republishes the same name immediately
            # after our unlink — inside our writer lock window, so it can
            # touch the filesystem but never the database
            path.write_bytes(b'republished')
            return removed

        monkeypatch.setattr(live_db.media_ownership, 'unlink_owned_files',
                            republishing_unlink)
        deleted = test_db_manager.delete_detection(detection_id)
        monkeypatch.setattr(live_db.media_ownership, 'unlink_owned_files',
                            real_unlink)

        assert deleted is not None
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0
        # the republished file is the documented recognizable orphan:
        # row gone -> reconciliation removes it after the grace period
        assert path.exists()
        import time as time_mod
        old_time = time_mod.time() - mr.ORPHAN_GRACE_SECONDS - 60
        import os as os_mod
        os_mod.utime(path, (old_time, old_time))
        monkeypatch.setitem(mr.KIND_DIRS, 'audio', str(audio_dir))
        stats = mr.scan_disk(test_db_manager)
        assert stats['residue_removed'] == 1
        assert not path.exists()

    def test_stale_inflight_summary_is_rebuilt_for_the_waiter(
            self, test_db_manager, monkeypatch):
        """R4: a request observing revision N must never return a joined
        payload built under an older revision — it discards and rebuilds."""
        import core.routes.observations as obs

        stale = {'revision': 1, 'data': {'totalObservations': 'stale'}}
        fresh = {'revision': 5, 'data': {'totalObservations': 'fresh'}}
        builds = iter([stale, fresh])
        monkeypatch.setattr(obs, '_build_versioned_summary_payload',
                            lambda period: next(builds))
        monkeypatch.setattr(obs, '_submit_db',
                            lambda fn, *a: _ImmediateJob(fn, *a))
        monkeypatch.setattr(obs, '_run_db', lambda fn, *a: 5)  # observed rev

        entry = obs._summary_cache['week']
        entry['payload'] = None
        entry['expires_at'] = 0.0
        entry['inflight'] = None
        try:
            result = obs._get_summary_period_payload('week')
        finally:
            entry['payload'] = None
            entry['expires_at'] = 0.0
            entry['inflight'] = None
        assert result == {'totalObservations': 'fresh'}


class _ImmediateJob:
    def __init__(self, fn, *args):
        self._result = fn(*args)

    def result(self, timeout=None):
        return self._result


class TestSecondReReviewFixes:
    """Regression pins for the second re-review residuals (S1-S3)."""

    def test_delete_classifies_resolution_under_the_writer_lock(
            self, test_db_manager, tmp_path, monkeypatch):
        """S1: a legacy row resolved between delete's invocation and its
        lock must be seen as RESOLVED by the locked read — the nonce-named
        file is unlinked, never left behind by a stale legacy-branch
        decision."""
        import core.db as live_db
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'audio', str(audio_dir))

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, extra, "
                "media_bytes, media_nonce) "
                "VALUES ('2024-01-15T08:30:00', '2024-01-15T08:30:00', "
                "'Turdus migratorius', 'American Robin', 0.9, '{}', NULL, NULL)")
            conn.commit()
            row_id = cur.lastrowid

        published = audio_dir / f'stage2_{row_id}-resolving.mp3'

        def resolving_lease_check(db):
            # simulates Stage 2 winning the window between delete's
            # invocation and its writer lock: the row becomes resolved
            # with recorded nonce-named media
            nonce = test_db_manager.get_or_create_media_nonce(row_id)
            name = f'stage2_{row_id}-{nonce}.mp3'
            (audio_dir / name).write_bytes(b'published')
            published_path[0] = audio_dir / name
            with test_db_manager.get_db_connection() as conn:
                cur = conn.cursor()
                live_db.media_ownership.record_media(cur, row_id, [
                    {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': 9}])
                conn.commit()
            return False  # no index build active

        published_path = [published]
        monkeypatch.setattr(live_db.maintenance_lease, 'index_build_active',
                            resolving_lease_check)
        deleted = test_db_manager.delete_detection(row_id)

        assert deleted is not None
        # the locked read saw the row RESOLVED: the recorded file is gone
        assert not published_path[0].exists()
        assert published_path[0].name in deleted['files_deleted']
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0

    def test_hybrid_bucket_uses_the_callers_clock(self, test_db_manager, monkeypatch):
        """S2: the helper must inherit the caller's `now`, not read a
        second clock — across midnight the two diverge and rollup/raw
        parity breaks."""
        test_db_manager.insert_detection(detection('2026-05-20T12:00:00'))
        test_db_manager.insert_detection(detection('2026-05-21T00:00:30'))
        build_all(test_db_manager)
        assert ready(test_db_manager)

        caller_now = datetime(2026, 5, 20, 23, 59, 59)
        # a drifted in-helper clock would see the next day
        monkeypatch.setattr('core.db.local_now',
                            lambda: datetime(2026, 5, 21, 0, 1, 0))
        result = test_db_manager.get_summary_stats_for_period(
            datetime.min, now=caller_now)
        assert result['totalObservations'] == 1  # caller's boundary, not the helper's

    def test_retry_exhaustion_rebuilds_instead_of_returning_stale(
            self, test_db_manager, monkeypatch):
        """S3: two consecutive stale joins under revision churn must end in
        a direct uncached rebuild — never in returning a wrapper older
        than a revision this request observed."""
        import core.routes.observations as obs

        joins = iter([{'revision': 4, 'data': 'stale-4'},
                      {'revision': 5, 'data': 'stale-5'}])
        observed = iter([5, 6])

        def fake_run_db(fn, *args):
            if getattr(fn, '__name__', '') == '_build_versioned_summary_payload':
                return {'revision': 6, 'data': 'fresh-6'}
            return next(observed)

        monkeypatch.setattr(obs, '_run_db', fake_run_db)
        monkeypatch.setattr(obs, '_serve_single_flight',
                            lambda *a, **kw: next(joins))

        entry = obs._summary_cache['month']
        entry['payload'] = None
        entry['expires_at'] = 0.0
        entry['inflight'] = None
        try:
            result = obs._get_summary_period_payload('month')
        finally:
            entry['payload'] = None
            entry['expires_at'] = 0.0
            entry['inflight'] = None
        assert result == 'fresh-6'


class TestAuditHourDayOnlyDates:

    def test_stale_hour_day_row_without_species_day_is_swept(
            self, test_db_manager):
        """A date surviving in hour_day alone (no detections, no
        species_day rows) is still drift and must be enqueued — the
        emptiness gate and the rollup-only sweep both consult hour_day."""
        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO hour_day (date, hour, count) VALUES "
                "('2024-02-01', 8, 3)")
            conn.commit()

        assert db_rollups.audit_rollups(test_db_manager) == {'2024-02-01'}


class TestThirdReReviewFixes:
    """Regression pins for the third re-review blocker (T1) and the
    reconciliation concurrency coverage gate."""

    def test_delete_holds_its_transaction_across_the_unlink_phase(
            self, test_db_manager, tmp_path, monkeypatch):
        """T1: _normalize_detection's filenames branch nests a
        get_db_connection whose exit ROLLS BACK the outer BEGIN IMMEDIATE
        — the unlinks and row deletes would then run unlocked. This pin
        asserts the write transaction is still open at unlink time."""
        import core.db as live_db
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'audio', str(audio_dir))

        detection_id = test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00'))
        nonce = test_db_manager.get_media_nonce(detection_id)
        name = f'txn_{detection_id}-{nonce}.mp3'
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            live_db.media_ownership.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': 2}])
            conn.commit()
        (audio_dir / name).write_bytes(b'xx')

        real_unlink = live_db.media_ownership.unlink_owned_files
        in_transaction_at_unlink = []

        def spying_unlink(owned):
            conn = getattr(test_db_manager._local, 'conn', None)
            in_transaction_at_unlink.append(
                bool(conn is not None and conn.in_transaction))
            return real_unlink(owned)

        monkeypatch.setattr(live_db.media_ownership, 'unlink_owned_files',
                            spying_unlink)
        deleted = test_db_manager.delete_detection(detection_id)

        assert deleted is not None
        assert in_transaction_at_unlink == [True]  # the lock was never dropped
        assert not (audio_dir / name).exists()

    def test_reattach_refuses_when_delete_wins_inside_the_lock(
            self, test_db_manager, tmp_path, monkeypatch):
        """Coverage gate from the re-reviews: the exact delete-vs-reattach
        ordering — the row vanishes after the scan's pre-checks — must end
        in refusal, never a ghost ownership row."""
        import core.media_reconciliation as mr
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(mr.KIND_DIRS, 'audio', str(audio_dir))
        monkeypatch.setitem(mr.KIND_DIRS, 'spectrogram', str(tmp_path))

        detection_id = test_db_manager.insert_detection(
            detection('2024-01-15T08:30:00'))
        nonce = test_db_manager.get_media_nonce(detection_id)
        from core.media_ownership import with_media_suffix
        from core.utils import build_detection_filenames
        base = build_detection_filenames(
            'American Robin', 0.9, '2024-01-15T08:30:00',
            audio_extension='mp3')['audio_filename']
        orphan = audio_dir / with_media_suffix(base, detection_id, nonce)
        orphan.write_bytes(b'complete')

        real_match = mr._canonical_fields_match

        def deleting_match(cursor, det_id, det_nonce, name):
            # the competing delete commits (simulated inside the repair's
            # own lock via its cursor) right after the field check
            result = real_match(cursor, det_id, det_nonce, name)
            cursor.execute("DELETE FROM detections WHERE id = ?", (det_id,))
            return result

        monkeypatch.setattr(mr, '_canonical_fields_match', deleting_match)
        stats = mr.scan_disk(test_db_manager)

        assert stats['reattached'] == 0
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM detection_media").fetchone()[0] == 0
        assert orphan.exists()  # untouched; ages into residue removal later
