"""Species summaries must agree before and after daily rollup construction."""
import pytest

from tests.database.test_db_rollups import detection, old_code_insert


def build_all(db):
    import core.db_rollups as db_rollups
    while not db_rollups.advance_build(db, max_days=2):
        pass


@pytest.fixture(params=[False, True], ids=['raw', 'rollups'])
def summary_db(request, test_db_manager):
    def prepare(rows):
        for timestamp, common, scientific in rows:
            test_db_manager.insert_detection(detection(timestamp, common, scientific))
        if request.param:
            build_all(test_db_manager)
        return test_db_manager
    return prepare


def test_inclusive_dates_and_name_variants(summary_db):
    db = summary_db([
        ('2026-11-06T23:59:59', 'Australian Magpie', 'Gymnorhina tibicen'),
        ('2026-11-07T00:00:00', 'Magpie', 'Gymnorhina tibicen'),
        ('2026-11-08T12:00:00', 'Australian Magpie', 'Gymnorhina tibicen'),
        ('2026-11-13T23:59:59.500000', 'Australian Magpie', 'Gymnorhina tibicen'),
        ('2026-11-14T00:00:00', 'Australian Magpie', 'Gymnorhina tibicen'),
    ])
    assert db.get_species_summary('2026-11-07', '2026-11-13') == [{
        'scientific_name': 'Gymnorhina tibicen', 'common_name': 'Australian Magpie',
        'count': 3, 'first_detected': '2026-11-07T00:00:00',
        'last_detected': '2026-11-13T23:59:59.500000',
    }]
    all_time = db.get_species_summary()
    assert all_time[0]['count'] == 5
    assert all_time[0]['first_detected'] == '2026-11-06T23:59:59'
    assert all_time[0]['last_detected'] == '2026-11-14T00:00:00'
    assert db.get_species_summary('2026-11-08', '2026-11-08')[0]['count'] == 1


def test_empty_results(summary_db):
    db = summary_db([])
    assert db.get_species_summary() == []
    assert db.get_species_summary('2026-11-07', '2026-11-13') == []


def test_taxonomy_aliases_legacy_names_and_sorting(summary_db, monkeypatch):
    # Use the same stable groups that the catalog consumes, independent of
    # which version of the downloaded model labels is installed in the image.
    import core.db as db_module

    def taxon(name):
        if name in ('Charadrius dubius', 'Thinornis dubius'):
            return ('Charadrius dubius', 'Thinornis dubius')
        return (name,) if name else ()

    monkeypatch.setattr(db_module, 'same_taxon_group', taxon)
    db = summary_db([
        ('2026-11-07T10:00:00', 'Little Ringed Plover', 'Charadrius dubius'),
        ('2026-11-08T10:00:00', 'Little Ringed Plover', 'Thinornis dubius'),
        ('2026-11-09T10:00:00', 'Little Ringed Plover', 'Thinornis dubius'),
        ('2026-11-07T11:00:00', 'Zulu legacy', ''),
        ('2026-11-07T12:00:00', 'Alpha legacy', ''),
        ('2026-11-07T13:00:00', 'Kookaburra', 'Dacelo novaeguineae'),
        ('2026-11-07T14:00:00', 'Willie Wagtail', 'Rhipidura leucophrys'),
    ])
    rows = db.get_species_summary()
    assert [r['common_name'] for r in rows] == [
        'Little Ringed Plover', 'Alpha legacy', 'Zulu legacy', 'Kookaburra', 'Willie Wagtail',
    ]
    assert rows[0]['scientific_name'] == 'Thinornis dubius'
    assert rows[0]['count'] == 3
    assert rows[0]['first_detected'] == '2026-11-07T10:00:00'
    assert rows[0]['last_detected'] == '2026-11-09T10:00:00'


def test_dirty_rollups_fall_back_to_raw_records(test_db_manager):
    import core.db_rollups as db_rollups

    db = test_db_manager
    db.insert_detection(detection('2026-11-07T10:00:00'))
    build_all(db)
    old_code_insert(db, '2026-11-08T10:00:00')
    with db.get_db_connection() as conn:
        db_rollups.enqueue_dirty_days(conn.cursor(), ['2026-11-08'])
        conn.commit()
    rows = db.get_species_summary('2026-11-07', '2026-11-08')
    assert sum(row['count'] for row in rows) == 2
    assert {row['common_name'] for row in rows} == {'American Robin', 'Old Bird'}
    while db_rollups.consume_dirty_days(db):
        pass
    assert db.get_species_summary('2026-11-07', '2026-11-08') == rows


