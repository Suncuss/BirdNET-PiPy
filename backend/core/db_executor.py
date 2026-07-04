"""Execution boundary for API-side SQLite work.

sqlite3 runs blocking C code that does not yield to gevent. API routes use
this small wrapper to move database work onto a native worker while the
request greenlet waits cooperatively for the result.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class _StdlibJob:
    def __init__(self, future: Future):
        self._future = future

    def result(self, timeout: float | None = None) -> Any:
        # Raises concurrent.futures.TimeoutError if timeout exceeded.
        # Note: the underlying work is NOT cancelled — sqlite3 is blocking
        # C code; the pool worker stays occupied until the query returns
        # or busy_timeout (30s) trips. This call just unblocks the caller.
        return self._future.result(timeout=timeout)


class _GeventJob:
    def __init__(self, async_result):
        self._async_result = async_result

    def result(self, timeout: float | None = None) -> Any:
        # AsyncResult.get() raises gevent.Timeout, which is a BaseException
        # subclass — `except Exception` (handle_api_errors, inflight cleanup)
        # would silently skip it, leaking state. Translate to TimeoutError so
        # callers can treat it uniformly with _StdlibJob. Same caveat as
        # _StdlibJob.result(): the underlying thread keeps running.
        from gevent import Timeout as _GeventTimeout
        try:
            return self._async_result.get(timeout=timeout)
        except _GeventTimeout as exc:
            raise TimeoutError(f"DB job exceeded {timeout}s") from exc


class StdlibDBExecutor:
    """Single-lane DB executor for threading/test mode."""

    mode = 'threading'

    def __init__(self, workers: int = 1):
        self._pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix='api-db',
        )

    def submit(self, func: Callable[..., Any], *args, **kwargs) -> _StdlibJob:
        return _StdlibJob(self._pool.submit(func, *args, **kwargs))

    def run(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit(func, *args, **kwargs).result()

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)


class GeventDBExecutor:
    """Single native DB lane whose waits yield the gevent event loop."""

    mode = 'gevent'

    def __init__(self, workers: int = 1):
        from gevent.threadpool import ThreadPool

        self._pool = ThreadPool(workers)

    def submit(self, func: Callable[..., Any], *args, **kwargs) -> _GeventJob:
        return _GeventJob(self._pool.spawn(func, *args, **kwargs))

    def run(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit(func, *args, **kwargs).result()

    def shutdown(self, wait: bool = False) -> None:
        if wait:
            self._pool.join()
        self._pool.kill()


def create_db_executor(async_mode: str = 'threading', workers: int = 1):
    if async_mode == 'gevent':
        return GeventDBExecutor(workers=workers)
    return StdlibDBExecutor(workers=workers)
