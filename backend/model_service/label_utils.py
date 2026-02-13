"""Utilities for parsing BirdNET label files.

These are kept free of ML dependencies so they can be imported
by both the model service and the API server.
"""

import csv


def parse_v3_labels(path: str) -> list[tuple[str, str]]:
    """Parse V3.0 semicolon-delimited CSV labels file.

    CSV format: idx;id;sci_name;com_name;class;order

    Returns:
        List of (scientific_name, common_name) tuples.
    """
    labels = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            sci = row.get('sci_name', '').strip()
            com = row.get('com_name', '').strip()
            if sci and com:
                labels.append((sci, com))
    return labels
