import sqlite3
from datetime import datetime

def migrate_database(old_db_path, new_db_path):
    # Connect to the old and new databases
    old_conn = sqlite3.connect(old_db_path)
    new_conn = sqlite3.connect(new_db_path)
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()

    # Create the new table
    new_cursor.execute('''
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
            week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED
        )
    ''')

    # Create indexes
    new_cursor.execute('CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC)')
    new_cursor.execute('CREATE INDEX IF NOT EXISTS idx_detections_common_name ON detections(common_name)')
    new_cursor.execute('CREATE INDEX IF NOT EXISTS idx_detections_scientific_name ON detections(scientific_name)')
    new_cursor.execute('CREATE INDEX IF NOT EXISTS idx_detections_week ON detections(week)')
    new_cursor.execute('CREATE INDEX IF NOT EXISTS idx_detections_location ON detections(latitude, longitude)')

    # Fetch all data from the old table
    old_cursor.execute('SELECT Date, Time, Sci_Name, Com_Name, Confidence, Lat, Lon, Cutoff, Sens, Overlap FROM detections')
    
    # Prepare the insert statement for the new table
    insert_stmt = '''
        INSERT INTO detections (
            timestamp, group_timestamp ,scientific_name, common_name, confidence, 
            latitude, longitude, cutoff, sensitivity, overlap
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''

    # Migrate the data
    for row in old_cursor.fetchall():
        date, time, sci_name, com_name, confidence, lat, lon, cutoff, sens, overlap = row
        
        # Combine date and time into a timestamp
        timestamp = f"{date}T{time}"
        
        # Insert into the new table
        # Reusing timestamp as group_timestamp
        new_cursor.execute(insert_stmt, (
            timestamp, timestamp, sci_name, com_name, confidence,
            lat, lon, cutoff, sens, overlap
        ))

    # Commit the changes and close the connections
    new_conn.commit()
    old_conn.close()
    new_conn.close()

    print("Migration completed successfully!")

# Usage
old_db_path = 'birds_old.db'
new_db_path = 'birds_new.db'
migrate_database(old_db_path, new_db_path)