"""Tests for the species rollup table (core.db_species).

The rollup's contract: after any sequence of insert_detection /
delete_detection calls, the species table is byte-identical to what
rebuild() computes from the detections table alone.
"""
import sqlite3


def _detection(ts, sci='Turdus migratorius', common='American Robin',
               confidence=0.8, extra=None):
    return {
        'timestamp': ts, 'group_timestamp': ts,
        'scientific_name': sci, 'common_name': common,
        'confidence': confidence,
        'latitude': 40.7128, 'longitude': -74.0060,
        'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        'extra': extra or {},
    }


def species_rows(db_manager):
    conn = sqlite3.connect(db_manager.db_path)
    conn.row_factory = sqlite3.Row
    rows = {row['species_key']: dict(row) for row in
            conn.execute("SELECT * FROM species ORDER BY species_key")}
    conn.close()
    return rows


class TestSpeciesInsert:

    def test_first_detection_creates_row(self, test_db_manager):
        detection_id = test_db_manager.insert_detection(
            _detection('2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}))

        rows = species_rows(test_db_manager)
        row = rows['Turdus migratorius']
        assert row['detection_count'] == 1
        assert row['common_name'] == 'American Robin'
        assert row['ebird_code'] == 'amerob'
        assert row['first_detected'] == '2024-01-15T10:00:00'
        assert row['last_detected'] == '2024-01-15T10:00:00'
        assert row['latest_id'] == detection_id

    def test_newer_detection_advances_latest(self, test_db_manager):
        test_db_manager.insert_detection(_detection('2024-01-15T10:00:00'))
        newer_id = test_db_manager.insert_detection(
            _detection('2024-01-16T08:00:00'))

        row = species_rows(test_db_manager)['Turdus migratorius']
        assert row['detection_count'] == 2
        assert row['first_detected'] == '2024-01-15T10:00:00'
        assert row['last_detected'] == '2024-01-16T08:00:00'
        assert row['latest_id'] == newer_id

    def test_out_of_order_insert_updates_first_not_latest(self, test_db_manager):
        """Bulk imports insert history out of order; first_detected must
        move back while last_detected/latest_id stay."""
        newest_id = test_db_manager.insert_detection(
            _detection('2024-06-01T10:00:00'))
        test_db_manager.insert_detection(_detection('2023-01-01T10:00:00'))

        row = species_rows(test_db_manager)['Turdus migratorius']
        assert row['first_detected'] == '2023-01-01T10:00:00'
        assert row['last_detected'] == '2024-06-01T10:00:00'
        assert row['latest_id'] == newest_id

    def test_newest_common_name_wins(self, test_db_manager):
        """V2/V3 English drift: the newest detection's name represents."""
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', sci='Turdus merula',
            common='Eurasian Blackbird'))
        test_db_manager.insert_detection(_detection(
            '2024-02-01T10:00:00', sci='Turdus merula',
            common='Common Blackbird'))

        rows = species_rows(test_db_manager)
        assert len(rows) == 1
        assert rows['Turdus merula']['common_name'] == 'Common Blackbird'
        assert rows['Turdus merula']['detection_count'] == 2

    def test_older_insert_does_not_regress_name_or_ebird(self, test_db_manager):
        test_db_manager.insert_detection(_detection(
            '2024-02-01T10:00:00', common='Common Blackbird',
            sci='Turdus merula', extra={'ebird_code': 'combla'}))
        test_db_manager.insert_detection(_detection(
            '2023-01-01T10:00:00', common='Eurasian Blackbird',
            sci='Turdus merula'))

        row = species_rows(test_db_manager)['Turdus merula']
        assert row['common_name'] == 'Common Blackbird'
        assert row['ebird_code'] == 'combla'

    def test_null_ebird_keeps_existing(self, test_db_manager):
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))

        assert species_rows(test_db_manager)[
            'Turdus migratorius']['ebird_code'] == 'amerob'

    def test_legacy_blank_sci_keys_by_common_name(self, test_db_manager):
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', sci='', common='Mystery Bird A'))
        test_db_manager.insert_detection(_detection(
            '2024-01-15T11:00:00', sci='', common='Mystery Bird B'))

        rows = species_rows(test_db_manager)
        assert 'Mystery Bird A' in rows and 'Mystery Bird B' in rows
        assert rows['Mystery Bird A']['scientific_name'] == ''


