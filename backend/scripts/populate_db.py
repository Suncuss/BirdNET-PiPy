import random
from faker import Faker

import sys

from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
print(f"Adding {project_root} to sys.path")
sys.path.append(str(project_root))

from core.db import DatabaseManager

fake = Faker()

# Mapping of common names to scientific names
bird_species = {
    "Northern Cardinal": "Cardinalis cardinalis",
    "American Robin": "Turdus migratorius",
    "Blue Jay": "Cyanocitta cristata",
    "Mourning Dove": "Zenaida macroura",
    "Red-winged Blackbird": "Agelaius phoeniceus",
    "House Sparrow": "Passer domesticus",
    "European Starling": "Sturnus vulgaris",
    "Song Sparrow": "Melospiza melodia",
    "House Finch": "Haemorhous mexicanus",
    "Eastern Bluebird": "Sialia sialis"
}

def populate_database(num_entries=1000):
    db = DatabaseManager()
    db.initialize_database()

    for _ in range(num_entries):
        common_name = random.choice(list(bird_species.keys()))
        scientific_name = bird_species[common_name]
        
        detection = {
            'timestamp': fake.date_time_between(start_date='-30d', end_date='now').isoformat(),
            'group_timestamp': fake.date_time_between(start_date='-30d', end_date='now').isoformat(),
            'scientific_name': scientific_name,
            'common_name': common_name,
            'confidence': float(round(random.uniform(0.8, 1.0), 4)),
            'latitude': float(fake.latitude()),
            'longitude': float(fake.longitude()),
            'cutoff': float(round(random.uniform(0.1, 0.5), 3)),
            'sensitivity': float(round(random.uniform(0.5, 1.0), 3)),
            'overlap': float(round(random.uniform(0.0, 0.5), 3))
        }
        db.insert_detection(detection)

    print(f"Populated database with {num_entries} entries.")

if __name__ == "__main__":
    populate_database()
