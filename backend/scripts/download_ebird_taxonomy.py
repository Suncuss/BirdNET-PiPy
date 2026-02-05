#!/usr/bin/env python3
"""
Download eBird taxonomy and generate scientific_name -> ebird_code mapping.

This script downloads the eBird/Clements taxonomy CSV from Cornell Lab of Ornithology
and generates a JSON mapping file for use by the BirdNET service.

Usage:
    python download_ebird_taxonomy.py [--output PATH]

The output JSON maps scientific names to eBird species codes:
    {
        "Turdus migratorius": "amerob",
        "Cardinalis cardinalis": "norcar",
        ...
    }
"""

import argparse
import csv
import json
import logging
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# eBird taxonomy CSV download URL (v2024)
EBIRD_TAXONOMY_URL = (
    "https://www.birds.cornell.edu/clementschecklist/wp-content/uploads/2024/10/"
    "eBird-Clements-v2024-integrated-checklist-October-2024-rev.csv"
)

# Default output path relative to this script
DEFAULT_OUTPUT_PATH = Path(__file__).parent.parent / "model_service" / "models" / "ebird_codes.json"


def download_csv(url: str) -> str:
    """Download CSV from URL and return path to temporary file."""
    logger.info(f"Downloading eBird taxonomy from {url}")

    # Create temporary file
    fd, temp_path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)

    try:
        # Use a proper User-Agent to avoid 403 errors
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; BirdNET-PiPy/1.0)'}
        )
        with urllib.request.urlopen(request) as response:
            with open(temp_path, 'wb') as f:
                f.write(response.read())
        logger.info(f"Downloaded to {temp_path}")
        return temp_path
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise RuntimeError(f"Failed to download taxonomy: {e}") from e


def parse_ebird_csv(csv_path: str) -> dict:
    """
    Parse eBird taxonomy CSV and extract scientific_name -> species_code mapping.

    Only includes entries with category='species' to avoid subspecies and groups.

    Args:
        csv_path: Path to the downloaded CSV file

    Returns:
        Dict mapping scientific names to eBird species codes
    """
    mapping = {}
    species_count = 0
    skipped_count = 0

    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            category = row.get('category', '').strip()
            scientific_name = row.get('scientific name', '').strip()
            species_code = row.get('species_code', '').strip()

            # Only include species (not subspecies, groups, etc.)
            if category != 'species':
                skipped_count += 1
                continue

            if not scientific_name or not species_code:
                skipped_count += 1
                continue

            mapping[scientific_name] = species_code
            species_count += 1

    logger.info(f"Parsed {species_count} species, skipped {skipped_count} non-species entries")
    return mapping


def save_json(mapping: dict, output_path: Path) -> None:
    """Save mapping to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(mapping)} entries to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download eBird taxonomy and generate species code mapping."
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT_PATH})"
    )
    parser.add_argument(
        '--url',
        default=EBIRD_TAXONOMY_URL,
        help="eBird taxonomy CSV URL (default: v2024)"
    )
    args = parser.parse_args()

    temp_csv = None
    try:
        # Download CSV
        temp_csv = download_csv(args.url)

        # Parse and extract mapping
        mapping = parse_ebird_csv(temp_csv)

        if not mapping:
            logger.error("No species found in taxonomy. Check CSV format.")
            sys.exit(1)

        # Save JSON
        save_json(mapping, args.output)

        # Print sample entries
        sample = list(mapping.items())[:5]
        logger.info("Sample entries:")
        for sci_name, code in sample:
            logger.info(f"  {sci_name} -> {code}")

    finally:
        # Cleanup temp file
        if temp_csv and os.path.exists(temp_csv):
            os.unlink(temp_csv)


if __name__ == "__main__":
    main()