class TestSpeciesDelete:

    def test_delete_decrements_count(self, test_db_manager):
        keep_id = test_db_manager.insert_detection(
            _detection('2024-01-15T10:00:00', confidence=0.7))
        drop_id = test_db_manager.insert_detection(
            _detection('2024-01-15T11:00:00', confidence=0.9))

        test_db_manager.delete_detection(drop_id)

        row = species_rows(test_db_manager)['Turdus migratorius']
        assert row['detection_count'] == 1
        assert row['latest_id'] == keep_id
        assert row['last_detected'] == '2024-01-15T10:00:00'
        assert abs(row['sum_confidence'] - 0.7) < 1e-9

    def test_delete_first_recomputes_boundary(self, test_db_manager):
        first_id = test_db_manager.insert_detection(
            _detection('2024-01-01T10:00:00'))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))

        test_db_manager.delete_detection(first_id)

        row = species_rows(test_db_manager)['Turdus migratorius']
        assert row['first_detected'] == '2024-02-01T10:00:00'

    def test_last_detection_removes_species_row(self, test_db_manager):
        only_id = test_db_manager.insert_detection(
            _detection('2024-01-15T10:00:00'))

        test_db_manager.delete_detection(only_id)

        assert species_rows(test_db_manager) == {}

    def test_delete_newest_recomputes_name_and_ebird(self, test_db_manager):
        """The deleted newest row may have defined the display name and
        ebird code; both must fall back to the new latest row, exactly as
        a rebuild would derive them."""
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', sci='Turdus merula',
            common='Eurasian Blackbird', extra={'ebird_code': 'eurbla'}))
        newest_id = test_db_manager.insert_detection(_detection(
            '2024-02-01T10:00:00', sci='Turdus merula',
            common='Common Blackbird', extra={'ebird_code': 'combla'}))

        test_db_manager.delete_detection(newest_id)

        row = species_rows(test_db_manager)['Turdus merula']
        assert row['common_name'] == 'Eurasian Blackbird'
        assert row['ebird_code'] == 'eurbla'

    def test_delete_nonlatest_ebird_source_clears_orphaned_code(
            self, test_db_manager):
        """The rollup's code came from an older row (latest has none);
        deleting that source row must re-derive — to NULL here, exactly
        what a rebuild would produce, not a value no remaining row holds."""
        source_id = test_db_manager.insert_detection(_detection(
            '2024-01-01T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))
        assert species_rows(test_db_manager)[
            'Turdus migratorius']['ebird_code'] == 'amerob'

        test_db_manager.delete_detection(source_id)

        incremental = species_rows(test_db_manager)['Turdus migratorius']
        assert incremental['ebird_code'] is None
        test_db_manager.rebuild_species_table()
        rebuilt = species_rows(test_db_manager)['Turdus migratorius']
        assert incremental['ebird_code'] == rebuilt['ebird_code']

    def test_delete_nonlatest_row_keeps_code_other_rows_hold(
            self, test_db_manager):
        """Deleting one of several code-carrying rows re-derives the same
        code from the survivors."""
        source_id = test_db_manager.insert_detection(_detection(
            '2024-01-01T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))

        test_db_manager.delete_detection(source_id)

        assert species_rows(test_db_manager)[
            'Turdus migratorius']['ebird_code'] == 'amerob'

    def test_delete_newest_backfills_ebird_from_older_row(self, test_db_manager):
        """New latest row lacks a code -> the newest row that has one
        supplies it (mirroring rebuild's backfill)."""
        test_db_manager.insert_detection(_detection(
            '2024-01-01T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-01-15T10:00:00'))
        newest_id = test_db_manager.insert_detection(
            _detection('2024-02-01T10:00:00', extra={'ebird_code': 'amerob2'}))

        test_db_manager.delete_detection(newest_id)

        row = species_rows(test_db_manager)['Turdus migratorius']
        assert row['ebird_code'] == 'amerob'


class TestRollupSelfHeal:

    def test_incremental_matches_rebuild(self, test_db_manager):
        """The core contract: incremental upkeep == rebuild from scratch."""
        detections = [
            _detection('2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}),
            _detection('2024-01-15T11:00:00'),
            _detection('2023-06-01T08:00:00'),  # out of order
            _detection('2024-02-01T09:00:00', sci='Turdus merula',
                       common='Eurasian Blackbird'),
            _detection('2024-03-01T09:00:00', sci='Turdus merula',
                       common='Common Blackbird',
                       extra={'ebird_code': 'combla'}),
            _detection('2024-01-20T12:00:00', sci='', common='Mystery Bird'),
        ]
        ids = [test_db_manager.insert_detection(d) for d in detections]
        test_db_manager.delete_detection(ids[1])
        # Delete a species' newest row whose display name and ebird differ
        # from its predecessor's — the recompute must match rebuild
        test_db_manager.delete_detection(ids[4])
        # Delete a non-latest, code-less row that defines first_detected —
        # covers the skip-ebird path and the first-boundary recompute
        test_db_manager.delete_detection(ids[2])

        incremental = species_rows(test_db_manager)
        test_db_manager.rebuild_species_table()
        rebuilt = species_rows(test_db_manager)

        # sum_confidence compares with tolerance (incremental float adds vs
        # one SQL SUM can differ in the last bits); everything else exactly.
        for key, row in rebuilt.items():
            inc = incremental.pop(key)
            assert abs(inc.pop('sum_confidence')
                       - row.pop('sum_confidence')) < 1e-9
            assert inc == row
        assert incremental == {}

    def test_startup_check_rebuilds_after_bypass_writes(self, test_db_manager):
        """Writes that bypass insert_detection (bulk import) are healed by
        the next DatabaseManager init."""
        test_db_manager.insert_detection(_detection('2024-01-15T10:00:00'))

        # Simulate a bypassing writer
        conn = sqlite3.connect(test_db_manager.db_path)
        conn.execute("""
            INSERT INTO detections (timestamp, group_timestamp,
                scientific_name, common_name, confidence, extra)
            VALUES ('2024-01-16T10:00:00', '2024-01-16T10:00:00',
                    'Cyanocitta cristata', 'Blue Jay', 0.9, '{}')
        """)
        conn.commit()
        conn.close()
        assert 'Cyanocitta cristata' not in species_rows(test_db_manager)

        from core.db import DatabaseManager
        DatabaseManager(db_path=test_db_manager.db_path)

        rows = species_rows(test_db_manager)
        assert rows['Cyanocitta cristata']['detection_count'] == 1
        assert rows['Turdus migratorius']['detection_count'] == 1

    def test_rebuild_tolerates_malformed_extra(self, test_db_manager):
        """extra is unconstrained text and Python reads tolerate bad JSON —
        the SQL-side rebuild must too, or one bad historical value makes
        DatabaseManager initialization crash-loop."""
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))

        conn = sqlite3.connect(test_db_manager.db_path)
        # newest robin row + a second species' only row get malformed extra
        conn.execute("UPDATE detections SET extra = 'not json' "
                     "WHERE timestamp = '2024-02-01T10:00:00'")
        conn.execute("""
            INSERT INTO detections (timestamp, group_timestamp,
                scientific_name, common_name, confidence, extra)
            VALUES ('2024-01-16T10:00:00', '2024-01-16T10:00:00',
                    'Cyanocitta cristata', 'Blue Jay', 0.9, '{bad')
        """)
        conn.commit()
        conn.close()

        # Startup path: consistency check sees the bypass write and rebuilds
        from core.db import DatabaseManager
        DatabaseManager(db_path=test_db_manager.db_path)

        rows = species_rows(test_db_manager)
        assert rows['Turdus migratorius']['ebird_code'] == 'amerob'
        assert rows['Cyanocitta cristata']['ebird_code'] is None

    def test_rebuild_backfills_ebird_from_older_rows(self, test_db_manager):
        """A species whose newest row lacks ebird_code still gets it from
        the newest row that has one."""
        test_db_manager.insert_detection(_detection(
            '2024-01-15T10:00:00', extra={'ebird_code': 'amerob'}))
        test_db_manager.insert_detection(_detection('2024-02-01T10:00:00'))

        test_db_manager.rebuild_species_table()

        assert species_rows(test_db_manager)[
            'Turdus migratorius']['ebird_code'] == 'amerob'
