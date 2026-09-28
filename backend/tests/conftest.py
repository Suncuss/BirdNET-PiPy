"""
Main test configuration and shared fixtures for pytest.

This file is automatically loaded by pytest and provides
shared utilities and configuration for all tests.
"""
import logging
import os
import sys

import pytest

# Pre-import config.settings so patch('config.settings.X') works in individual tests
# (pytest.ini's pythonpath puts the backend on sys.path before this runs)
import config.settings  # noqa: F401

# Configure logging for tests
logging.basicConfig(level=logging.INFO)


def _is_tmpfs_mount(path):
    try:
        with open('/proc/mounts') as f:
            return any(fields[1] == path and fields[2] == 'tmpfs'
                       for fields in (line.split() for line in f))
    except OSError:
        return False


def pytest_sessionstart(session):
    """Refuse to run unless BASE_DIR/data is a throwaway tmpfs.

    Every data path is hard-wired under it and modules open the DB, logs and
    flags there at import time, so on a bind-mounted real folder the suite
    would write into it and read whatever settings it holds. docker-test.sh
    mounts a fresh tmpfs there. Runs before collection imports anything.
    """
    data_dir = os.path.join(config.settings.BASE_DIR, 'data')
    if not _is_tmpfs_mount(data_dir):
        pytest.exit(
            f"{data_dir} is not a throwaway tmpfs, so the tests would read and "
            f"write whatever data folder is mounted there. Run them through "
            f"./docker-test.sh (e.g. ./docker-test.sh tests/api/), or add "
            f"--tmpfs {data_dir}:rw,mode=1777 to your own docker run.",
            returncode=pytest.ExitCode.USAGE_ERROR)


@pytest.fixture
def test_db_manager():
    """DatabaseManager on a temporary database — the shared real-SQLite
    fixture for DB-touching tests."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    from core.db import DatabaseManager
    manager = DatabaseManager(db_path=db_path)
    yield manager

    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Hash passwords at bcrypt's minimum cost in tests.

    The production cost (12) takes ~0.3s per hash or check on a Pi 5, and
    the auth tests do hundreds of them: a quarter of the suite's runtime.
    Hashes made at cost 4 are also checked at cost 4, in about 1ms.
    """
    import bcrypt
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, 'gensalt',
                        lambda rounds=12, prefix=b'2b': real_gensalt(4, prefix))


# Survive reset_imports: label_utils caches the parsed species table, static
# data that takes ~0.4s to rebuild, and rebuilding it for every test that
# touched a species name was a quarter of the suite's runtime. Tests that need
# a cold cache call clear_species_cache().
_PERSISTENT_MODULES = {'model_service.label_utils'}


@pytest.fixture(autouse=True)
def reset_imports():
    """Reset imports between tests to avoid state pollution.

    NOTE: the bare packages ('core', 'config', 'model_service') survive
    deliberately — popping them trips import-time side effects suite-wide.
    The cost: a surviving package's stale submodule attributes satisfy
    `from core import X` in the next test's re-import, splitting module
    state and exception-class identity between generations. Modules whose
    identity must match across the import graph therefore use direct
    `import core.x as x` (sys.modules-resolved) instead of the package-attr
    form — see core/db.py — and tests patch state via the live instance
    the code under test actually holds.
    """
    yield
    # The next test re-imports core.*, which builds fresh executors; shut
    # down this generation's native workers first, or every test leaks an
    # idle thread — hundreds per run, enough to exhaust docker-test.sh's
    # address-space cap ("can't start new thread", failed mmaps).
    for module_name, attr in (('core.api_infra', 'db_executor'),
                              ('core.export_jobs', '_writer_lane')):
        executor = getattr(sys.modules.get(module_name), attr, None)
        if hasattr(executor, 'shutdown'):
            executor.shutdown(wait=False)
    # Clean up any cached imports
    modules_to_remove = [m for m in sys.modules
                         if m.startswith(('core.', 'config.', 'model_service.'))
                         and m not in _PERSISTENT_MODULES]
    for module in modules_to_remove:
        sys.modules.pop(module, None)


@pytest.fixture(autouse=True)
def isolate_internal_secret(tmp_path):
    """Redirect the internal broadcast secret to a tmp file.

    docker-test.sh mounts the repo at /app, so the default secret path is the
    LIVE data/config dir; without this, any broadcast in a test would write a
    real internal_secret there. Also resets the in-process cache so each test
    gets a fresh, isolated secret.
    """
    from unittest.mock import patch

    import core.internal_auth as internal_auth
    with patch.object(internal_auth, '_SECRET_FILE', str(tmp_path / 'internal_secret')), \
         patch.object(internal_auth, '_cached_secret', None):
        yield


@pytest.fixture(autouse=True)
def isolate_model_startup_status(tmp_path, monkeypatch):
    """Keep model startup diagnostics out of the mounted development data."""
    from config import settings

    monkeypatch.setattr(
        settings,
        "MODEL_STARTUP_STATUS_PATH",
        str(tmp_path / "model_service_startup.json"),
    )


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A private user_settings.json path plus the runtime reader bound to it."""
    import config.settings as config_settings
    import core.runtime_config as runtime
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(config_settings, 'USER_SETTINGS_PATH', str(path))
    monkeypatch.setattr(runtime, 'USER_SETTINGS_PATH', str(path))
    return path, runtime
