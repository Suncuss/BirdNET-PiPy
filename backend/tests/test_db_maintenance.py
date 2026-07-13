"""Tests for core.db_maintenance — integrity checks and rotating backups."""
import os
import sqlite3
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.db import DatabaseManager
from core.db_maintenance import (
    BACKUPS_TO_KEEP,
    HEALTH_INTERVAL_SECONDS,
    _backup_dir,
    _list_backups,
    _marker_path,
    create_backup,
    maybe_run_health_cycle,
    run_quick_check,
)


@pytest.fixture
def db_manager(tmp_path):
    """DatabaseManager in its own directory (backups land beside the DB)."""
    db_path = str(tmp_path / 'db' / 'birds.db')
    manager = DatabaseManager(db_path=db_path)
    manager.insert_detection({
        'timestamp': '2024-01-15T10:30:00',
        'group_timestamp': '2024-01-15T10:30:00',
        'scientific_name': 'Turdus migratorius',
        'common_name': 'American Robin',
        'confidence': 0.9,
        'latitude': 40.0, 'longitude': -74.0,
        'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
    })
    return manager


def corrupt(db_path):
    """Overwrite an interior page so quick_check reports corruption.

    Checkpoints the WAL first: with long-lived connections holding the WAL
    open, a live WAL copy of the page would shadow the damage and mask it.
    (Real SD corruption overwhelmingly hits the large main file, which is
    exactly what this models.)
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    size = os.path.getsize(db_path)
    assert size > 8192, "need at least 3 pages to corrupt the middle one"
    with open(db_path, 'r+b') as f:
        f.seek(4096)
        f.write(b'\xde\xad\xbe\xef' * 1024)


class TestQuickCheck:

    def test_passes_on_healthy_database(self, db_manager):
        assert run_quick_check(db_manager) is True

    def test_fails_on_corrupted_database(self, db_manager):
        corrupt(db_manager.db_path)
        assert run_quick_check(db_manager) is False

    def test_fails_on_missing_database_without_creating_it(self, db_manager):
        """A vanished DB file must fail the check — and the read-only open
        must not quietly create an empty file where the DB used to be."""
        for suffix in ('', '-wal', '-shm'):
            path = db_manager.db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

        assert run_quick_check(db_manager) is False
        assert not os.path.exists(db_manager.db_path)

    def test_fails_on_foreign_empty_file(self, db_manager):
        """A zero-length file passes quick_check structurally; it must
        still fail (nothing worth rotating good backups away for)."""
        for suffix in ('-wal', '-shm'):
            path = db_manager.db_path + suffix
            if os.path.exists(path):
                os.unlink(path)
        with open(db_manager.db_path, 'w'):
            pass

        assert run_quick_check(db_manager) is False


class TestCreateBackup:

    def test_backup_is_a_valid_consistent_snapshot(self, db_manager):
        path = create_backup(db_manager)

        assert path is not None and os.path.exists(path)
        conn = sqlite3.connect(path)
        count = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.close()
        assert count == 1
        assert integrity == 'ok'

    def test_rotation_keeps_newest(self, db_manager):
        backup_dir = _backup_dir(db_manager.db_path)
        os.makedirs(backup_dir)
        old = [os.path.join(backup_dir, f'birds-2020010{i}-000000.db')
               for i in (1, 2)]
        for p in old:
            open(p, 'w').close()

        new_path = create_backup(db_manager)

        remaining = _list_backups(backup_dir)
        assert len(remaining) == BACKUPS_TO_KEEP
        assert new_path in remaining
        assert old[0] not in remaining  # oldest pruned

    def test_skips_when_disk_space_low(self, db_manager):
        fake_usage = type('u', (), {'total': 100, 'used': 100, 'free': 0})()
        with patch('core.db_maintenance.shutil.disk_usage',
                   return_value=fake_usage):
            assert create_backup(db_manager) is None
        assert _list_backups(_backup_dir(db_manager.db_path)) == []

    def test_stray_tmp_file_cleaned_up(self, db_manager):
        backup_dir = _backup_dir(db_manager.db_path)
        os.makedirs(backup_dir)
        stray = os.path.join(backup_dir, 'birds-20200101-000000.db.tmp')
        open(stray, 'w').close()

        create_backup(db_manager)

        assert not os.path.exists(stray)


class TestHealthCycle:

    def test_first_cycle_checks_and_backs_up(self, db_manager):
        maybe_run_health_cycle(db_manager)

        assert os.path.exists(_marker_path(db_manager.db_path))
        assert len(_list_backups(_backup_dir(db_manager.db_path))) == 1

    def test_nothing_due_is_a_noop(self, db_manager):
        maybe_run_health_cycle(db_manager)
        first = _list_backups(_backup_dir(db_manager.db_path))

        maybe_run_health_cycle(db_manager)

        assert _list_backups(_backup_dir(db_manager.db_path)) == first

    def test_due_again_after_interval(self, db_manager):
        maybe_run_health_cycle(db_manager)
        future = time.time() + HEALTH_INTERVAL_SECONDS + 1

        maybe_run_health_cycle(db_manager, now=future)

        assert len(_list_backups(_backup_dir(db_manager.db_path))) == 2

    def test_corruption_blocks_backup_and_marker(self, db_manager):
        """A corrupt live file must never rotate a good backup away, and
        the failed check must stay due so it re-alerts next cycle."""
        corrupt(db_manager.db_path)

        maybe_run_health_cycle(db_manager)

        assert not os.path.exists(_marker_path(db_manager.db_path))
        assert _list_backups(_backup_dir(db_manager.db_path)) == []
