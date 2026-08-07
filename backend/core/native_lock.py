"""Native (unpatched) locks for state shared with real OS threads.

gevent's monkey-patched ``threading.Lock`` can lose waiter wakeups when the
lock is contended from a native thread (our DB-lane worker): the semaphore's
notifier gets scheduled on a hub created for the worker thread, whose loop
never iterates once the worker goes back to waiting on its task queue, and
every later waiter queues behind that dead notifier. The lock then sits
*free* while request greenlets sleep on it — until an unrelated
acquire/release from the main thread happens to re-run notification
processing. Reproduced deterministically on gevent 24.11.1 and 26.7.0; this
was the "Table view stuck until a refresh arrives" bug.

Therefore: any lock taken both from hub greenlets (request handlers) and
from DB-lane worker code (the single-flight cache builders) must be a real
OS lock. That is only safe when every critical section is non-yielding
(plain file I/O and CPU work) — a native lock blocks the whole event loop
while contended, so never hold one across socket I/O, gevent primitives, or
anything else that switches greenlets.
"""
from __future__ import annotations


def native_lock():
    """A real OS lock, immune to gevent monkey-patching."""
    try:
        from gevent import monkey
        return monkey.get_original('_thread', 'allocate_lock')()
    except ImportError:  # gevent absent (plain-threading environments)
        import threading
        return threading.Lock()


def native_rlock():
    """A real OS re-entrant lock, immune to gevent monkey-patching.

    For logging handlers: a formatter can itself log (or re-enter through
    the timezone/settings caches), so handler locks must stay re-entrant.
    """
    try:
        from gevent import monkey
        return monkey.get_original('threading', 'RLock')()
    except ImportError:
        import threading
        return threading.RLock()
