"""BirdNET-Pi database migration module.

Handles migration of bird detection data from BirdNET-Pi's birds.db format
to BirdNET-PiPy's detections table format.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from core.logging_config import get_logger

logger = get_logger(__name__)

# Global storage for migration progress, keyed by temp_path
_migration_progress = {}
_progress_lock = threading.Lock()


def get_migration_progress(temp_path):
    """Get current progress for a migration.

    Args:
        temp_path: Path to the temp file (used as migration ID)

    Returns:
        dict: Progress info or None if not found
    """
    with _progress_lock:
        progress = _migration_progress.get(temp_path)
        return progress.copy() if progress else None


def set_migration_progress(temp_path, progress):
    """Update progress for a migration.

    Args:
        temp_path: Path to the temp file (used as migration ID)
        progress: dict with progress info
    """
    with _progress_lock:
        _migration_progress[temp_path] = progress


def clear_migration_progress(temp_path):
    """Clear progress for a completed migration.

    Args:
        temp_path: Path to the temp file (used as migration ID)
    """
    with _progress_lock:
        _migration_progress.pop(temp_path, None)


def start_migration_if_not_running(temp_path, total_records):
    """Atomically check if migration can start and initialize progress.

    Args:
        temp_path: Path to the temporary database file (used as migration ID)
        total_records: Total number of records to import

    Returns:
        tuple: (can_start: bool, running_id: str or None)
               - (True, None) if migration can start
               - (False, existing_id) if another migration is already running
    """
    with _progress_lock:
        # Check if ANY migration is currently running (not just this ID)
        for existing_id, existing in _migration_progress.items():
            if existing.get('status') in ('starting', 'loading', 'running'):
                return False, existing_id

        _migration_progress[temp_path] = {
            'status': 'starting',
            'processed': 0,
            'total': total_records,
            'imported': 0,
            'skipped': 0,
            'errors': 0
        }
        return True, None


class BirdNETPiMigrator:
    """Migrates bird detections from BirdNET-Pi database format to BirdNET-PiPy.

    BirdNET-Pi schema (source):
        Date, Time, Sci_Name, Com_Name, Confidence, Lat, Lon, Cutoff, Week, Sens, Overlap, File_Name

    BirdNET-PiPy schema (target):
        timestamp, group_timestamp, scientific_name, common_name, confidence,
        latitude, longitude, cutoff, sensitivity, overlap, week, extra
    """

    # Required columns in BirdNET-Pi database
    EXPECTED_COLUMNS = {
        'Date', 'Time', 'Sci_Name', 'Com_Name', 'Confidence',
        'Lat', 'Lon', 'Cutoff', 'Week', 'Sens', 'Overlap', 'File_Name'
    }

    def __init__(self, db_manager):
        """Initialize migrator with target database manager.

        Args:
            db_manager: DatabaseManager instance for the target database
        """
        self.db_manager = db_manager

    @contextmanager
    def _get_source_connection(self, source_path):
        """Get a connection to the source BirdNET-Pi database.

        Args:
            source_path: Path to the BirdNET-Pi birds.db file

        Yields:
            sqlite3.Connection with row_factory set
        """
        conn = sqlite3.connect(source_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def validate_source_database(self, source_path):
        """Validate that the source file is a valid BirdNET-Pi database.

        Args:
            source_path: Path to the uploaded database file

        Returns:
            dict: {
                'valid': bool,
                'error': str or None,
                'record_count': int,
                'columns': list of column names
            }
        """
        result = {
            'valid': False,
            'error': None,
            'record_count': 0,
            'columns': []
        }

        # Check file exists
        if not os.path.exists(source_path):
            result['error'] = 'File not found'
            return result

        # Check file size (basic sanity check)
        file_size = os.path.getsize(source_path)
        if file_size < 100:  # Minimum SQLite file size
            result['error'] = 'File too small to be a valid SQLite database'
            return result

        try:
            with self._get_source_connection(source_path) as conn:
                cursor = conn.cursor()

                # Check if it's a valid SQLite database
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in cursor.fetchall()}

                if 'detections' not in tables:
                    result['error'] = 'Database does not contain a "detections" table'
                    return result

                # Get column names
                cursor.execute("PRAGMA table_info(detections)")
                columns = {row[1] for row in cursor.fetchall()}
                result['columns'] = list(columns)

                # Check for required columns
                missing_columns = self.EXPECTED_COLUMNS - columns
                if missing_columns:
                    result['error'] = f'Missing required columns: {", ".join(sorted(missing_columns))}'
                    return result

                # Get record count
                cursor.execute("SELECT COUNT(*) FROM detections")
                result['record_count'] = cursor.fetchone()[0]

                result['valid'] = True
                logger.info("Source database validated", extra={
                    'path': source_path,
                    'record_count': result['record_count'],
                    'columns': len(columns)
                })

        except sqlite3.DatabaseError as e:
            result['error'] = f'Invalid SQLite database: {str(e)}'
        except Exception as e:
            result['error'] = f'Error validating database: {str(e)}'
            logger.error("Database validation error", extra={'error': str(e)}, exc_info=True)

        return result

    def get_preview(self, source_path, limit=10):
        """Get a preview of records from the source database.

        Args:
            source_path: Path to the BirdNET-Pi database
            limit: Maximum number of records to return

        Returns:
            list: Sample records transformed to target format
        """
        preview = []

        try:
            with self._get_source_connection(source_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT Date, Time, Sci_Name, Com_Name, Confidence,
                           Lat, Lon, Cutoff, Sens, Overlap, File_Name
                    FROM detections
                    ORDER BY Date DESC, Time DESC
                    LIMIT ?
                """, (limit,))

                for row in cursor.fetchall():
                    transformed = self._transform_record(dict(row))
                    if transformed:
                        preview.append(transformed)

        except Exception as e:
            logger.error("Error getting preview", extra={'error': str(e)}, exc_info=True)

        return preview

    def migrate(self, source_path, skip_duplicates=True, temp_path=None, total_records=None):
        """Migrate all records from source database to target.

        Args:
            source_path: Path to the BirdNET-Pi database
            skip_duplicates: If True, skip records that already exist in target
            temp_path: Path used as migration ID for progress tracking
            total_records: Optional total record count for progress calculation

        Returns:
            dict: {
                'imported': int,
                'skipped': int,
                'errors': int,
                'error_details': list of error messages
            }
        """
        result = {
            'imported': 0,
            'skipped': 0,
            'errors': 0,
            'error_details': []
        }

        def update_progress(status='running'):
            """Update progress if temp_path is provided."""
            if temp_path:
                processed = result['imported'] + result['skipped'] + result['errors']
                set_migration_progress(temp_path, {
                    'status': status,
                    'processed': processed,
                    'total': total_records or 0,
                    'imported': result['imported'],
                    'skipped': result['skipped'],
                    'errors': result['errors']
                })

        try:
            # Initial progress update
            update_progress('loading')

            # Pre-load existing records into memory for fast duplicate checking
            existing_keys = set()
            if skip_duplicates:
                existing_keys = self._load_existing_keys()
                logger.info("Loaded existing records for duplicate detection", extra={
                    'count': len(existing_keys)
                })

            update_progress('running')

            with self._get_source_connection(source_path) as source_conn:
                source_cursor = source_conn.cursor()
                source_cursor.execute("""
                    SELECT Date, Time, Sci_Name, Com_Name, Confidence,
                           Lat, Lon, Cutoff, Sens, Overlap, File_Name
                    FROM detections
                    ORDER BY Date ASC, Time ASC
                """)

                # Process in batches for efficiency
                batch_size = 500
                batch = []
                progress_update_interval = 1000  # Update progress every N records

                for row in source_cursor:
                    record = dict(row)
                    transformed = self._transform_record(record)

                    if not transformed:
                        result['errors'] += 1
                        if len(result['error_details']) < 10:
                            result['error_details'].append(
                                f"Failed to transform record: {record.get('Date')} {record.get('Time')} - {record.get('Com_Name')}"
                            )
                        continue

                    # Check for duplicates using in-memory set
                    if skip_duplicates:
                        key = self._make_record_key(transformed)
                        if key in existing_keys:
                            result['skipped'] += 1
                            # Update progress periodically even for skipped records
                            if (result['imported'] + result['skipped']) % progress_update_interval == 0:
                                update_progress()
                            continue
                        # Add to set to prevent duplicates within the import
                        existing_keys.add(key)

                    batch.append(transformed)

                    # Insert batch when full
                    if len(batch) >= batch_size:
                        imported, errors = self._insert_batch(batch)
                        result['imported'] += imported
                        result['errors'] += errors
                        batch = []
                        update_progress()

                # Insert remaining records
                if batch:
                    imported, errors = self._insert_batch(batch)
                    result['imported'] += imported
                    result['errors'] += errors

            # Final progress update
            update_progress('completed')

            logger.info("Migration completed", extra={
                'imported': result['imported'],
                'skipped': result['skipped'],
                'errors': result['errors']
            })

        except Exception as e:
            logger.error("Migration failed", extra={'error': str(e)}, exc_info=True)
            result['error_details'].append(f"Migration error: {str(e)}")
            if temp_path:
                set_migration_progress(temp_path, {
                    'status': 'failed',
                    'error': str(e),
                    'imported': result['imported'],
                    'skipped': result['skipped'],
                    'errors': result['errors']
                })

        return result

    def _load_existing_keys(self):
        """Load all existing record keys into memory for fast duplicate checking.

        Returns:
            set: Set of (timestamp, scientific_name, confidence_rounded) tuples
        """
        keys = set()
        try:
            with self.db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT timestamp, scientific_name, confidence
                    FROM detections
                """)
                for row in cursor.fetchall():
                    # Round confidence to 4 decimal places for comparison
                    key = (row[0], row[1], round(row[2], 4))
                    keys.add(key)
        except Exception as e:
            logger.warning("Failed to load existing keys", extra={'error': str(e)})
        return keys

    def _make_record_key(self, record):
        """Create a key tuple for duplicate detection.

        Args:
            record: Transformed record dict

        Returns:
            tuple: (timestamp, scientific_name, confidence_rounded)
        """
        return (
            record['timestamp'],
            record['scientific_name'],
            round(record['confidence'], 4)
        )

    def _transform_record(self, source_record):
        """Transform a BirdNET-Pi record to BirdNET-PiPy format.

        Args:
            source_record: dict with BirdNET-Pi column names

        Returns:
            dict: Transformed record in BirdNET-PiPy format, or None if invalid
        """
        try:
            timestamp = self._combine_datetime(
                source_record.get('Date'),
                source_record.get('Time')
            )

            if not timestamp:
                return None

            # Build extra field with original file name
            extra = {}
            if source_record.get('File_Name'):
                extra['original_file_name'] = source_record['File_Name']

            return {
                'timestamp': timestamp,
                'group_timestamp': timestamp,  # Same as timestamp for migrated records
                'scientific_name': source_record.get('Sci_Name', ''),
                'common_name': source_record.get('Com_Name', ''),
                'confidence': float(source_record.get('Confidence', 0)),
                'latitude': float(source_record.get('Lat', 0)) if source_record.get('Lat') else None,
                'longitude': float(source_record.get('Lon', 0)) if source_record.get('Lon') else None,
                'cutoff': float(source_record.get('Cutoff', 0)) if source_record.get('Cutoff') else None,
                'sensitivity': float(source_record.get('Sens', 0)) if source_record.get('Sens') else None,
                'overlap': float(source_record.get('Overlap', 0)) if source_record.get('Overlap') is not None else None,
                'extra': extra
            }
        except (ValueError, TypeError) as e:
            logger.warning("Failed to transform record", extra={
                'error': str(e),
                'record': source_record
            })
            return None

    def _combine_datetime(self, date_str, time_str):
        """Combine BirdNET-Pi date and time strings into ISO 8601 timestamp.

        Args:
            date_str: Date in YYYY-MM-DD format
            time_str: Time in HH:MM:SS format

        Returns:
            str: ISO 8601 timestamp or None if invalid
        """
        if not date_str or not time_str:
            return None

        try:
            # Handle various date formats
            date_str = str(date_str).strip()
            time_str = str(time_str).strip()

            # Try ISO format first (YYYY-MM-DD)
            dt = datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                # Try alternative format (MM/DD/YYYY)
                dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %H:%M:%S")
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return None

    def _insert_batch(self, records):
        """Insert a batch of records into the target database.

        Uses executemany for efficient bulk insertion with a single transaction.

        Args:
            records: list of transformed record dicts

        Returns:
            tuple: (imported_count, error_count)
        """
        if not records:
            return 0, 0

        # Prepare data for batch insert
        batch_data = []
        for record in records:
            extra = record.get('extra', {})
            if extra is None:
                extra = {}
            if isinstance(extra, dict):
                extra = json.dumps(extra)

            batch_data.append((
                record['timestamp'],
                record['group_timestamp'],
                record['scientific_name'],
                record['common_name'],
                record['confidence'],
                record['latitude'],
                record['longitude'],
                record['cutoff'],
                record['sensitivity'],
                record['overlap'],
                extra
            ))

        query = """
        INSERT INTO detections (timestamp, group_timestamp, scientific_name, common_name, confidence,
                                latitude, longitude, cutoff, sensitivity, overlap, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        try:
            with self.db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(query, batch_data)
                conn.commit()
                return len(records), 0
        except Exception as e:
            logger.error("Batch insert failed", extra={
                'error': str(e),
                'batch_size': len(records)
            })
            return 0, len(records)
