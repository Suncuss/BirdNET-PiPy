"""Tests for the cross-process maintenance lease and the coordinated
live-media index build.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 2):
acquisition is check-and-set under BEGIN IMMEDIATE (never two flags),
renewal and release are owner-checked, expiry allows takeover from a
crashed holder, and the index build defers to a live import.
"""
import threading

from core import maintenance_lease as lease


class TestLeaseProtocol:

    def test_acquire_is_exclusive(self, test_db_manager):
        assert lease.acquire(test_db_manager, 'index_build', 'owner-a', 60)
        assert not lease.acquire(test_db_manager, 'db_import', 'owner-b', 60)

    def test_same_owner_reacquire_refreshes(self, test_db_manager):
        assert lease.acquire(test_db_manager, 'db_import', 'owner-a', 60)
        assert lease.acquire(test_db_manager, 'db_import', 'owner-a', 60)

    def test_expired_lease_can_be_taken_over(self, test_db_manager):
        assert lease.acquire(test_db_manager, 'db_import', 'crashed', 60, now=1000)
        # 61 seconds later the crashed holder's lease has expired
        assert lease.acquire(test_db_manager, 'index_build', 'next', 60, now=1061)

    def test_renew_is_owner_checked(self, test_db_manager):
        lease.acquire(test_db_manager, 'db_import', 'owner-a', 60, now=1000)
        assert lease.renew(test_db_manager, 'owner-a', 60, now=1030)
        assert not lease.renew(test_db_manager, 'stranger', 60, now=1030)

    def test_renewal_keeps_long_import_alive(self, test_db_manager):
        """Per-batch renewal must outlive any fixed TTL — a live import is
        never expired out from under its owner."""
        lease.acquire(test_db_manager, 'db_import', 'imp', 60, now=1000)
        for minute in range(1, 10):  # renew each "batch" for 9 minutes
            assert lease.renew(test_db_manager, 'imp', 60, now=1000 + minute * 55)
        # a contender still can't take it near the end
        assert not lease.acquire(test_db_manager, 'index_build', 'idx', 60,
                                 now=1000 + 9 * 55 + 30)

    def test_release_is_owner_checked(self, test_db_manager):
        lease.acquire(test_db_manager, 'db_import', 'owner-a', 60)
        assert not lease.release(test_db_manager, 'stranger')
        assert not lease.acquire(test_db_manager, 'index_build', 'other', 60)
        assert lease.release(test_db_manager, 'owner-a')
        assert lease.acquire(test_db_manager, 'index_build', 'other', 60)

    def test_racing_acquirers_get_exactly_one_winner(self, test_db_manager):
        results = {}
        barrier = threading.Barrier(2)

        def contend(name):
            barrier.wait()
            results[name] = lease.acquire(test_db_manager, 'role', name, 60)

        threads = [threading.Thread(target=contend, args=(n,))
                   for n in ('a', 'b')]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results.values()) == [False, True]

class TestCoordinatedIndexBuild:

    def _drop_index(self, db):
        with db.get_db_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_detections_live_media")
            conn.commit()

    def test_builds_when_absent_and_releases_lease(self, test_db_manager):
        from core import media_frontier as mf
        self._drop_index(test_db_manager)
        assert not mf.live_media_indexes_exist(test_db_manager)

        assert mf.ensure_live_media_index(test_db_manager) is True

        assert mf.live_media_indexes_exist(test_db_manager)
        # lease released: an importer can acquire immediately
        assert lease.acquire(test_db_manager, 'db_import', 'imp', 60)

    def test_noop_when_index_already_exists(self, test_db_manager):
        from core import media_frontier as mf
        # fresh test DBs create the index at schema time
        assert mf.ensure_live_media_index(test_db_manager) is True

    def test_defers_while_import_holds_the_lease(self, test_db_manager):
        from core import media_frontier as mf
        self._drop_index(test_db_manager)
        lease.acquire(test_db_manager, 'db_import', 'importer', 120)

        assert mf.ensure_live_media_index(test_db_manager) is False
        assert not mf.live_media_indexes_exist(test_db_manager)
        # cleanup stays gated; a later start (post-import) builds it
        lease.release(test_db_manager, 'importer')
        assert mf.ensure_live_media_index(test_db_manager) is True

    def test_interrupted_build_reruns_cleanly(self, test_db_manager, monkeypatch):
        """A build that dies mid-CREATE INDEX leaves no index; the next
        start simply reruns it (restartable, not resumable)."""
        from core import media_frontier as mf
        self._drop_index(test_db_manager)

        real_get = test_db_manager.get_db_connection
        calls = {'n': 0}

        class Boom(RuntimeError):
            pass

        import contextlib

        @contextlib.contextmanager
        def dying_connection():
            calls['n'] += 1
            raise Boom('killed mid-build')
            yield  # pragma: no cover

        monkeypatch.setattr(test_db_manager, 'get_db_connection', dying_connection)
        try:
            mf.ensure_live_media_index(test_db_manager)
        except Boom:
            pass
        monkeypatch.setattr(test_db_manager, 'get_db_connection', real_get)

        # index absent, lease... may still be held (release also died) —
        # the TTL guarantees eventual takeover; simulate expiry via a
        # fresh acquire far in the future is out of scope here, so just
        # assert the rerun succeeds once the lease clears.
        with test_db_manager.get_db_connection() as conn:
            conn.execute("DELETE FROM meta WHERE key = 'maintenance_lease'")
            conn.commit()
        assert mf.ensure_live_media_index(test_db_manager) is True
        assert mf.live_media_indexes_exist(test_db_manager)


