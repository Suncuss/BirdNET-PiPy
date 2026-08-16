"""
Main test configuration and shared fixtures for pytest.

This file is automatically loaded by pytest and provides
shared utilities and configuration for all tests.
"""
import logging
import os
import sys

import pytest

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Pre-import config.settings so patch('config.settings.X') works in individual tests
# This must happen after sys.path is set up, before tests run
import config.settings  # noqa: F401

# Configure logging for tests
logging.basicConfig(level=logging.INFO)


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
    # Clean up any cached imports
    modules_to_remove = [m for m in sys.modules if m.startswith('core.') or m.startswith('config.') or m.startswith('model_service.')]
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
def test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv('TESTING', 'true')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    yield


# Shared test data that multiple test suites might use
TEST_BIRD_SPECIES = [
    ('American Robin', 'Turdus migratorius'),
    ('Blue Jay', 'Cyanocitta cristata'),
    ('Northern Cardinal', 'Cardinalis cardinalis'),
    ('Hooded Warbler', 'Setophaga citrina'),
]

TEST_COORDINATES = {
    'latitude': 40.7128,
    'longitude': -74.0060
}

TEST_DETECTION_PARAMS = {
    'cutoff': 0.5,
    'sensitivity': 0.75,
    'overlap': 0.25
}
