import threading
import time

import pytest

from core.db_executor import StdlibDBExecutor, create_db_executor


def test_stdlib_executor_returns_values():
    executor = StdlibDBExecutor()
    try:
        assert executor.run(lambda value: value + 1, 2) == 3
    finally:
        executor.shutdown(wait=False)


def test_stdlib_executor_propagates_exceptions():
    executor = StdlibDBExecutor()

    def fail():
        raise RuntimeError("boom")

    try:
        with pytest.raises(RuntimeError, match="boom"):
            executor.run(fail)
    finally:
        executor.shutdown(wait=False)


def test_stdlib_executor_serializes_jobs():
    executor = StdlibDBExecutor()
    first_started = threading.Event()
    release_first = threading.Event()
    events = []

    def first():
        events.append("first-start")
        first_started.set()
        release_first.wait(timeout=1)
        events.append("first-end")

    def second():
        events.append("second")

    try:
        first_job = executor.submit(first)
        assert first_started.wait(timeout=1)
        second_job = executor.submit(second)

        time.sleep(0.02)
        assert events == ["first-start"]

        release_first.set()
        first_job.result()
        second_job.result()
        assert events == ["first-start", "first-end", "second"]
    finally:
        executor.shutdown(wait=False)


def test_gevent_executor_wait_yields_event_loop():
    gevent = pytest.importorskip("gevent")
    executor = create_db_executor("gevent")
    ticks = []

    def blocking_db_work():
        time.sleep(0.05)
        return "done"

    def ticker():
        while len(ticks) < 3:
            ticks.append("tick")
            gevent.sleep(0.005)

    try:
        job = executor.submit(blocking_db_work)
        ticker_greenlet = gevent.spawn(ticker)

        assert job.result() == "done"
        ticker_greenlet.join(timeout=1)
        assert len(ticks) >= 3
    finally:
        executor.shutdown(wait=False)


def test_gevent_executor_survives_missed_wakeup(monkeypatch):
    """The old gevent ThreadPool lane could strand a job until the next
    submission arrived (missed cross-thread wakeup / wedged spawn). The
    replacement lane's waiters poll in short slices and re-check the done
    flag, so even with the wakeup watcher fully suppressed a result must
    arrive within about one poll slice — never an unbounded stall."""
    pytest.importorskip("gevent")

    from core import db_executor
    from core.db_executor import create_db_executor

    monkeypatch.setattr(db_executor, "_POLL_SLICE_SECONDS", 0.05)
    executor = create_db_executor("gevent")

    class _DeadWatcher:
        def send(self):
            pass  # simulate the lost wakeup

    try:
        monkeypatch.setattr(executor, "_watcher", _DeadWatcher())
        start = time.monotonic()
        assert executor.submit(lambda: "rescued").result(timeout=5) == "rescued"
        assert time.monotonic() - start < 1.0
    finally:
        executor.shutdown(wait=False)


def test_gevent_executor_propagates_exceptions():
    pytest.importorskip("gevent")
    from core.db_executor import create_db_executor

    executor = create_db_executor("gevent")

    def fail():
        raise RuntimeError("boom")

    try:
        with pytest.raises(RuntimeError, match="boom"):
            executor.submit(fail).result(timeout=5)
    finally:
        executor.shutdown(wait=False)


def test_gevent_executor_serializes_jobs():
    """workers=1 must stay a strict single lane: the second job may not
    start until the first finishes."""
    pytest.importorskip("gevent")
    import threading

    from core.db_executor import create_db_executor

    executor = create_db_executor("gevent")
    first_started = threading.Event()
    release_first = threading.Event()
    events = []

    def first():
        events.append("first-start")
        first_started.set()
        release_first.wait(timeout=1)
        events.append("first-end")

    def second():
        events.append("second")

    try:
        first_job = executor.submit(first)
        assert first_started.wait(timeout=1)
        second_job = executor.submit(second)

        time.sleep(0.02)
        assert events == ["first-start"]

        release_first.set()
        first_job.result(timeout=5)
        second_job.result(timeout=5)
        assert events == ["first-start", "first-end", "second"]
    finally:
        executor.shutdown(wait=False)


def test_gevent_executor_rejects_submit_after_shutdown():
    pytest.importorskip("gevent")
    from core.db_executor import create_db_executor

    executor = create_db_executor("gevent")
    executor.shutdown(wait=False)
    with pytest.raises(RuntimeError):
        executor.submit(lambda: None)


def test_gevent_executor_shutdown_wait_joins_workers():
    """shutdown(wait=True) must not return while a worker is mid-job — a
    caller deleting a temp SQLite file right after would race the write."""
    pytest.importorskip("gevent")
    from core.db_executor import create_db_executor

    executor = create_db_executor("gevent")
    done = []

    def slow():
        time.sleep(0.2)
        done.append(True)

    executor.submit(slow)
    executor.shutdown(wait=True)
    assert done == [True]
    # A second wait must be a no-op, not a hang on already-consumed tokens.
    executor.shutdown(wait=True)


def test_gevent_lane_timeout_raises_timeout_error():
    """gevent.Timeout is a BaseException, so the raw exception slips past
    `except Exception` in handle_api_errors and the dashboard inflight
    cleanup, leaking state. _LaneJob.result() must raise TimeoutError (an
    Exception subclass) so those handlers fire."""
    gevent = pytest.importorskip("gevent")
    executor = create_db_executor("gevent")

    def slow():
        # Occupies the native worker well past the timeout we'll apply.
        time.sleep(0.5)
        return "never"

    try:
        job = executor.submit(slow)
        # Critical: must be TimeoutError (Exception), not gevent.Timeout.
        with pytest.raises(TimeoutError):
            job.result(timeout=0.05)
        # And the raw gevent.Timeout must not leak through.
        job2 = executor.submit(slow)
        try:
            job2.result(timeout=0.05)
        except gevent.Timeout:
            pytest.fail("gevent.Timeout leaked through _LaneJob.result()")
        except TimeoutError:
            pass
    finally:
        executor.shutdown(wait=False)
