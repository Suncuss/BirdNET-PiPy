"""Execution boundary for API-side SQLite work.

sqlite3 runs blocking C code that does not yield to gevent. API routes use
this small wrapper to move database work onto a native worker while the
request greenlet waits cooperatively for the result.
"""
from __future__ import annotations

import collections
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

try:
    # The C implementation. Its blocking get() parks the native worker on a
    # C-level lock that gevent's monkey-patching never touches — patch_all
    # substitutes queue.SimpleQueue with a pure-Python version built on
    # patched primitives, which must NOT be used from a real thread.
    from _queue import SimpleQueue as _NativeSimpleQueue
except ImportError:  # pragma: no cover - CPython always ships _queue
    from queue import SimpleQueue as _NativeSimpleQueue

# Waiters sleep in short slices instead of one long wait: if the worker's
# cross-thread wakeup is ever missed, the next slice notices the done flag,
# bounding a missed wakeup at one slice instead of an unbounded stall.
_POLL_SLICE_SECONDS = 0.5


class _StdlibJob:
    def __init__(self, future: Future):
        self._future = future

    def result(self, timeout: float | None = None) -> Any:
        # Raises concurrent.futures.TimeoutError if timeout exceeded.
        # Note: the underlying work is NOT cancelled — sqlite3 is blocking
        # C code; the pool worker stays occupied until the query returns
        # or busy_timeout (30s) trips. This call just unblocks the caller.
        return self._future.result(timeout=timeout)


class _LaneJob:
    """One submitted DB job; created and awaited on the hub thread.

    The worker thread only touches ``_finish`` (plain attribute writes —
    GIL-atomic, no greenlet machinery, safe cross-thread). The gevent Event
    is set exclusively from the hub thread via the executor's wakeup
    watcher; waiters double-check ``_done`` each poll slice so a missed
    wakeup delays them by at most one slice.
    """

    __slots__ = ('_value', '_exc', '_done', '_event')

    def __init__(self):
        from gevent.event import Event

        self._value = None
        self._exc: BaseException | None = None
        self._done = False
        self._event = Event()

    def _finish(self, value, exc) -> None:
        # Worker thread. Order matters: publish the payload before the flag.
        self._value = value
        self._exc = exc
        self._done = True

    def _deliver(self) -> None:
        # Hub thread only.
        self._event.set()

    def result(self, timeout: float | None = None) -> Any:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._done:
                if self._exc is not None:
                    raise self._exc
                return self._value
            if deadline is None:
                wait = _POLL_SLICE_SECONDS
            else:
                wait = min(_POLL_SLICE_SECONDS, deadline - time.monotonic())
                if wait <= 0:
                    raise TimeoutError(f"DB job exceeded {timeout}s")
            self._event.wait(wait)


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
    """Single native DB lane whose waits yield the gevent event loop.

    Hand-rolled instead of gevent.threadpool.ThreadPool: the pool's
    per-task machinery (slot semaphore, per-task async watchers, on-demand
    workers) intermittently strands a submitted job until the NEXT
    submission arrives — reproduced on gevent 24.11.1 AND 26.7.0, and the
    wedge can sit in spawn() itself (an untimed semaphore acquire), where
    no downstream timeout or nudge can see it. Users saw the Table view
    hang 10-45s+ until any other request happened by.

    This lane has nothing equivalent to wedge: submission is a nonblocking
    put to a C-level queue, the worker threads are permanent, completions
    ride ONE persistent async watcher shared by all jobs, and waiters poll
    in short slices (see _POLL_SLICE_SECONDS) so even a missed wakeup
    costs half a second, not an unbounded stall.
    """

    mode = 'gevent'

    def __init__(self, workers: int = 1):
        from gevent import get_hub, monkey

        self._workers = max(1, workers)
        self._tasks = _NativeSimpleQueue()
        self._completed = collections.deque()
        self._closed = False
        self._joined = False
        # Makes submit's closed-check-and-put atomic against shutdown's
        # sentinels: without it, a job enqueued between the check and the
        # put could land behind a sentinel and never run, leaving its
        # waiter polling until the full request timeout.
        self._close_lock = monkey.get_original('_thread', 'allocate_lock')()
        # Each worker drops a token here on exit; shutdown(wait=True) joins
        # on them (raw start_new_thread gives us no join handle).
        self._exited = _NativeSimpleQueue()
        self._watcher = get_hub().loop.async_()
        self._watcher.start(self._deliver_completions)

        # A real OS thread: under patch_all, threading.Thread would give us
        # a greenlet, which cannot host blocking sqlite3 work.
        start_new_thread = monkey.get_original('_thread', 'start_new_thread')
        for _ in range(self._workers):
            start_new_thread(self._worker, ())

    def submit(self, func: Callable[..., Any], *args, **kwargs) -> _LaneJob:
        job = _LaneJob()
        with self._close_lock:
            if self._closed:
                raise RuntimeError('DB executor is shut down')
            self._tasks.put((job, func, args, kwargs))
        return job

    def run(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit(func, *args, **kwargs).result()

    def _worker(self) -> None:
        # Native thread. Only plain-Python/C operations in here — no gevent
        # primitives, no logging handlers that might be patched.
        while True:
            item = self._tasks.get()
            if item is None:
                self._exited.put(None)
                return
            job, func, args, kwargs = item
            try:
                value, exc = func(*args, **kwargs), None
            except BaseException as e:  # propagate to the waiter, keep lane alive
                value, exc = None, e
            job._finish(value, exc)
            self._completed.append(job)
            try:
                # async watchers are gevent's documented thread-safe wakeup.
                self._watcher.send()
            except Exception:  # watcher closed mid-shutdown; pollers still finish
                pass

    def _deliver_completions(self) -> None:
        # Hub thread (the watcher callback). Waking every completed job in
        # one drain keeps a single watcher edge sufficient for any number
        # of completions coalesced behind it.
        while True:
            try:
                job = self._completed.popleft()
            except IndexError:
                return
            job._deliver()

    def shutdown(self, wait: bool = False) -> None:
        with self._close_lock:
            first_close = not self._closed
            self._closed = True
            if first_close:
                for _ in range(self._workers):
                    self._tasks.put(None)
            join = wait and not self._joined
            if join:
                self._joined = True
        if join:
            # Blocks the calling thread natively until every worker has
            # drained its queue and exited — teardown-only (tests deleting
            # a temp SQLite file must not race a worker mid-write).
            for _ in range(self._workers):
                self._exited.get()
        # The watcher stays started: in-flight jobs still deliver through
        # it, and closing it here races the workers' final send(). It is
        # reclaimed with the hub; reset_db_executor swaps executors rarely
        # (boot and tests), so the leak is a handful of watchers at most.


def create_db_executor(async_mode: str = 'threading', workers: int = 1):
    if async_mode == 'gevent':
        return GeventDBExecutor(workers=workers)
    return StdlibDBExecutor(workers=workers)
