"""
Script to create a test database with sample data for testing.
This can be run to generate a consistent test database.
"""
import os
import random
import sqlite3
from datetime import datetime, timedelta

# Test database path
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'test_birds.db')

# Database schema (same as production)
SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    group_timestamp DATETIME NOT NULL,
    scientific_name VARCHAR(100) NOT NULL,
    common_name VARCHAR(100) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    latitude DECIMAL(10,8) CHECK(latitude >= -90 AND latitude <= 90),
    longitude DECIMAL(11,8) CHECK(longitude >= -180 AND longitude <= 180),
    cutoff DECIMAL(4,3) CHECK(cutoff > 0 AND cutoff <= 1),
    sensitivity DECIMAL(4,3) CHECK(sensitivity > 0),
    overlap DECIMAL(4,3) CHECK(overlap >= 0 AND overlap <= 1),
    week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED,
    extra TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detections_common_name ON detections(common_name);
CREATE INDEX IF NOT EXISTS idx_detections_scientific_name ON detections(scientific_name);
CREATE INDEX IF NOT EXISTS idx_detections_week ON detections(week);
CREATE INDEX IF NOT EXISTS idx_detections_location ON detections(latitude, longitude);
"""

# Sample bird species data
BIRD_SPECIES = [
    # Common birds (will have many detections)
    {'common_name': 'American Robin', 'scientific_name': 'Turdus migratorius', 'frequency': 'common'},
    {'common_name': 'Northern Cardinal', 'scientific_name': 'Cardinalis cardinalis', 'frequency': 'common'},
    {'common_name': 'Blue Jay', 'scientific_name': 'Cyanocitta cristata', 'frequency': 'common'},
    {'common_name': 'Black-capped Chickadee', 'scientific_name': 'Poecile atricapillus', 'frequency': 'common'},

    # Uncommon birds (moderate detections)
    {'common_name': 'Red-bellied Woodpecker', 'scientific_name': 'Melanerpes carolinus', 'frequency': 'uncommon'},
    {'common_name': 'White-breasted Nuthatch', 'scientific_name': 'Sitta carolinensis', 'frequency': 'uncommon'},
    {'common_name': 'Eastern Bluebird', 'scientific_name': 'Sialia sialis', 'frequency': 'uncommon'},

    # Rare birds (few detections)
    {'common_name': 'Hooded Warbler', 'scientific_name': 'Setophaga citrina', 'frequency': 'rare'},
    {'common_name': 'Scarlet Tanager', 'scientific_name': 'Piranga olivacea', 'frequency': 'rare'},
    {'common_name': 'Indigo Bunting', 'scientific_name': 'Passerina cyanea', 'frequency': 'rare'},
]

def create_test_database():
    """Create a test database with sample data."""
    # Remove existing test database if it exists
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    # Create new database
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()

    # Create schema
    cursor.executescript(SCHEMA)

    # Generate sample detections
    base_time = datetime.now()
    detections = []

    for bird in BIRD_SPECIES:
        # Determine number of detections based on frequency
        if bird['frequency'] == 'common':
            num_detections = random.randint(50, 100)
        elif bird['frequency'] == 'uncommon':
            num_detections = random.randint(10, 30)
        else:  # rare
            num_detections = random.randint(1, 5)

        # Generate detections over the past 30 days
        for _i in range(num_detections):
            # Random time in the past 30 days
            days_ago = random.uniform(0, 30)
            hours_offset = random.uniform(0, 24)
            detection_time = base_time - timedelta(days=days_ago, hours=hours_offset)

            # Higher confidence for common birds
            if bird['frequency'] == 'common':
                confidence = random.uniform(0.75, 0.99)
            elif bird['frequency'] == 'uncommon':
                confidence = random.uniform(0.65, 0.85)
            else:  # rare
                confidence = random.uniform(0.55, 0.75)

            detection = {
                'timestamp': detection_time.isoformat(),
                'group_timestamp': detection_time.isoformat(),
                'scientific_name': bird['scientific_name'],
                'common_name': bird['common_name'],
                'confidence': round(confidence, 4),
                'latitude': 40.7128 + random.uniform(-0.1, 0.1),  # NYC area
                'longitude': -74.0060 + random.uniform(-0.1, 0.1),
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            detections.append(detection)

    # Insert all detections
    cursor.executemany("""
        INSERT INTO detections (
            timestamp, group_timestamp, scientific_name, common_name,
            confidence, latitude, longitude, cutoff, sensitivity, overlap, extra
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(d['timestamp'], d['group_timestamp'], d['scientific_name'],
           d['common_name'], d['confidence'], d['latitude'], d['longitude'],
           d['cutoff'], d['sensitivity'], d['overlap'], '{}') for d in detections])

    conn.commit()

    # Print summary
    cursor.execute("SELECT COUNT(*) FROM detections")
    total_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT common_name) FROM detections")
    species_count = cursor.fetchone()[0]

    print(f"Test database created at: {TEST_DB_PATH}")
    print(f"Total detections: {total_count}")
    print(f"Unique species: {species_count}")

    # Show detection counts by species
    cursor.execute("""
        SELECT common_name, COUNT(*) as count
        FROM detections
        GROUP BY common_name
        ORDER BY count DESC
    """)

    print("\nDetections by species:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    conn.close()

if __name__ == "__main__":
    create_test_database()
