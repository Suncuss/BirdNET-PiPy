# Database Extra Field

This document describes the `extra` JSON column in the `detections` table, which provides flexible schema extension without requiring database migrations.

## Overview

The `extra` column allows storing arbitrary JSON data alongside each detection record. This enables adding new features (weather data, user notes, tags, etc.) without modifying the database schema.

| Aspect | Details |
|--------|---------|
| **Column Type** | `TEXT DEFAULT '{}'` |
| **Storage Format** | JSON string |
| **API Response** | Parsed JSON object |
| **CSV Export** | Raw JSON string |

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS detections (
    -- ... existing columns ...
    extra TEXT DEFAULT '{}'
);
```

## Auto-Migration

For existing databases, the `extra` column is automatically added on startup:

```python
# In DatabaseManager.initialize_database()
if 'extra' not in existing_columns:
    cursor.execute("ALTER TABLE detections ADD COLUMN extra TEXT DEFAULT '{}'")
    cursor.execute("UPDATE detections SET extra = '{}' WHERE extra IS NULL")
```

This ensures:
- New installations get the column from the schema
- Existing installations get the column added automatically
- Existing records are backfilled with `'{}'` during migration

Note: The `insert_detection()` method always provides a valid JSON value, so NULLs should not occur in normal operation.

## Usage

### Inserting Detections with Extra Data

```python
detection = {
    'timestamp': '2024-01-15T10:30:00',
    'common_name': 'American Robin',
    'scientific_name': 'Turdus migratorius',
    'confidence': 0.95,
    # ... other required fields ...
    'extra': {
        'weather': 'sunny',
        'temperature_f': 72,
        'notes': 'Clear morning song'
    }
}
detection_id = db_manager.insert_detection(detection)
```

### Getting Extra Fields

```python
# Get a specific field
weather = db_manager.get_extra_field(detection_id, 'weather')
# Returns: 'sunny'

# Get with default value
humidity = db_manager.get_extra_field(detection_id, 'humidity', default='N/A')
# Returns: 'N/A' (field doesn't exist)
```

### Updating Extra Fields

```python
# Update a single field (preserves other fields)
db_manager.update_extra_field(detection_id, 'user_notes', 'First robin of spring!')

# Replace entire extra object
db_manager.set_extra(detection_id, {'new_data': 'replaces everything'})
```

### Querying by Extra Values

SQLite's JSON1 extension allows querying inside the JSON:

```python
# Find detections with specific weather
cursor.execute("""
    SELECT * FROM detections
    WHERE json_extract(extra, '$.weather') = 'sunny'
""")

# Find detections with tags containing 'favorite'
cursor.execute("""
    SELECT * FROM detections
    WHERE json_extract(extra, '$.tags') LIKE '%favorite%'
""")
```

For frequently queried fields, consider adding an expression index:

```sql
CREATE INDEX idx_extra_weather ON detections(json_extract(extra, '$.weather'));
```

## API Response Format

When retrieving detections via the API, `extra` is returned as a parsed JSON object:

```json
{
    "id": 123,
    "timestamp": "2024-01-15T10:30:00",
    "common_name": "American Robin",
    "extra": {
        "weather": "sunny",
        "temperature_f": 72
    }
}
```

## CSV Export Format

In CSV exports, `extra` is included as a raw JSON string:

```csv
id,timestamp,common_name,...,extra
123,2024-01-15T10:30:00,American Robin,...,"{""weather"": ""sunny""}"
```

## Helper Methods Reference

### `_parse_extra(extra_raw)`
Internal method to parse JSON string to dict. Handles None, empty string, and invalid JSON gracefully.

### `get_extra_field(detection_id, field_name, default=None)`
Get a specific field from a detection's extra JSON.

**Parameters:**
- `detection_id`: The detection ID
- `field_name`: Key to retrieve
- `default`: Value if field doesn't exist (default: None)

**Returns:** The field value or default

### `update_extra_field(detection_id, field_name, value)`
Update a single field in extra, preserving other fields.

**Parameters:**
- `detection_id`: The detection ID
- `field_name`: Key to update
- `value`: New value

**Returns:** `True` if updated, `False` if detection not found

### `set_extra(detection_id, extra_dict)`
Replace the entire extra JSON object.

**Parameters:**
- `detection_id`: The detection ID
- `extra_dict`: Dict to set (must be a dictionary)

**Returns:** `True` if updated, `False` if detection not found

**Raises:** `ValueError` if extra_dict is not a dictionary

## Example Use Cases

### Weather Tracking
```python
detection['extra'] = {
    'weather': {
        'condition': 'partly_cloudy',
        'temperature_f': 68,
        'humidity_percent': 45,
        'wind_mph': 5
    }
}
```

### User Notes and Tags
```python
db_manager.update_extra_field(detection_id, 'user_notes', 'Beautiful morning song!')
db_manager.update_extra_field(detection_id, 'tags', ['favorite', 'rare', 'spring'])
```

### Audio Quality Metadata
```python
detection['extra'] = {
    'audio_quality': 'excellent',
    'background_noise': 'low',
    'distance_estimate': 'near'
}
```

### External Integrations
```python
detection['extra'] = {
    'ebird_checklist_id': 'S123456789',
    'exported_to_ebird': True,
    'export_timestamp': '2024-01-15T12:00:00'
}
```

## Testing

The extra field functionality is tested in `backend/tests/database/test_extra_field.py`:

```bash
cd backend
./docker-test.sh tests/database/test_extra_field.py -v
```

Test coverage includes (27 tests):
- Insert with/without extra data (4 tests)
- Helper methods: get, update, set (10 tests)
- Extra field in all query methods (8 tests):
  - `get_latest_detections`
  - `get_paginated_detections`
  - `get_bird_recordings`
  - `get_all_detections_for_export`
  - `get_detections_by_date_range` (regular and unique)
  - `get_species_sightings` (frequent and rare)
- Parse edge cases: None, invalid JSON, etc. (5 tests)