@pytest.mark.parametrize('ready', [False, True], ids=['unready', 'ready'])
def test_all_history_reads_only_species_projection(test_db_manager, monkeypatch, ready):
    import core.db_rollups as db_rollups

    db = test_db_manager
    for i in range(1000):
        db.insert_detection(detection(f'2026-11-07T10:{i // 60:02d}:{i % 60:02d}'))
    if ready:
        build_all(db)

    def unexpected_readiness_check(cur):
        pytest.fail('All-history summary must not depend on daily-rollup readiness')

    monkeypatch.setattr(db_rollups, 'rollups_ready', unexpected_readiness_check)
    statements = []
    with db.get_db_connection() as conn:
        conn.set_trace_callback(statements.append)
    try:
        assert db.get_species_summary()[0]['count'] == 1000
    finally:
        with db.get_db_connection() as conn:
            conn.set_trace_callback(None)
    assert not any('detections' in sql or 'species_day' in sql for sql in statements)
    assert len(statements) == 1
    assert 'FROM species' in statements[0]


def test_ready_date_summary_uses_daily_rollups(test_db_manager):
    db = test_db_manager
    db.insert_detection(detection('2026-11-07T10:00:00'))
    build_all(db)
    statements = []
    with db.get_db_connection() as conn:
        conn.set_trace_callback(statements.append)
    try:
        assert db.get_species_summary('2026-11-07', '2026-11-07')[0]['count'] == 1
    finally:
        with db.get_db_connection() as conn:
            conn.set_trace_callback(None)
    assert not any('FROM detections' in sql for sql in statements)
    assert any('FROM species_day' in sql for sql in statements)
    assert statements[0] == 'BEGIN'
    assert statements[-1] == 'COMMIT'


@pytest.mark.parametrize('scientific', ['Oldus birdus', ''])
def test_missing_species_names_use_newest_detection(test_db_manager, scientific):
    db = test_db_manager
    # Alphabetical order and insertion order both disagree with newest timestamp.
    old_code_insert(db, '2026-11-07T10:00:00', 'Z Newest', scientific)
    old_code_insert(db, '2026-11-07T09:00:00', 'A Older', scientific)
    expected_names = ['A Older', 'Z Newest'] if not scientific else ['Z Newest']
    raw = db.get_species_summary('2026-11-07', '2026-11-07')
    assert [row['common_name'] for row in raw] == expected_names
    build_all(db)
    assert db.get_species_summary('2026-11-07', '2026-11-07') == raw


def test_raw_name_ties_use_latest_id(test_db_manager):
    db = test_db_manager
    old_code_insert(db, '2026-11-07T10:00:00', 'A Older')
    old_code_insert(db, '2026-11-07T10:00:00', 'Z Newest')
    before = db.get_species_summary('2026-11-07', '2026-11-07')
    assert before[0]['common_name'] == 'Z Newest'
    build_all(db)
    assert db.get_species_summary('2026-11-07', '2026-11-07') == before
    db.rebuild_species_table()
    assert db.get_species_summary('2026-11-07', '2026-11-07') == before


def test_catalog_and_summary_share_taxonomy_rules(summary_db, monkeypatch):
    import core.db as db_module
    monkeypatch.setattr(db_module, 'same_taxon_group', lambda name: ('same taxon',))
    db = summary_db([
        ('2026-11-07T10:00:00', 'A Bird', 'Oldus birdus'),
        ('2026-11-08T10:00:00', 'Z Bird', 'Newus birdus'),
    ])
    summary = db.get_species_summary()[0]
    catalog = db.get_all_unique_species()
    assert summary['count'] == 2
    assert catalog == [{key: summary[key] for key in (
        'scientific_name', 'common_name', 'last_detected',
    )}]
    assert summary['common_name'] == 'A Bird'


def test_missing_name_uses_latest_detection_outside_range(test_db_manager):
    db = test_db_manager
    old_code_insert(db, '2026-11-07T10:00:00', 'A Older')
    old_code_insert(db, '2026-11-08T10:00:00', 'Z Newest')
    before = db.get_species_summary('2026-11-07', '2026-11-07')
    assert before[0]['common_name'] == 'Z Newest'
    assert before[0]['count'] == 1
    assert before[0]['last_detected'] == '2026-11-07T10:00:00'
    build_all(db)
    assert db.get_species_summary('2026-11-07', '2026-11-07') == before
    db.rebuild_species_table()
    assert db.get_species_summary('2026-11-07', '2026-11-07') == before
