"""
Main test configuration and shared fixtures for pytest.

This file is automatically loaded by pytest and provides
shared utilities and configuration for all tests.
"""
import pytest
import sys
import os
import logging

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging for tests
logging.basicConfig(level=logging.INFO)


@pytest.fixture(autouse=True)
def reset_imports():
    """Reset imports between tests to avoid state pollution."""
    yield
    # Clean up any cached imports
    modules_to_remove = [m for m in sys.modules if m.startswith('core.') or m.startswith('config.') or m.startswith('model_service.')]
    for module in modules_to_remove:
        sys.modules.pop(module, None)


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