"""Tests for BirdNET-Pi migration API endpoints."""

import os
import tempfile
import sqlite3
import pytest
import json
import io
import time
from unittest.mock import patch, Mock


def wait_for_migration(api_client, migration_id, timeout=30):
    """Wait for a migration to complete by polling the status endpoint.

    Args:
        api_client: Flask test client
        migration_id: The migration ID to poll for
        timeout: Maximum seconds to wait

    Returns:
        dict: Final status response
    """
    start = time.time()
    while time.time() - start < timeout:
        response = api_client.get(
            '/api/migration/status',
            query_string={'migration_id': migration_id}
        )
        if response.status_code != 200:
            time.sleep(0.1)
            continue

        data = response.get_json()
        if data.get('status') in ('completed', 'failed'):
            return data

        time.sleep(0.1)

    raise TimeoutError(f"Migration did not complete within {timeout} seconds")


def create_birdnetpi_database(db_path, records=None):
    """Create a mock BirdNET-Pi database for testing.

    Args:
        db_path: Path to create the database
        records: List of records to insert (uses defaults if None)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create BirdNET-Pi schema
    cursor.execute("""
        CREATE TABLE detections (
            Date TEXT,
            Time TEXT,
            Sci_Name TEXT,
            Com_Name TEXT,
            Confidence REAL,
            Lat REAL,
            Lon REAL,
            Cutoff REAL,
            Week INTEGER,
            Sens REAL,
            Overlap REAL,
            File_Name TEXT
        )
    """)

    if records is None:
        # Insert sample records
        records = [
            ('2024-01-15', '10:30:00', 'Turdus migratorius', 'American Robin', 0.85, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, 'robin_2024-01-15.wav'),
            ('2024-01-15', '11:15:00', 'Cyanocitta cristata', 'Blue Jay', 0.90, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, 'bluejay_2024-01-15.wav'),
            ('2024-01-16', '08:45:00', 'Cardinalis cardinalis', 'Northern Cardinal', 0.78, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, 'cardinal_2024-01-16.wav'),
        ]

    for record in records:
        cursor.execute("""
            INSERT INTO detections
            (Date, Time, Sci_Name, Com_Name, Confidence, Lat, Lon, Cutoff, Week, Sens, Overlap, File_Name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, record)

    conn.commit()
    conn.close()


