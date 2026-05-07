"""Memory and behavior regression tests for the species label cache."""

import sys
import types

import pytest

from model_service import label_utils
from model_service.label_utils import (
    _ensure_language_loaded,
    _ensure_loaded,
    clear_species_cache,
    get_localized_name,
    get_localized_name_from_english,
    get_species_list,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_species_cache()
    yield
    clear_species_cache()


class TestSpeciesTableLayout:
    """Behavioral checks for the columnar layout."""

    def test_localized_name_lookup_supported_language(self):
        assert get_localized_name('Turdus migratorius', 'de') == 'Wanderdrossel'

    def test_localized_name_lookup_unknown_species(self):
        assert get_localized_name('Fakeus birdus', 'de') is None

    def test_localized_name_unknown_language_returns_none(self):
        assert get_localized_name('Turdus migratorius', 'zz_xx') is None

    def test_localized_name_from_english_supported_language(self):
        assert get_localized_name_from_english('American Robin', 'de') == 'Wanderdrossel'

    def test_species_list_v2_sorted_by_common_name(self):
        v2 = get_species_list('birdnet')
        assert len(v2) > 6000
        assert all('scientific_name' in s and 'common_name' in s for s in v2)
        assert v2 == sorted(v2, key=lambda s: s['common_name'])

    def test_species_list_v3_includes_more_species_than_v2(self):
        v2 = get_species_list('birdnet')
        v3 = get_species_list('birdnet_v3')
        assert len(v3) > len(v2)


def _retained_module_cache_bytes(module: types.ModuleType) -> int:
    """Recursive retained-size of all module-level data attributes.

    Walks every non-dunder, non-callable, non-module/class attribute and sums
    sys.getsizeof through the object graph, deduplicating by id so interned
    strings and shared references are counted once.

    Allocation-site independent (unlike tracemalloc filtering by file): a
    regression that stores per-row dicts produced by ``csv.DictReader`` would
    still attribute the strings to ``csv.py`` under tracemalloc, but those
    objects are reachable from this module's globals and so are counted here.
    """
    seen: set[int] = set()
    total = 0
    stack = [
        value
        for name, value in vars(module).items()
        if not name.startswith('__')
        and not callable(value)
        and not isinstance(value, (type, types.ModuleType))
    ]
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        try:
            total += sys.getsizeof(obj)
        except TypeError:
            continue
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
    return total


@pytest.mark.skipif(
    sys.implementation.name != 'cpython',
    reason='Memory accounting depends on CPython object layout',
)
class TestSpeciesTableMemoryFootprint:
    """Regression guard against the dict-of-dicts shape returning."""

    def test_metadata_only_load_under_8_mb(self):
        _ensure_loaded()
        used = _retained_module_cache_bytes(label_utils)
        # Measured ~4 MB columnar; the pre-refactor dict-of-dicts shape
        # retained ~36 MB by this measurement, so 8 MB cleanly separates them.
        assert used < 8 * 1024 * 1024, (
            f'label_utils cache retained {used:,} bytes after metadata-only '
            'load; expected < 8 MB. Did the dict-of-dicts shape return?'
        )

    def test_single_language_load_under_10_mb(self):
        _ensure_loaded()
        _ensure_language_loaded('de')
        used = _retained_module_cache_bytes(label_utils)
        # Measured ~5 MB after one language; headroom for ~1 MB per column.
        assert used < 10 * 1024 * 1024, (
            f'label_utils cache retained {used:,} bytes after metadata + DE '
            'load; expected < 10 MB.'
        )
