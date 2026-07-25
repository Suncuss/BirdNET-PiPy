"""Tests for thread-local connection reuse in DatabaseManager."""
import threading

import pytest


class TestConnectionReuse:

    def test_same_thread_reuses_connection(self, test_db_manager):
        with test_db_manager.get_db_connection() as first:
            pass
        with test_db_manager.get_db_connection() as second:
            pass
        assert first is second

    def test_threads_get_distinct_connections(self, test_db_manager):
        seen = []

        def grab():
            with test_db_manager.get_db_connection() as conn:
                seen.append(conn)

        thread = threading.Thread(target=grab)
        thread.start()
        thread.join()
        with test_db_manager.get_db_connection() as conn:
            seen.append(conn)

        assert seen[0] is not seen[1]

    def test_uncommitted_writes_rolled_back_on_exit(self, test_db_manager):
        """A block that forgets to commit must not leak its transaction
        into the next use of the shared connection."""
        with test_db_manager.get_db_connection() as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence) "
                "VALUES ('2024-01-15T10:00:00', '2024-01-15T10:00:00', "
                "'Testus birdus', 'Test Bird', 0.9)")
            # no commit

        with test_db_manager.get_db_connection() as conn:
            assert not conn.in_transaction
            count = conn.execute(
                "SELECT COUNT(*) FROM detections").fetchone()[0]
        assert count == 0

    def test_exception_discards_connection(self, test_db_manager):
        with pytest.raises(RuntimeError):
            with test_db_manager.get_db_connection() as broken:
                raise RuntimeError("boom")

        # next call reopens and works
        with test_db_manager.get_db_connection() as fresh:
            fresh.execute("SELECT 1").fetchone()
        assert fresh is not broken

    def test_cache_pragmas_applied(self, test_db_manager):
        with test_db_manager.get_db_connection() as conn:
            assert conn.execute("PRAGMA cache_size").fetchone()[0] == -8192
            assert conn.execute("PRAGMA mmap_size").fetchone()[0] == 134217728