class TestMigrationValidateEndpoint:
    """Tests for /api/migration/validate endpoint."""

    def test_validate_no_file(self, api_client):
        """Test validation fails when no file is uploaded."""
        response = api_client.post('/api/migration/validate')
        assert response.status_code == 400
        assert 'No file uploaded' in response.get_json()['error']

    def test_validate_empty_filename(self, api_client):
        """Test validation fails with empty filename."""
        response = api_client.post(
            '/api/migration/validate',
            data={'file': (io.BytesIO(b''), '')},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'No file selected' in response.get_json()['error']

    def test_validate_wrong_extension(self, api_client):
        """Test validation fails with non-.db file."""
        response = api_client.post(
            '/api/migration/validate',
            data={'file': (io.BytesIO(b'test'), 'test.txt')},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert '.db' in response.get_json()['error']

    def test_validate_invalid_sqlite(self, api_client):
        """Test validation fails with invalid SQLite file."""
        response = api_client.post(
            '/api/migration/validate',
            data={'file': (io.BytesIO(b'not a sqlite database'), 'birds.db')},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        # Should get an error about invalid database
        assert 'error' in response.get_json()

    def test_validate_missing_table(self, api_client):
        """Test validation fails when detections table is missing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create empty SQLite database without detections table
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE other_table (id INTEGER)")
            conn.close()

            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )

            assert response.status_code == 400
            assert 'detections' in response.get_json()['error'].lower()
        finally:
            os.unlink(db_path)

    def test_validate_missing_columns(self, api_client):
        """Test validation fails when required columns are missing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create detections table with missing columns
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE detections (
                    Date TEXT,
                    Time TEXT,
                    Sci_Name TEXT
                )
            """)
            conn.close()

            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )

            assert response.status_code == 400
            assert 'Missing required columns' in response.get_json()['error']
        finally:
            os.unlink(db_path)

    def test_validate_valid_database(self, api_client):
        """Test validation succeeds with valid BirdNET-Pi database."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )

            assert response.status_code == 200
            data = response.get_json()
            assert data['valid'] is True
            assert data['record_count'] == 3
            assert 'preview' in data
            assert len(data['preview']) <= 10
        finally:
            os.unlink(db_path)

    def test_validate_preview_contains_transformed_records(self, api_client):
        """Test that preview records are in BirdNET-PiPy format."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )

            assert response.status_code == 200
            data = response.get_json()

            # Check preview record format
            assert len(data['preview']) > 0
            preview_record = data['preview'][0]

            # Should have BirdNET-PiPy fields
            assert 'timestamp' in preview_record
            assert 'scientific_name' in preview_record
            assert 'common_name' in preview_record
            assert 'confidence' in preview_record

            # Should NOT have BirdNET-Pi fields
            assert 'Date' not in preview_record
            assert 'Time' not in preview_record
            assert 'Sci_Name' not in preview_record
        finally:
            os.unlink(db_path)


class TestMigrationImportEndpoint:
    """Tests for /api/migration/import endpoint."""

    def test_import_without_validation(self, api_client):
        """Test import fails if no file was validated first."""
        response = api_client.post('/api/migration/import')
        assert response.status_code == 400
        assert 'validated file' in response.get_json()['error'].lower()

    def test_import_after_validation(self, api_client, real_db_manager):
        """Test successful import after validation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            # First validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Then import (now starts in background)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200

            data = response.get_json()
            assert data['status'] in ('started', 'already_running')
            migration_id = data['migration_id']

            # Wait for completion
            result = wait_for_migration(api_client, migration_id)
            assert result['status'] == 'completed'
            assert result['imported'] == 3
            assert result['skipped'] == 0
            assert result['errors'] == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_import_skips_duplicates(self, api_client, real_db_manager):
        """Test that duplicate records are skipped by default."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Insert a record that will be in the source database
            real_db_manager.insert_detection({
                'timestamp': '2024-01-15T10:30:00',
                'group_timestamp': '2024-01-15T10:30:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

            create_birdnetpi_database(db_path)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Import (default skip_duplicates=True)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200

            data = response.get_json()
            migration_id = data['migration_id']

            # Wait for completion
            result = wait_for_migration(api_client, migration_id)
            assert result['status'] == 'completed'
            assert result['imported'] == 2  # 3 total - 1 duplicate
            assert result['skipped'] == 1
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_import_with_skip_duplicates_false(self, api_client, real_db_manager):
        """Test that duplicates are imported when skip_duplicates is False."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Insert a record that will be in the source database
            real_db_manager.insert_detection({
                'timestamp': '2024-01-15T10:30:00',
                'group_timestamp': '2024-01-15T10:30:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

            create_birdnetpi_database(db_path)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Import with skip_duplicates=False
            response = api_client.post(
                '/api/migration/import',
                data=json.dumps({'skip_duplicates': False}),
                content_type='application/json'
            )
            assert response.status_code == 200

            data = response.get_json()
            migration_id = data['migration_id']

            # Wait for completion
            result = wait_for_migration(api_client, migration_id)
            assert result['status'] == 'completed'
            assert result['imported'] == 3  # All records including duplicate
            assert result['skipped'] == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_import_cleans_up_temp_file(self, api_client, real_db_manager):
        """Test that temp file is cleaned up after import."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Import
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200

            # Second import should fail (temp file cleaned up)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 400
            assert 'validated file' in response.get_json()['error'].lower()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_race_protection_prevents_duplicate_migrations(self, api_client, real_db_manager):
        """Test that the race protection prevents duplicate migrations for the same temp_path."""
        from core.migration import (
            start_migration_if_not_running,
            clear_migration_progress
        )

        temp_path = '/fake/temp/path/for/testing.db'

        try:
            # First call should succeed (returns True = can start)
            can_start1 = start_migration_if_not_running(temp_path, 100)
            assert can_start1 is True

            # Second call with same temp_path should return False (already running)
            can_start2 = start_migration_if_not_running(temp_path, 100)
            assert can_start2 is False

            # Third call should also fail
            can_start3 = start_migration_if_not_running(temp_path, 100)
            assert can_start3 is False

        finally:
            # Clean up
            clear_migration_progress(temp_path)

        # After cleanup, should be able to start again
        can_start4 = start_migration_if_not_running(temp_path, 100)
        assert can_start4 is True
        clear_migration_progress(temp_path)


class TestMigrationCancelEndpoint:
    """Tests for /api/migration/cancel endpoint."""

    def test_cancel_without_validation(self, api_client):
        """Test cancel succeeds even without prior validation."""
        response = api_client.post('/api/migration/cancel')
        assert response.status_code == 200
        assert response.get_json()['status'] == 'ok'

    def test_cancel_after_validation(self, api_client):
        """Test cancel cleans up temp file after validation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Cancel
            response = api_client.post('/api/migration/cancel')
            assert response.status_code == 200
            assert response.get_json()['status'] == 'cancelled'

            # Import should fail (temp file cleaned up)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 400
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestMigrationStatusEndpoint:
    """Tests for /api/migration/status endpoint."""

    def test_status_missing_migration_id(self, api_client):
        """Test status fails without migration_id parameter."""
        response = api_client.get('/api/migration/status')
        assert response.status_code == 400
        assert 'migration_id' in response.get_json()['error'].lower()

    def test_status_not_found(self, api_client):
        """Test status returns 404 for unknown migration_id."""
        response = api_client.get(
            '/api/migration/status',
            query_string={'migration_id': 'mig_nonexistent12345'}
        )
        assert response.status_code == 404
        assert response.get_json()['status'] == 'not_found'

    def test_status_during_import(self, api_client, real_db_manager):
        """Test status returns progress during import."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create a database with enough records to have time to poll
            records = [
                ('2024-01-15', f'10:{i:02d}:00', 'Turdus migratorius', 'American Robin',
                 0.80 + i*0.001, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, f'robin_{i}.wav')
                for i in range(50)
            ]
            create_birdnetpi_database(db_path, records)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200

            # Start import
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200
            data = response.get_json()
            migration_id = data['migration_id']

            # Check status - should find the migration
            response = api_client.get(
                '/api/migration/status',
                query_string={'migration_id': migration_id}
            )
            assert response.status_code == 200
            status = response.get_json()
            assert status['status'] in ('starting', 'loading', 'running', 'completed')

            # Wait for completion
            wait_for_migration(api_client, migration_id)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_migration_id_is_temp_path(self, api_client, real_db_manager):
        """Test that migration_id is the temp file path (protected by auth)."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path)

            with open(db_path, 'rb') as f:
                api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )

            response = api_client.post('/api/migration/import')
            data = response.get_json()
            migration_id = data['migration_id']

            # Migration ID is the temp file path (endpoints are auth-protected)
            assert migration_id.endswith('.db')

            wait_for_migration(api_client, migration_id)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestMigrationIntegration:
    """Integration tests for the full migration workflow."""

    def test_full_migration_workflow(self, api_client, real_db_manager):
        """Test complete migration workflow: validate -> import -> verify."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create source database with 5 records
            records = [
                ('2024-01-15', f'10:{i:02d}:00', 'Turdus migratorius', 'American Robin',
                 0.80 + i*0.03, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, f'robin_{i}.wav')
                for i in range(5)
            ]
            create_birdnetpi_database(db_path, records)

            # Step 1: Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200
            data = response.get_json()
            assert data['valid'] is True
            assert data['record_count'] == 5

            # Step 2: Import (starts in background)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200
            data = response.get_json()
            migration_id = data['migration_id']

            # Wait for completion
            result = wait_for_migration(api_client, migration_id)
            assert result['status'] == 'completed'
            assert result['imported'] == 5

            # Step 3: Verify records are in database
            response = api_client.get('/api/species/all')
            assert response.status_code == 200
            species = response.get_json()
            assert any(s['common_name'] == 'American Robin' for s in species)

            # Verify we can query the imported data
            response = api_client.get('/api/observations/recent')
            assert response.status_code == 200
            observations = response.get_json()
            assert len(observations) >= 5
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_migration_preserves_extra_data(self, api_client, real_db_manager):
        """Test that original file name is preserved in extra field."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            records = [
                ('2024-01-15', '10:30:00', 'Turdus migratorius', 'American Robin',
                 0.85, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, 'original_robin_file.wav'),
            ]
            create_birdnetpi_database(db_path, records)

            # Validate and import
            with open(db_path, 'rb') as f:
                api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            response = api_client.post('/api/migration/import')
            migration_id = response.get_json()['migration_id']

            # Wait for completion
            wait_for_migration(api_client, migration_id)

            # Check that extra field contains original file name
            response = api_client.get('/api/observations/latest')
            assert response.status_code == 200
            data = response.get_json()

            # The extra field should contain original_file_name
            extra = data.get('extra', {})
            assert extra.get('original_file_name') == 'original_robin_file.wav'
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_migration_handles_empty_database(self, api_client, real_db_manager):
        """Test migration handles empty source database."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            create_birdnetpi_database(db_path, records=[])

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200
            data = response.get_json()
            assert data['record_count'] == 0

            # Import (should succeed with 0 records)
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200
            data = response.get_json()
            migration_id = data['migration_id']

            # Wait for completion
            result = wait_for_migration(api_client, migration_id)
            assert result['status'] == 'completed'
            assert result['imported'] == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_large_migration(self, api_client, real_db_manager):
        """Test migration with larger dataset."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            # Create 500 records
            records = [
                ('2024-01-15', f'{(i//60):02d}:{(i%60):02d}:00', 'Turdus migratorius', 'American Robin',
                 0.70 + (i % 30) * 0.01, 40.7128, -74.0060, 0.5, 3, 0.75, 0.25, f'robin_{i}.wav')
                for i in range(500)
            ]
            create_birdnetpi_database(db_path, records)

            # Validate
            with open(db_path, 'rb') as f:
                response = api_client.post(
                    '/api/migration/validate',
                    data={'file': (f, 'birds.db')},
                    content_type='multipart/form-data'
                )
            assert response.status_code == 200
            data = response.get_json()
            assert data['record_count'] == 500

            # Import
            response = api_client.post('/api/migration/import')
            assert response.status_code == 200
            data = response.get_json()
            migration_id = data['migration_id']

            # Wait for completion (allow more time for larger dataset)
            result = wait_for_migration(api_client, migration_id, timeout=60)
            assert result['status'] == 'completed'
            assert result['imported'] == 500
            assert result['errors'] == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
