"""Batched (timestamp, id) keyset walks must seek to their cursor.

A walk whose cursor is a scan instead of a seek costs O(rows behind the
cursor) per batch — O(n²) for the whole walk (the media frontier took ~7
minutes instead of ~6s on a 1.16M-row station). Costs are counted in SQLite
VM steps, so the checks are timing-free. See core.db_schema.keyset_after.
The export walk has its own check in tests/api/test_detections_api.py.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROWS = 2000


@pytest.fixture(params=[False, True], ids=['stale-stats', 'fresh-stats'])
def walk_db(request, test_db_manager):
    """ROWS one-per-second detections that all own media (so the frontier
    skips resolution and every row is a cleanup candidate), with planner
    stats either stale (analyzed while empty) or fresh — plans differ, and
    a station can be in either state. Returns (db, keys oldest-first)."""
    start = datetime(2024, 1, 1)
    values = []
    for i in range(ROWS):
        ts = (start + timedelta(seconds=i)).strftime('%Y-%m-%dT%H:%M:%S')
        values.append((ts, ts))
    with test_db_manager.get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO detections (timestamp, group_timestamp, scientific_name, "
            "common_name, confidence, media_bytes) "
            "VALUES (?, ?, 'Turdus migratorius', 'Robin', 0.9, 1000)", values)
        conn.commit()
        if request.param:
            conn.execute("ANALYZE")
        keys = conn.execute(
            "SELECT timestamp, id FROM detections ORDER BY timestamp, id").fetchall()
    return test_db_manager, [tuple(k) for k in keys]


def _vm_steps(db, call):
    """SQLite VM steps spent by call() on this thread's shared connection."""
    steps = 0

    def count():
        nonlocal steps
        steps += 1
        return 0

    with db.get_db_connection() as conn:
        conn.set_progress_handler(count, 1)
    try:
        call()
    finally:
        with db.get_db_connection() as conn:
            conn.set_progress_handler(None, 1)
    return steps


def _assert_flat(shallow_steps, deep_steps, walk):
    assert deep_steps < shallow_steps * 2, (
        f"{walk}: batch deep in the walk cost {deep_steps} VM steps vs "
        f"{shallow_steps} near its start — the cursor is scanned, not sought")


def test_cleanup_candidate_walk_seeks(walk_db):
    db, keys = walk_db

    def batch(cursor):
        rows = db.get_cleanup_candidates_batch(*cursor, limit=10)
        assert len(rows) == 10

    _assert_flat(_vm_steps(db, lambda: batch(keys[20])),
                 _vm_steps(db, lambda: batch(keys[-40])), 'cleanup candidates')


def test_frontier_walk_seeks(walk_db):
    import core.media_frontier as mf
    db, keys = walk_db

    def advance_from(cursor):
        with db.get_db_connection() as conn:
            mf._store_cursor(conn.cursor(), cursor)
            conn.commit()
        return _vm_steps(db, lambda: mf.advance_frontier(db, batch_rows=10))

    _assert_flat(advance_from(keys[20]), advance_from(keys[-40]), 'media frontier')


def test_no_expanded_or_form_keyset_in_core():
    """Tripwire: new walks must use keyset_after/keyset_before rather than
    re-spell the cursor in the expanded OR form the planner can't seek on."""
    core = Path(__file__).resolve().parents[2] / 'core'
    pattern = re.compile(r'timestamp\s*[<>]\s*\?\s*OR\s*\(\s*timestamp\s*=\s*\?')
    offenders = [
        f'{path.name}:{lineno}'
        for path in core.rglob('*.py')
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
        if pattern.search(line.split('#', 1)[0])
    ]
    assert not offenders, f'expanded OR-form keyset cursor: {offenders}'
