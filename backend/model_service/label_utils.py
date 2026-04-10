"""Utilities for parsing BirdNET label files and species lookups.

These are kept free of ML dependencies so they can be imported
by both the model service and the API server.
"""

import csv
import logging
import os
import threading

logger = logging.getLogger(__name__)

_SPECIES_TABLE_PATH = os.path.join(
    os.path.dirname(__file__), 'models', 'species_table.csv'
)

# Loaded lazily by _ensure_loaded()
_species_by_sci: dict[str, dict] | None = None
_species_by_common: dict[str, str] | None = None
_loading_lock = threading.Lock()


def _ensure_loaded():
    """Load species table on first access (thread-safe)."""
    global _species_by_sci, _species_by_common
    if _species_by_sci is not None:
        return

    with _loading_lock:
        if _species_by_sci is not None:
            return

        by_sci = {}
        by_common = {}

        try:
            with open(_SPECIES_TABLE_PATH, encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    sci = row['sci_name']
                    by_sci[sci] = row
                    common = row.get('common_name', '')
                    if common:
                        by_common[common] = sci
            logger.info("Loaded species table: %d species", len(by_sci))
        except Exception:
            logger.exception("Failed to load species table from %s", _SPECIES_TABLE_PATH)

        _species_by_common = by_common
        _species_by_sci = by_sci


def clear_species_cache():
    """Reset the loaded species table. Used by tests."""
    global _species_by_sci, _species_by_common
    _species_by_sci = None
    _species_by_common = None


def get_localized_name(sci_name: str, language: str) -> str | None:
    """Look up localized common name for a species.

    Returns None if species or language translation not found.
    """
    _ensure_loaded()
    row = _species_by_sci.get(sci_name)
    if not row:
        return None
    name = row.get(f'label_{language}', '')
    return name if name else None


def get_localized_name_from_english(common_name: str, language: str) -> str | None:
    """Look up localized name given an English common name.

    Returns None if species or translation not found.
    """
    _ensure_loaded()
    sci_name = _species_by_common.get(common_name)
    if not sci_name:
        return None
    return get_localized_name(sci_name, language)


def get_ebird_code(sci_name: str) -> str | None:
    """Look up eBird species code for a scientific name."""
    _ensure_loaded()
    row = _species_by_sci.get(sci_name)
    if not row:
        return None
    code = row.get('ebird_code', '')
    return code if code else None


def get_species_list(model_type: str) -> list[dict]:
    """Return species for a given model type.

    Returns list of dicts with 'scientific_name' and 'common_name' keys,
    sorted by common name.
    """
    from config.constants import ModelType

    _ensure_loaded()
    flag = 'in_v3' if model_type == ModelType.BIRDNET_V3.value else 'in_v2'

    species = [
        {'scientific_name': row['sci_name'], 'common_name': row['common_name']}
        for row in _species_by_sci.values()
        if row.get(flag) == 'True'
    ]
    species.sort(key=lambda s: s['common_name'])
    return species


# ---------------------------------------------------------------------------
# Species label helpers (shared across model service modules)
# ---------------------------------------------------------------------------

def get_scientific_name(label: str) -> str:
    """Extract scientific name from a full species label.

    Args:
        label: Full species label (e.g., "Turdus migratorius_American Robin")

    Returns:
        Scientific name (e.g., "Turdus migratorius")
    """
    parts = label.split('_', 1)
    return parts[0] if len(parts) == 2 else label


def get_common_name(label: str) -> str:
    """Extract common name from a full species label."""
    parts = label.split('_', 1)
    return parts[1] if len(parts) == 2 else label


# ---------------------------------------------------------------------------
# Model-specific label parsers (used by model classes for inference only)
# ---------------------------------------------------------------------------

def parse_v2_labels(path: str) -> list[tuple[str, str]]:
    """Parse V2.4 text labels file.

    Text format: SciName_CommonName

    Returns:
        List of (scientific_name, common_name) tuples.
    """
    labels = []
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            scientific_name, separator, common_name = line.partition('_')
            if scientific_name and separator and common_name:
                labels.append((scientific_name.strip(), common_name.strip()))

    return labels


def parse_geomodel_labels(path: str) -> list[tuple[str, str, str]]:
    """Parse geomodel tab-delimited labels file.

    Format: speciesCode<TAB>scientificName<TAB>commonName

    Returns:
        List of (species_code, scientific_name, common_name) tuples
        in model output order (index = position in list).
    """
    labels = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 3:
                code, sci, com = parts[0].strip(), parts[1].strip(), parts[2].strip()
            elif len(parts) == 2:
                code, sci = parts[0].strip(), parts[1].strip()
                com = sci
            else:
                code = sci = com = parts[0].strip()
            if sci:
                labels.append((code, sci, com))
    return labels


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
