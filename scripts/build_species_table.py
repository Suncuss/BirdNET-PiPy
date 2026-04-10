#!/usr/bin/env python3
"""Build a unified species lookup table from all label sources.

Merges:
  - V2.4 label files (28 languages, ~6K species each)
  - V3.0 labels CSV (~11K species, English + taxonomy)
  - eBird codes JSON (~11K mappings)

Output: backend/model_service/models/species_table.csv

Run from repo root:
    python3 scripts/build_species_table.py
"""

import csv
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_LABELS_DIR = os.path.join(
    REPO_ROOT, "backend", "model_service", "models", "v2.4", "labels"
)
V3_LABELS_CSV = os.path.join(
    REPO_ROOT,
    "backend",
    "model_service",
    "models",
    "v3.0",
    "BirdNET_V3.0_Global_11K_Labels.csv",
)
EBIRD_CODES_JSON = os.path.join(
    REPO_ROOT, "backend", "model_service", "models", "ebird_codes.json"
)
OUTPUT_CSV = os.path.join(
    REPO_ROOT, "backend", "model_service", "models", "species_table.csv"
)

# Language codes extracted from V2.4 label filenames, sorted.
# en_uk is a variant; we keep it as a separate column.
V2_LABEL_PATTERN = re.compile(r"BirdNET_GLOBAL_6K_V2\.4_Labels_(\w+)\.txt")


def discover_languages():
    """Find all language codes from V2.4 label filenames."""
    langs = []
    for fname in sorted(os.listdir(V2_LABELS_DIR)):
        m = V2_LABEL_PATTERN.match(fname)
        if m:
            langs.append(m.group(1))
    return langs


def load_v2_labels(lang):
    """Load a V2.4 label file. Returns dict {sci_name: common_name}."""
    fname = f"BirdNET_GLOBAL_6K_V2.4_Labels_{lang}.txt"
    path = os.path.join(V2_LABELS_DIR, fname)
    mapping = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: "SciName_CommonName" — split on first underscore
            parts = line.split("_", 1)
            if len(parts) == 2:
                sci_name, common_name = parts
                mapping[sci_name] = common_name
    return mapping


def load_v3_labels():
    """Load V3.0 labels CSV. Returns list of dicts with sci_name, com_name, class, order."""
    rows = []
    with open(V3_LABELS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(
                {
                    "sci_name": row["sci_name"],
                    "com_name": row["com_name"],
                    "class": row["class"],
                    "order": row["order"],
                }
            )
    return rows


def load_ebird_codes():
    """Load eBird codes JSON. Returns dict {sci_name: ebird_code}."""
    with open(EBIRD_CODES_JSON, encoding="utf-8") as f:
        return json.load(f)


def build_table():
    """Merge all sources into a unified species table."""
    print("Discovering V2.4 languages...")
    languages = discover_languages()
    print(f"  Found {len(languages)} languages: {', '.join(languages)}")

    # Start with V3.0 as the base (superset of species)
    print("Loading V3.0 labels...")
    v3_rows = load_v3_labels()
    print(f"  {len(v3_rows)} species")

    # Build species dict keyed on sci_name
    species = {}
    for row in v3_rows:
        sci = row["sci_name"]
        species[sci] = {
            "sci_name": sci,
            "common_name": row["com_name"],
            "class": row["class"],
            "order": row["order"],
            "in_v2": False,
            "in_v3": True,
        }

    # Load V2.4 English first to get common names for V2-only species
    print("Loading V2.4 English labels...")
    v2_en = load_v2_labels("en")
    print(f"  {len(v2_en)} species")

    # Add V2-only species (not in V3)
    v2_only_count = 0
    for sci, common in v2_en.items():
        if sci in species:
            species[sci]["in_v2"] = True
        else:
            # Species in V2 but not V3
            species[sci] = {
                "sci_name": sci,
                "common_name": common,
                "class": "",
                "order": "",
                "in_v2": True,
                "in_v3": False,
            }
            v2_only_count += 1
    print(f"  {v2_only_count} species only in V2.4 (not in V3.0)")

    # Load eBird codes
    print("Loading eBird codes...")
    ebird = load_ebird_codes()
    matched_ebird = 0
    for sci in species:
        if sci in ebird:
            species[sci]["ebird_code"] = ebird[sci]
            matched_ebird += 1
        else:
            species[sci]["ebird_code"] = ""
    print(f"  {matched_ebird}/{len(species)} species matched")

    # Load all V2.4 language files
    print("Loading V2.4 localized labels...")
    lang_maps = {}
    for lang in languages:
        lang_maps[lang] = load_v2_labels(lang)
        # Apply translations to species dict
        for sci, common in lang_maps[lang].items():
            if sci in species:
                species[sci][f"label_{lang}"] = common

    # Fill missing language columns with empty string
    for sci in species:
        for lang in languages:
            key = f"label_{lang}"
            if key not in species[sci]:
                species[sci][key] = ""

    return species, languages


def write_csv(species, languages):
    """Write the unified table to CSV."""
    # Column order
    columns = [
        "sci_name",
        "common_name",
        "ebird_code",
        "class",
        "order",
        "in_v2",
        "in_v3",
    ] + [f"label_{lang}" for lang in languages]

    # Sort by scientific name
    sorted_species = sorted(species.values(), key=lambda s: s["sci_name"])

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for row in sorted_species:
            writer.writerow({col: row.get(col, "") for col in columns})

    print(f"\nWritten {len(sorted_species)} species to {OUTPUT_CSV}")


def print_stats(species, languages):
    """Print summary statistics."""
    total = len(species)
    in_v2 = sum(1 for s in species.values() if s["in_v2"])
    in_v3 = sum(1 for s in species.values() if s["in_v3"])
    both = sum(1 for s in species.values() if s["in_v2"] and s["in_v3"])
    has_ebird = sum(1 for s in species.values() if s["ebird_code"])

    # Count species with at least one non-English translation
    has_translation = sum(
        1
        for s in species.values()
        if any(s.get(f"label_{lang}") for lang in languages if lang != "en")
    )

    birds = sum(1 for s in species.values() if s["class"] == "Aves")
    non_birds = sum(1 for s in species.values() if s["class"] and s["class"] != "Aves")

    print(f"\n{'='*50}")
    print(f"SPECIES TABLE SUMMARY")
    print(f"{'='*50}")
    print(f"Total species:            {total}")
    print(f"  Birds (Aves):           {birds}")
    print(f"  Non-birds:              {non_birds}")
    print(f"  No taxonomy (V2-only):  {total - birds - non_birds}")
    print(f"")
    print(f"Model coverage:")
    print(f"  In V2.4:                {in_v2}")
    print(f"  In V3.0:                {in_v3}")
    print(f"  In both:                {both}")
    print(f"  V2-only:                {in_v2 - both}")
    print(f"  V3-only:                {in_v3 - both}")
    print(f"")
    print(f"eBird codes:              {has_ebird}/{total}")
    print(f"Has translations:         {has_translation}/{total}")
    print(f"Languages:                {len(languages)}")


if __name__ == "__main__":
    species, languages = build_table()
    write_csv(species, languages)
    print_stats(species, languages)