class TestSlowedBuildContention:
    """The interactive-write contract and Stage 2/3 enrollment: while the
    index build holds the lease, sustained jobs wait visibly and short
    mutations refuse BEFORE any side effect."""

    def _hold_build_lease(self, db):
        lease.acquire(db, 'index_build', 'builder', 120)

    def test_delete_refuses_before_any_side_effect(
            self, test_db_manager, sample_detection, tmp_path, monkeypatch):
        import core.db as live_db
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        monkeypatch.setitem(live_db.media_ownership.KIND_DIRS, 'audio', str(audio_dir))

        detection_id = test_db_manager.insert_detection(sample_detection)
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = test_db_manager.get_media_nonce(detection_id)
            name = f'a_{detection_id}-{nonce}.mp3'
            live_db.media_ownership.record_media(cur, detection_id, [
                {'filename': name, 'kind': 'audio', 'rank': 0, 'bytes': 1}])
            conn.commit()
        (audio_dir / name).write_bytes(b'x')

        self._hold_build_lease(test_db_manager)
        # Catch the exception class the LIVE core.db raises — conftest's
        # module eviction can leave this file's `lease` a stale generation
        # whose class object no longer matches.
        import pytest as _pytest
        with _pytest.raises(live_db.maintenance_lease.MaintenanceInProgressError):
            test_db_manager.delete_detection(detection_id)

        # zero side effects: file, row, and ownership all intact
        assert (audio_dir / name).exists()
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM detections WHERE id = ?",
                                (detection_id,)).fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM detection_media").fetchone()[0] == 1

        # lease released -> the same call goes through
        lease.release(test_db_manager, 'builder')
        deleted = test_db_manager.delete_detection(detection_id)
        assert deleted['files_deleted'] == [name]

    def test_rename_refuses_during_build(self, test_db_manager):
        import core.db as live_db
        self._hold_build_lease(test_db_manager)
        import pytest as _pytest
        with _pytest.raises(live_db.maintenance_lease.MaintenanceInProgressError):
            test_db_manager.rename_detection_media('a.mp3', 'b.mp3')

    def test_stage2_waits_out_the_build(self, test_db_manager, tmp_path, monkeypatch):
        """The audio import defers (visible waiting status) while the build
        holds the lease, then proceeds when it releases."""
        import threading

        from core import migration_audio as ma
        audio_dir = tmp_path / 'extracted'
        audio_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))
        # fast polling for the test (capture the original first — the
        # module object is shared, so a self-referential lambda recurses)
        original_acquire_with_wait = lease.acquire_with_wait
        monkeypatch.setattr(
            'core.migration_audio.maintenance_lease.acquire_with_wait',
            lambda db, role, owner, ttl, **kw: original_acquire_with_wait(
                db, role, owner, ttl, poll_seconds=0.05,
                **{k: v for k, v in kw.items() if k != 'poll_seconds'}))

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence, media_bytes, media_nonce) "
                "VALUES ('2024-01-15T10:30:00', '2024-01-15T10:30:00', "
                "'Turdus migratorius', 'American Robin', 0.9, NULL, NULL)")
            conn.commit()
            detection_id = cur.lastrowid
        source = tmp_path / 's.mp3'
        source.write_bytes(b'audio')

        self._hold_build_lease(test_db_manager)
        release_timer = threading.Timer(
            0.3, lambda: lease.release(test_db_manager, 'builder'))
        release_timer.start()
        try:
            result = ma.import_audio_files(
                test_db_manager, [(detection_id, str(source), 5)], 'imp-lease')
        finally:
            release_timer.cancel()

        assert result['imported'] == 1
        # and the import released its own lease on the way out
        assert lease.acquire(test_db_manager, 'index_build', 'later', 60)

    def test_stage3_without_db_needs_no_lease(self, test_db_manager, tmp_path, monkeypatch):
        """Ownership-less spectrogram generation (no db_manager) writes no
        DB rows and must not block on a held lease."""
        from core import migration_audio as ma
        audio_dir = tmp_path / 'extracted'
        spec_dir = tmp_path / 'spec'
        audio_dir.mkdir()
        spec_dir.mkdir()
        monkeypatch.setattr('core.migration_audio.EXTRACTED_AUDIO_DIR', str(audio_dir))
        monkeypatch.setattr('core.migration_audio.SPECTROGRAM_DIR', str(spec_dir))
        monkeypatch.setattr('core.migration_audio._convert_to_wav_if_needed',
                            lambda path: (path, False))
        monkeypatch.setattr(
            'core.migration_audio.generate_spectrogram',
            lambda wav, out, title, **kw: open(out, 'wb').write(b'webp'))
        (audio_dir / 'Legacy_90_x.mp3').write_bytes(b'a')

        self._hold_build_lease(test_db_manager)
        result = ma.generate_spectrograms_batch(['Legacy_90_x.mp3'], 'gen-lease')
        assert result['generated'] == 1
