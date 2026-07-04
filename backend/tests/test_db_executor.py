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


def test_gevent_job_timeout_raises_timeout_error():
    """gevent.Timeout is a BaseException, so the raw exception slips past
    `except Exception` in handle_api_errors and the dashboard inflight
    cleanup, leaking state. _GeventJob.result() must translate it to
    TimeoutError (an Exception subclass) so those handlers fire."""
    gevent = pytest.importorskip("gevent")
    executor = create_db_executor("gevent")

    def slow():
        # Sleep via gevent so the threadpool wrapper still yields, but
        # well past the timeout we'll apply.
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
            pytest.fail("gevent.Timeout leaked through _GeventJob.result()")
        except TimeoutError:
            pass
    finally:
        executor.shutdown(wait=False)
