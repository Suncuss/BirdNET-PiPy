"""Locks shared between gevent greenlets and native threads must be native.

gevent's patched threading.Lock loses waiter wakeups when contended from a
native thread (the DB-lane worker): the notifier lands on a hub created for
the worker thread whose loop never runs again, and later waiters queue
behind it while the lock sits free — the "Table view stuck until a refresh
arrives" bug. These tests run in subprocesses because monkey.patch_all()
cannot be undone within the test process.
"""
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("gevent")


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True, text=True, timeout=60,
    )


def test_shared_locks_are_native_under_monkey_patching():
    """Every lock reachable from both request greenlets and the DB-lane
    worker must be the unpatched OS lock type, even under patch_all."""
    result = _run("""
        from gevent import monkey
        monkey.patch_all()
        native_type = type(monkey.get_original('_thread', 'allocate_lock')())

        import core.runtime_config as rc
        import core.auth as auth
        import core.media_access as media_access
        import core.timezone_service as tz
        import model_service.label_utils as lu
        import model_service.ebird_codes_lookup as ebird

        shared = {
            'runtime_config._settings_lock': rc._settings_lock,
            'auth._auth_config_lock': auth._auth_config_lock,
            'auth._auth_config_write_lock': auth._auth_config_write_lock,
            'media_access._secret_cache_lock': media_access._secret_cache_lock,
            'timezone_service._lock': tz._lock,
            'label_utils._loading_lock': lu._loading_lock,
            'label_utils._lang_lock': lu._lang_lock,
            'ebird_codes_lookup._loading_lock': ebird._loading_lock,
        }
        bad = [name for name, lock in shared.items()
               if not isinstance(lock, native_type)]
        assert not bad, f"patched (gevent) locks in cross-thread use: {bad}"
        print("all shared locks native")
    """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all shared locks native" in result.stdout


def test_logging_handler_locks_are_native_under_monkey_patching():
    """DB-lane jobs log from a native worker thread while request greenlets
    log per request; handlers created after patch_all get a patched RLock,
    which is the same lost-wakeup boundary — setup_logging must swap every
    handler lock (and lastResort's) for a native RLock."""
    result = _run("""
        from gevent import monkey
        monkey.patch_all()
        import logging
        from core.logging_config import setup_logging

        root = setup_logging('native-locks-test')
        native_rlock_type = type(monkey.get_original('threading', 'RLock')())

        assert root.handlers, "setup_logging attached no handlers"
        bad = [type(h).__name__ for h in root.handlers
               if not isinstance(h.lock, native_rlock_type)]
        assert not bad, f"handlers with patched locks: {bad}"
        assert isinstance(logging.lastResort.lock, native_rlock_type), \\
            "logging.lastResort still carries a patched lock"
        print("all handler locks native")
    """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all handler locks native" in result.stdout


# The forced interleaving that reproduces the gevent bug: a native worker
# thread contends on the lock while the main thread holds it, then a fresh
# greenlet tries to acquire after the lock is free.
_INTERLEAVING = """
    from gevent import monkey
    monkey.patch_all()
    import time
    import gevent
    try:
        from _queue import SimpleQueue as NativeQueue
    except ImportError:
        from queue import SimpleQueue as NativeQueue
    start_new_thread = monkey.get_original('_thread', 'start_new_thread')
    native_sleep = monkey.get_original('time', 'sleep')

    lock = {LOCK_EXPR}
    tasks = NativeQueue()

    def worker():
        while True:
            item = tasks.get()
            if item is None:
                return
            lock.acquire(); native_sleep(item); lock.release()

    start_new_thread(worker, ())
    # main holds the lock while the worker contends on it from its thread
    lock.acquire(); tasks.put(0.4); gevent.sleep(0.2); lock.release()
    gevent.sleep(0.1)

    # the lock is free once the worker finishes; a new greenlet acquires
    res = {}
    def g2():
        t0 = time.monotonic(); lock.acquire()
        res['dt'] = time.monotonic() - t0
        lock.release()
    gb = gevent.spawn(g2); gb.join(timeout=2)
    tasks.put(None)
    print('acquired in', res.get('dt')) if 'dt' in res else print('STALLED')
"""


def test_native_lock_survives_cross_thread_contention():
    """core.native_lock's lock must not stall in the interleaving that
    wedges gevent's patched lock."""
    result = _run(_INTERLEAVING.replace(
        "{LOCK_EXPR}",
        "__import__('core.native_lock', fromlist=['native_lock']).native_lock()"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "acquired in" in result.stdout, result.stdout + result.stderr


def test_patched_lock_still_exhibits_the_gevent_bug():
    """The patched lock STALLS in the same interleaving on the pinned gevent.
    If this test ever fails, gevent fixed the lost-wakeup bug upstream —
    the native-lock workaround can then be reconsidered (do not delete it
    without re-validating the Table-view stall repro)."""
    result = _run(_INTERLEAVING.replace(
        "{LOCK_EXPR}", "__import__('threading').Lock()"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "STALLED" in result.stdout, (
        "patched lock no longer stalls — gevent may have fixed the "
        "lost-wakeup bug; re-evaluate the native-lock workaround\n"
        + result.stdout)


def test_no_unannotated_patched_locks_in_api_reachable_code():
    """Tripwire for the next regression of the class this file exists for:
    a bare threading.Lock()/RLock() in code the API process can reach must
    either be a native lock (if DB-lane worker code can ever take it) or
    carry an explicit `# hub-only: <why>` annotation. core/native_lock.py
    is the sanctioned factory and is skipped; `# native-fallback` marks a
    factory's no-gevent branch."""
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    targets = [p for p in (backend / 'core').rglob('*.py')
               if p.name != 'native_lock.py']
    # model_service modules importable from core run in the API process too;
    # the rest of model_service only runs in the unpatched model container.
    targets += [backend / 'model_service' / 'label_utils.py',
                backend / 'model_service' / 'ebird_codes_lookup.py']

    pattern = re.compile(r'\b(?:threading\.)?R?Lock\(\)')
    violations = []
    for path in targets:
        for lineno, line in enumerate(
                path.read_text(encoding='utf-8').splitlines(), 1):
            code = line.split('#', 1)[0]
            if not pattern.search(code):
                continue
            if 'hub-only' in line or 'native-fallback' in line:
                continue
            violations.append(
                f'{path.relative_to(backend)}:{lineno}: {line.strip()}')

    assert not violations, (
        'bare patched-lock instantiation in API-reachable code — use '
        'core.native_lock if DB-lane worker code can ever take it, or '
        'annotate `# hub-only: <why>` after checking it cannot:\n'
        + '\n'.join(violations))
