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
    resolve_to_scientific_name,
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


class TestResolveToScientificName:
    """English-synonym resolver covering canonical + V2 label drift."""

    def test_canonical_common_name_resolves(self):
        # 'Common Blackbird' is the V3 canonical for Turdus merula.
        assert resolve_to_scientific_name('Common Blackbird') == 'Turdus merula'

    def test_v2_label_en_synonym_resolves(self):
        # The V2 model emits 'Eurasian Blackbird' for the same species.
        # Pre-resolver, this string missed _common_to_idx and broke
        # add_display_species translation.
        assert resolve_to_scientific_name('Eurasian Blackbird') == 'Turdus merula'

    def test_resolution_is_case_insensitive(self):
        assert resolve_to_scientific_name('eurasian blackbird') == 'Turdus merula'
        assert resolve_to_scientific_name('  COMMON BLACKBIRD  ') == 'Turdus merula'

    def test_unknown_name_returns_none(self):
        assert resolve_to_scientific_name('Definitely Not A Real Bird') is None

    def test_empty_inputs_return_none(self):
        assert resolve_to_scientific_name('') is None
        assert resolve_to_scientific_name(None) is None
        assert resolve_to_scientific_name('   ') is None

    def test_canonical_wins_over_label_en_within_a_row(self):
        # Within a single row, the canonical common_name takes precedence
        # over label_en when both are present and different. For Turdus merula
        # both columns lead to the same row, so we only need to assert the
        # value is the correct scientific name.
        assert resolve_to_scientific_name('Common Blackbird') == 'Turdus merula'
        assert resolve_to_scientific_name('Eurasian Blackbird') == 'Turdus merula'

    def test_canonical_wins_across_rows_black_vulture(self):
        # Cross-row shadowing regression. Aegypius monachus (Cinereous Vulture,
        # CSV row "A") has label_en_uk = "Black Vulture". Coragyps atratus (CSV
        # row "C") has common_name = "Black Vulture". An earlier setdefault-
        # only pass would route "Black Vulture" detections to Aegypius monachus
        # — the Old World species — and the /api/bird/Black Vulture detail
        # page would miss every real V2 BirdNET detection.
        assert resolve_to_scientific_name('Black Vulture') == 'Coragyps atratus'
        # The Aegypius side is still reachable via its canonical name.
        assert resolve_to_scientific_name('Cinereous Vulture') == 'Aegypius monachus'

    def test_taxonomic_rename_resolves_to_v3_canonical(self):
        # Shikra is one of ~137 species where V2 and V3 use different
        # scientific names for the same bird (V2: Accipiter badius,
        # V3: Tachyspiza badia). Both rows live in the species table; the
        # resolver returns whichever canonical common_name appears last in
        # CSV order — for Shikra that's the V3 Tachyspiza row, which matches
        # what new V3 detections store. Known limitation: a V2-on-disk user
        # with detections saved under "Accipiter badius" will not see those
        # rows merged on /api/bird/Shikra; a scientific-name synonym table
        # is the right follow-up but is out of scope for this PR.
        assert resolve_to_scientific_name('Shikra') == 'Tachyspiza badia'


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
