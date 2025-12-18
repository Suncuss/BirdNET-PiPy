"""
Database-specific test fixtures and configuration.
"""
import pytest
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import patch

# Import test configuration
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fixtures.test_config import TEST_DATABASE_SCHEMA


@pytest.fixture
def test_db_manager():
    """Create a DatabaseManager with temporary test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    # Patch the settings before importing
    with patch('config.settings.DATABASE_PATH', db_path):
        with patch('config.settings.DATABASE_SCHEMA', TEST_DATABASE_SCHEMA):
            from core.db import DatabaseManager
            manager = DatabaseManager(db_path=db_path)
            yield manager
    
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_detection():
    """Standard bird detection for testing."""
    return {
        'timestamp': '2024-01-15T10:30:00',
        'group_timestamp': '2024-01-15T10:30:00',
        'scientific_name': 'Turdus migratorius',
        'common_name': 'American Robin',
        'confidence': 0.95,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25
    }


@pytest.fixture
def multiple_species_data():
    """Multiple species with varying detection counts."""
    return [
        ('American Robin', 'Turdus migratorius', 10),
        ('Blue Jay', 'Cyanocitta cristata', 5),
        ('Northern Cardinal', 'Cardinalis cardinalis', 7),
        ('Hooded Warbler', 'Setophaga citrina', 1),  # Rare
    ]


@pytest.fixture
def populated_db(test_db_manager, multiple_species_data):
    """Database populated with test data."""
    base_time = datetime(2024, 1, 15, 10, 0, 0)
    
    for common, scientific, count in multiple_species_data:
        for i in range(count):
            detection = {
                'timestamp': (base_time - timedelta(hours=i*2)).isoformat(),
                'group_timestamp': (base_time - timedelta(hours=i*2)).isoformat(),
                'scientific_name': scientific,
                'common_name': common,
                'confidence': 0.75 + (i % 20) * 0.01,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)
    
    return test_db_manager