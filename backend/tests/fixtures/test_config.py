"""
Test configuration for database testing.
This module provides test-specific settings that override production settings.
"""
import os
import tempfile

from config.settings import DATABASE_SCHEMA

# Create a temporary directory for test databases
TEST_DATA_DIR = tempfile.mkdtemp(prefix='birdnet_test_')
TEST_DB_DIR = os.path.join(TEST_DATA_DIR, 'db')
os.makedirs(TEST_DB_DIR, exist_ok=True)

# Test database path
TEST_DATABASE_PATH = os.path.join(TEST_DB_DIR, 'test_birds.db')

# The production schema, aliased rather than copied: a hand-maintained copy
# drifts (it had already lost several production indexes, so tests exercised
# different query plans than production).
TEST_DATABASE_SCHEMA = DATABASE_SCHEMA

def cleanup_test_data():
    """Clean up test data directory."""
    import shutil
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR)
