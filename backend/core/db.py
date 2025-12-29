from config.settings import DATABASE_PATH, DATABASE_SCHEMA
from core.logging_config import get_logger
from core.utils import build_detection_filenames

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import os
import time
import logging

# Create a custom logger adapter that adds a prefix to all messages
class DBLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[DB] {msg}", kwargs

# Use the existing logger hierarchy with adapter
_base_logger = get_logger(__name__)
logger = DBLoggerAdapter(_base_logger, {})

class DatabaseManager:
    
    def __init__(self, db_path=DATABASE_PATH):
        self.db_path = db_path
        self.ensure_db_directory_exists()
        self.initialize_database()
        logger.info("DatabaseManager initialized", extra={
            'database_path': self.db_path
        })

    def ensure_db_directory_exists(self):
        db_directory = os.path.dirname(self.db_path)
        if not os.path.exists(db_directory):
            os.makedirs(db_directory)    
        
    @contextmanager
    def get_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # This line ensures we get dictionaries instead of tuples
        try:
            yield conn
        finally:
            conn.close()

    def initialize_database(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript(DATABASE_SCHEMA)

            # Auto-migrate: add 'extra' column if missing (for existing databases)
            cursor.execute("PRAGMA table_info(detections)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            if 'extra' not in existing_columns:
                cursor.execute("ALTER TABLE detections ADD COLUMN extra TEXT DEFAULT '{}'")
                cursor.execute("UPDATE detections SET extra = '{}' WHERE extra IS NULL")
                logger.info("Migrated database: added 'extra' column to detections table")

            conn.commit()

    def database_exists(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detections'")
            return cursor.fetchone() is not None

    def insert_detection(self, detection):
        # Handle extra field - default to empty JSON object
        extra = detection.get('extra', {})
        if extra is None:
            extra = {}
        if isinstance(extra, dict):
            extra = json.dumps(extra)

        query = """
        INSERT INTO detections (timestamp, group_timestamp, scientific_name, common_name, confidence,
                                latitude, longitude, cutoff, sensitivity, overlap, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (
                detection['timestamp'],
                detection['group_timestamp'],
                detection['scientific_name'],
                detection['common_name'],
                detection['confidence'],
                detection['latitude'],
                detection['longitude'],
                detection['cutoff'],
                detection['sensitivity'],
                detection['overlap'],
                extra
            ))
            conn.commit()
            return cur.lastrowid
        
    def get_latest_detections(self, limit=15):
        # Use window function to get highest confidence detection per (group_timestamp, common_name)
        # Previous query used WHERE (id, confidence) IN (SELECT id, MAX(confidence) ... GROUP BY)
        # which has undefined behavior in SQLite - the non-aggregated 'id' column can return
        # an arbitrary id that doesn't match the row with MAX(confidence), causing empty results.
        query = """
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra
        FROM detections
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY group_timestamp, common_name
                    ORDER BY confidence DESC
                ) as rn
                FROM detections
            ) WHERE rn = 1
        )
        ORDER BY timestamp DESC
        LIMIT ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (limit,))
            rows = cur.fetchall()
            
            detections = []
            for row in rows:
                detection = dict(row)

                # Parse extra JSON field
                detection['extra'] = self._parse_extra(detection.get('extra'))

                # Generate standardized filenames using utility function
                filenames = build_detection_filenames(
                    detection['common_name'],
                    detection['confidence'],
                    detection['timestamp'],
                    audio_extension='mp3'
                )

                detection['bird_song_file_name'] = filenames['audio_filename']
                detection['spectrogram_file_name'] = filenames['spectrogram_filename']

                detections.append(detection)

            return detections

    def get_detections_by_date_range(self, start_date, end_date, unique=False):
        start_time = time.time()
        
        # Convert dates to ISO 8601 format
        start_date_iso = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00')
        end_date_iso = datetime.strptime(end_date, '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59')
        
        logger.debug("Fetching detections by date range", extra={
            'start_date': start_date,
            'end_date': end_date,
            'unique_only': unique
        })
        
        if unique:
            query = """
            WITH RankedDetections AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (PARTITION BY common_name ORDER BY confidence DESC, timestamp DESC) AS rn
                FROM detections
                WHERE timestamp BETWEEN ? AND ?
            )
            SELECT
                *
            FROM RankedDetections
            WHERE rn = 1
            ORDER BY timestamp DESC;
            """
        else:
            query = """
            SELECT * FROM detections
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            """
        
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            if unique:
                cur.execute(query, (start_date_iso, end_date_iso))
            else:
                cur.execute(query, (start_date_iso, end_date_iso))
            
            rows = cur.fetchall()
            results = []
            for row in rows:
                detection = dict(row)
                detection['extra'] = self._parse_extra(detection.get('extra'))
                results.append(detection)

            query_time = time.time() - start_time
            logger.debug("Date range query completed", extra={
                'results_count': len(results),
                'query_time': round(query_time, 3)
            })
            
            return results

    def get_hourly_activity(self, date=None):
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        end_of_day = start_of_day + timedelta(days=1)

        query = """
        SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
        FROM detections
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY hour
        ORDER BY hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_of_day, end_of_day))
            results = cur.fetchall()

        hourly_activity = {f"{hour:02d}": 0 for hour in range(24)}
        for row in results:
            hourly_activity[row['hour']] = row['count']

        return [{'hour': f"{hour}:00", 'count': count} for hour, count in hourly_activity.items()]
    
    def get_activity_overview(self, date=None, num_species=10):
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        end_of_day = start_of_day + timedelta(days=1)

        # Date range already logged in parent function

        query = """
        SELECT common_name, strftime('%H', timestamp) as hour, COUNT(*) as count
        FROM detections
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY common_name, hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_of_day, end_of_day))
            results = cur.fetchall()

        species_hourly_activity = {}
        for row in results:
            species = row['common_name']
            hour = row['hour']
            count = row['count']

            if species not in species_hourly_activity:
                species_hourly_activity[species] = [0] * 24

            species_hourly_activity[species][int(hour)] = count

        species_activity = [
            {
                'species': species,
                'hourlyActivity': hourly_activity,
                'totalObservations': sum(hourly_activity)
            }
            for species, hourly_activity in species_hourly_activity.items()
        ]

        species_activity.sort(key=lambda x: x['totalObservations'], reverse=True)
        
        logger.debug("Activity overview generated", extra={
            'total_species': len(species_hourly_activity),
            'returned_species': min(num_species, len(species_activity))
        })
        
        return species_activity[:min(num_species, len(species_activity))]

    def get_summary_stats(self, start_date=None):
        if start_date is None:
            start_date = datetime.min.isoformat()
        else:
            start_date = start_date.isoformat()

        end_date = datetime.now().isoformat()

        with self.get_db_connection() as conn:
            cur = conn.cursor()

            logger.debug("Calculating summary statistics", extra={
                'start_date': start_date[:10] if start_date else 'all_time',
                'end_date': end_date[:10]
            })

            # Single optimized query using CTEs (replaces 5 separate queries)
            query = """
            WITH filtered_detections AS (
                SELECT common_name, timestamp
                FROM detections
                WHERE timestamp BETWEEN ? AND ?
            ),
            counts AS (
                SELECT
                    COUNT(*) as total_observations,
                    COUNT(DISTINCT common_name) as unique_species
                FROM filtered_detections
            ),
            hourly AS (
                SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                FROM filtered_detections
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 1
            ),
            species_counts AS (
                SELECT common_name, COUNT(*) as count
                FROM filtered_detections
                GROUP BY common_name
            ),
            most_common AS (
                SELECT common_name
                FROM species_counts
                ORDER BY count DESC
                LIMIT 1
            ),
            rarest AS (
                SELECT common_name
                FROM species_counts
                ORDER BY count ASC
                LIMIT 1
            )
            SELECT
                (SELECT total_observations FROM counts) as totalObservations,
                (SELECT unique_species FROM counts) as uniqueSpecies,
                (SELECT hour FROM hourly) as mostActiveHour,
                (SELECT common_name FROM most_common) as mostCommonBird,
                (SELECT common_name FROM rarest) as rarestBird
            """

            cur.execute(query, (start_date, end_date))
            result = cur.fetchone()

            if result:
                most_active_hour = f"{result['mostActiveHour']}:00" if result['mostActiveHour'] else "N/A"
                return {
                    'totalObservations': result['totalObservations'] or 0,
                    'uniqueSpecies': result['uniqueSpecies'] or 0,
                    'mostActiveHour': most_active_hour,
                    'mostCommonBird': result['mostCommonBird'] or "N/A",
                    'rarestBird': result['rarestBird'] or "N/A"
                }

        return {
            'totalObservations': 0,
            'uniqueSpecies': 0,
            'mostActiveHour': "N/A",
            'mostCommonBird': "N/A",
            'rarestBird': "N/A"
        }

    def get_species_sightings(self, limit=10, most_frequent=True):
        # Use separate queries based on sort order (safer than f-string interpolation)
        if most_frequent:
            query = """
            WITH SpeciesCount AS (
                SELECT common_name, COUNT(*) as count
                FROM detections
                GROUP BY common_name
                ORDER BY count DESC
                LIMIT ?
            )
            SELECT d.*
            FROM detections d
            JOIN SpeciesCount sc ON d.common_name = sc.common_name
            WHERE (d.common_name, d.timestamp) IN (
                SELECT common_name, MAX(timestamp)
                FROM detections
                GROUP BY common_name
            )
            ORDER BY sc.count DESC, d.timestamp DESC
            """
        else:
            query = """
            WITH SpeciesCount AS (
                SELECT common_name, COUNT(*) as count
                FROM detections
                GROUP BY common_name
                ORDER BY count ASC
                LIMIT ?
            )
            SELECT d.*
            FROM detections d
            JOIN SpeciesCount sc ON d.common_name = sc.common_name
            WHERE (d.common_name, d.timestamp) IN (
                SELECT common_name, MAX(timestamp)
                FROM detections
                GROUP BY common_name
            )
            ORDER BY sc.count ASC, d.timestamp DESC
            """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (limit,))
            rows = cur.fetchall()
            results = []
            for row in rows:
                detection = dict(row)
                detection['extra'] = self._parse_extra(detection.get('extra'))
                results.append(detection)
            return results



    def get_bird_details(self, species_name):
        query = """
        SELECT 
            common_name,
            scientific_name,
            COUNT(*) as total_visits,
            MIN(timestamp) as first_detected,
            MAX(timestamp) as last_detected,
            AVG(confidence) as average_confidence,
            (SELECT strftime('%H:00', timestamp) 
            FROM detections d2 
            WHERE d2.common_name = d1.common_name 
            GROUP BY strftime('%H', timestamp) 
            ORDER BY COUNT(*) DESC 
            LIMIT 1) as peak_activity_time,
            CASE 
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) = 12 THEN 'Year-round'
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) >= 6 THEN 'Multi-season'
                ELSE 'Seasonal'
            END as seasonality
        FROM detections d1
        WHERE common_name = ?
        GROUP BY common_name, scientific_name
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (species_name,))
            result = cur.fetchone()
            return dict(result) if result else None


    def get_bird_recordings(self, species_name, sort='recent', limit=None):
        """
        Get recordings for a species with sorting options.

        Args:
            species_name: Bird species common name
            sort: 'recent' (timestamp DESC) or 'best' (confidence DESC)
            limit: Optional max number of records (None = all)

        Returns:
            List of recording dicts with id, timestamp, common_name, confidence,
            audio_filename, spectrogram_filename
        """
        # Use separate queries based on sort order (safer than f-string interpolation)
        # LIMIT is parameterized using -1 for unlimited (SQLite treats negative LIMIT as no limit)
        if sort == 'best':
            query = """
            SELECT id, timestamp, common_name, confidence, extra
            FROM detections
            WHERE common_name = ?
            ORDER BY confidence DESC
            LIMIT ?
            """
        else:  # default to 'recent'
            query = """
            SELECT id, timestamp, common_name, confidence, extra
            FROM detections
            WHERE common_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (species_name, limit_param))
            rows = cur.fetchall()

        recordings = []
        for row in rows:
            record = dict(row)

            # Parse extra JSON field
            record['extra'] = self._parse_extra(record.get('extra'))

            # Generate standardized filenames using utility function
            filenames = build_detection_filenames(
                record['common_name'],
                record['confidence'],
                record['timestamp'],
                audio_extension='mp3'
            )

            record['audio_filename'] = filenames['audio_filename']
            record['spectrogram_filename'] = filenames['spectrogram_filename']

            recordings.append(record)

        logger.debug("Bird recordings retrieved", extra={
            'species': species_name,
            'sort': sort,
            'limit': limit,
            'records_count': len(recordings)
        })
        return recordings
    
    def get_detection_distribution(self, species_name, view, anchor_date_str):
        import datetime
        anchor_date = datetime.datetime.strptime(anchor_date_str, '%Y-%m-%d')
        logger.debug("Getting detection distribution", extra={
            'species': species_name,
            'view': view,
            'date': anchor_date_str
        })
        
        # Initialize labels and data based on view type
        if view == 'day':
            # 24 hours for the specific day
            labels = [f"{i:02d}:00" for i in range(24)]
            data = [0] * 24
            
            query = """
            SELECT 
                strftime('%H', timestamp) as hour,
                COUNT(*) as count
            FROM detections
            WHERE common_name = ?
            AND date(timestamp) = date(?)
            GROUP BY hour
            """
            
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (species_name, anchor_date_str))
                results = cur.fetchall()
                
            for row in results:
                hour_idx = int(row['hour'])
                data[hour_idx] = row['count']
                
        elif view == 'week':
            # 7 days for the week containing the anchor date
            # Use Sunday as week start (matching JavaScript's getDay() where Sunday=0)
            # Python's weekday() returns Monday=0, so we convert: Sunday=6 -> 0, Mon=0 -> 1, etc.
            days_since_sunday = (anchor_date.weekday() + 1) % 7
            week_start = anchor_date - datetime.timedelta(days=days_since_sunday)
            labels = []
            for i in range(7):
                day = week_start + datetime.timedelta(days=i)
                labels.append(day.strftime('%a %m/%d'))
            data = [0] * 7
            
            query = """
            SELECT 
                date(timestamp) as day,
                COUNT(*) as count
            FROM detections
            WHERE common_name = ?
            AND date(timestamp) >= date(?)
            AND date(timestamp) < date(?, '+7 days')
            GROUP BY day
            """
            
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (species_name, week_start.strftime('%Y-%m-%d'), week_start.strftime('%Y-%m-%d')))
                results = cur.fetchall()
                
            for row in results:
                day_date = datetime.datetime.strptime(row['day'], '%Y-%m-%d')
                day_idx = (day_date - week_start).days
                if 0 <= day_idx < 7:
                    data[day_idx] = row['count']
                    
        elif view == 'month':
            # All days in the month
            import calendar
            year = anchor_date.year
            month = anchor_date.month
            num_days = calendar.monthrange(year, month)[1]
            labels = [str(i) for i in range(1, num_days + 1)]
            data = [0] * num_days
            
            query = """
            SELECT 
                strftime('%d', timestamp) as day,
                COUNT(*) as count
            FROM detections
            WHERE common_name = ?
            AND strftime('%Y-%m', timestamp) = ?
            GROUP BY day
            """
            
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (species_name, anchor_date.strftime('%Y-%m')))
                results = cur.fetchall()
                
            for row in results:
                day_idx = int(row['day']) - 1
                if 0 <= day_idx < num_days:
                    data[day_idx] = row['count']
                    
        elif view == '6month':
            # 6 months based on anchor date
            start_month = 1 if anchor_date.month <= 6 else 7
            labels = []
            for i in range(6):
                month_date = datetime.datetime(anchor_date.year, start_month + i, 1)
                labels.append(month_date.strftime('%b'))
            data = [0] * 6
            
            query = """
            SELECT 
                strftime('%m', timestamp) as month,
                COUNT(*) as count
            FROM detections
            WHERE common_name = ?
            AND strftime('%Y', timestamp) = ?
            AND CAST(strftime('%m', timestamp) AS INTEGER) >= ?
            AND CAST(strftime('%m', timestamp) AS INTEGER) < ?
            GROUP BY month
            """
            
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (species_name, str(anchor_date.year), start_month, start_month + 6))
                results = cur.fetchall()
                
            for row in results:
                month_idx = int(row['month']) - start_month
                if 0 <= month_idx < 6:
                    data[month_idx] = row['count']
                    
        elif view == 'year':
            # 12 months for the year
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            data = [0] * 12
            
            query = """
            SELECT 
                strftime('%m', timestamp) as month,
                COUNT(*) as count
            FROM detections
            WHERE common_name = ?
            AND strftime('%Y', timestamp) = ?
            GROUP BY month
            """
            
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (species_name, str(anchor_date.year)))
                results = cur.fetchall()
                
            for row in results:
                month_idx = int(row['month']) - 1
                if 0 <= month_idx < 12:
                    data[month_idx] = row['count']
        
        else:
            raise ValueError("Invalid view. Use 'day', 'week', 'month', '6month', or 'year'.")
            
        logger.debug("Detection distribution calculated", extra={
            'data_points': len([d for d in data if d > 0]),
            'total_detections': sum(data)
        })
        return {'labels': labels, 'data': data}
    
    def get_all_unique_species(self):
        """Get all unique bird species ever detected, sorted alphabetically"""
        query = """
        SELECT DISTINCT common_name, scientific_name
        FROM detections
        ORDER BY common_name ASC
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        return [
            {
                'common_name': row['common_name'],
                'scientific_name': row['scientific_name']
            }
            for row in results
        ]

    def get_species_counts(self):
        """Get detection count for each species.

        Returns:
            dict: {common_name: count} for all species
        """
        query = """
        SELECT common_name, COUNT(*) as count
        FROM detections
        GROUP BY common_name
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        return {row['common_name']: row['count'] for row in results}

    def get_cleanup_candidates(self, keep_per_species=60, limit=None):
        """Get detections eligible for cleanup, oldest first.

        For each species, keeps the top N recordings by confidence.
        Only returns recordings beyond the top N for each species.

        Args:
            keep_per_species: Number of top recordings to keep per species (by confidence)
            limit: Optional max number of records to return

        Returns:
            List of dicts with: id, common_name, confidence, timestamp
            Ordered by timestamp ASC (oldest first)
        """
        # Use window function to rank recordings within each species by confidence
        # Only return recordings ranked beyond keep_per_species
        # LIMIT is parameterized using -1 for unlimited (SQLite treats negative LIMIT as no limit)
        query = """
        WITH RankedDetections AS (
            SELECT
                id,
                common_name,
                confidence,
                timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY common_name
                    ORDER BY confidence DESC
                ) as confidence_rank
            FROM detections
        )
        SELECT id, common_name, confidence, timestamp
        FROM RankedDetections
        WHERE confidence_rank > ?
        ORDER BY timestamp ASC
        LIMIT ?
        """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (keep_per_species, limit_param))
            results = cur.fetchall()

        candidates = [dict(row) for row in results]

        logger.debug("Cleanup candidates retrieved", extra={
            'keep_per_species': keep_per_species,
            'candidates_count': len(candidates)
        })

        return candidates

    def get_paginated_detections(self, page=1, per_page=25, start_date=None,
                                  end_date=None, species=None, sort='timestamp',
                                  order='desc'):
        """Get paginated detection records with optional filtering.

        Args:
            page: Page number (1-indexed)
            per_page: Results per page (max 100)
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name
            sort: Sort field (timestamp, confidence, common_name)
            order: Sort order (asc, desc)

        Returns:
            tuple: (list of detections with filenames, total_count)
        """
        # Validate and constrain per_page
        per_page = min(max(1, per_page), 100)
        page = max(1, page)
        offset = (page - 1) * per_page

        # Validate sort field to prevent SQL injection
        valid_sort_fields = {'timestamp', 'confidence', 'common_name'}
        if sort not in valid_sort_fields:
            sort = 'timestamp'

        # Validate order
        order = 'ASC' if order.lower() == 'asc' else 'DESC'

        # Build WHERE conditions
        conditions = []
        params = []

        if start_date:
            start_date_iso = f"{start_date}T00:00:00"
            conditions.append("timestamp >= ?")
            params.append(start_date_iso)

        if end_date:
            end_date_iso = f"{end_date}T23:59:59"
            conditions.append("timestamp <= ?")
            params.append(end_date_iso)

        if species:
            conditions.append("common_name = ?")
            params.append(species)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Get total count
        count_query = f"""
        SELECT COUNT(*) as total
        FROM detections
        WHERE {where_clause}
        """

        # Get paginated results
        # Using safe string interpolation for sort/order (validated above)
        data_query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra
        FROM detections
        WHERE {where_clause}
        ORDER BY {sort} {order}
        LIMIT ? OFFSET ?
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()

            # Get total count
            cur.execute(count_query, params)
            total_count = cur.fetchone()['total']

            # Get paginated data
            cur.execute(data_query, params + [per_page, offset])
            rows = cur.fetchall()

        # Build detection list with filenames
        detections = []
        for row in rows:
            detection = dict(row)

            # Parse extra JSON field
            detection['extra'] = self._parse_extra(detection.get('extra'))

            # Generate standardized filenames using utility function
            filenames = build_detection_filenames(
                detection['common_name'],
                detection['confidence'],
                detection['timestamp'],
                audio_extension='mp3'
            )

            detection['audio_filename'] = filenames['audio_filename']
            detection['spectrogram_filename'] = filenames['spectrogram_filename']

            detections.append(detection)

        logger.debug("Paginated detections retrieved", extra={
            'page': page,
            'per_page': per_page,
            'total_count': total_count,
            'returned_count': len(detections),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'species': species
            }
        })

        return detections, total_count

    def get_all_detections_for_export(self, start_date=None, end_date=None, species=None):
        """Get all detection records for CSV export.

        Fetches all matching rows in a single query. This is simpler and avoids
        consistency issues with batched LIMIT/OFFSET (where concurrent inserts
        can cause skipped or duplicate rows).

        For typical Raspberry Pi deployments with thousands of detections,
        this approach is efficient and the memory footprint is minimal.

        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name

        Returns:
            list: All detection records matching the filters
        """
        # Build WHERE conditions
        conditions = []
        params = []

        if start_date:
            start_date_iso = f"{start_date}T00:00:00"
            conditions.append("timestamp >= ?")
            params.append(start_date_iso)

        if end_date:
            end_date_iso = f"{end_date}T23:59:59"
            conditions.append("timestamp <= ?")
            params.append(end_date_iso)

        if species:
            conditions.append("common_name = ?")
            params.append(species)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra
        FROM detections
        WHERE {where_clause}
        ORDER BY timestamp DESC, id DESC
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        # For export, keep extra as raw JSON string (not parsed)
        detections = [dict(row) for row in rows]

        logger.debug("Detections exported", extra={
            'count': len(detections),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'species': species
            }
        })

        return detections

    def get_detection_by_id(self, detection_id):
        """Get a single detection by ID.

        Args:
            detection_id: The detection ID

        Returns:
            dict: Detection record or None if not found
        """
        query = """
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra
        FROM detections
        WHERE id = ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (detection_id,))
            row = cur.fetchone()

        if row:
            detection = dict(row)
            detection['extra'] = self._parse_extra(detection.get('extra'))
            filenames = build_detection_filenames(
                detection['common_name'],
                detection['confidence'],
                detection['timestamp'],
                audio_extension='mp3'
            )
            detection['audio_filename'] = filenames['audio_filename']
            detection['spectrogram_filename'] = filenames['spectrogram_filename']
            return detection
        return None

    def delete_detection(self, detection_id):
        """Delete a detection record by ID.

        Args:
            detection_id: The detection ID to delete

        Returns:
            dict: The deleted detection info (for file cleanup) or None if not found
        """
        # First get the detection info for file cleanup
        detection = self.get_detection_by_id(detection_id)

        if not detection:
            return None

        # Delete the record
        query = "DELETE FROM detections WHERE id = ?"
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (detection_id,))
            conn.commit()
            rows_deleted = cur.rowcount

        if rows_deleted > 0:
            logger.info("Detection deleted", extra={
                'detection_id': detection_id,
                'species': detection['common_name'],
                'timestamp': detection['timestamp']
            })
            return detection

        return None

    # -------------------------------------------------------------------------
    # Extra field helpers
    # -------------------------------------------------------------------------

    def _parse_extra(self, extra_raw):
        """Parse the extra JSON field from a database value into a dict.

        Args:
            extra_raw: Raw value from database (string, None, or already dict)

        Returns:
            dict: Parsed JSON object, or empty dict if invalid/missing
        """
        if extra_raw is None:
            return {}
        if isinstance(extra_raw, dict):
            return extra_raw
        try:
            return json.loads(extra_raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_extra_field(self, detection_id, field_name, default=None):
        """Get a specific field from a detection's extra JSON.

        Args:
            detection_id: The detection ID
            field_name: Key to retrieve from extra JSON
            default: Value to return if field doesn't exist

        Returns:
            The field value or default
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT extra FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()
            if row:
                extra = self._parse_extra(row['extra'])
                return extra.get(field_name, default)
            return default

    def update_extra_field(self, detection_id, field_name, value):
        """Update a specific field in a detection's extra JSON.

        Args:
            detection_id: The detection ID
            field_name: Key to update in extra JSON
            value: Value to set

        Returns:
            bool: True if updated, False if detection not found
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()

            # Get current extra
            cur.execute("SELECT extra FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

            if not row:
                return False

            # Parse, update, and save
            extra = self._parse_extra(row['extra'])
            extra[field_name] = value

            cur.execute(
                "UPDATE detections SET extra = ? WHERE id = ?",
                (json.dumps(extra), detection_id)
            )
            conn.commit()
            return True

    def set_extra(self, detection_id, extra_dict):
        """Replace the entire extra JSON for a detection.

        Args:
            detection_id: The detection ID
            extra_dict: Dict to set as extra (replaces existing)

        Returns:
            bool: True if updated, False if detection not found
        """
        if not isinstance(extra_dict, dict):
            raise ValueError("extra_dict must be a dictionary")

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE detections SET extra = ? WHERE id = ?",
                (json.dumps(extra_dict), detection_id)
            )
            conn.commit()
            return cur.rowcount > 0