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
    parse_geomodel_labels,
    resolve_to_scientific_name,
    resolve_to_scientific_names,
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


class TestGeoModelLabels:
    def test_parser_accepts_utf8_bom(self, tmp_path):
        labels_path = tmp_path / "labels.txt"
        labels_path.write_text(
            "amerob\tTurdus migratorius\tAmerican Robin\n",
            encoding="utf-8-sig",
        )

        assert parse_geomodel_labels(str(labels_path)) == [
            ("amerob", "Turdus migratorius", "American Robin")
        ]


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


class TestResolveToScientificNames:
    """Plural resolver: every scientific name denoting the same bird.

    Covers the taxonomy genus splits the model label set carries under two
    scientific names — the singular resolver returns only one, which blanks the
    detail/recording pages when a station's detections are stored under the
    other key. Two rows are the same bird when they share an English name *and*
    an epithet stem; both halves of that rule are pinned below.
    """

    def test_unique_common_name_returns_single(self):
        # No duplicate: identical to the singular resolver, one element.
        assert resolve_to_scientific_names('Common Ringed Plover') == [
            'Charadrius hiaticula'
        ]
        assert resolve_to_scientific_names('Common Blackbird') == ['Turdus merula']

    def test_duplicate_common_name_returns_all_keys(self):
        # "Little Ringed Plover" is two rows: Charadrius dubius (in_v2, the
        # commonly-detected bird) and Thinornis dubius (v3-only split). Both
        # must come back so a rollup keyed on either merges.
        result = resolve_to_scientific_names('Little Ringed Plover')
        assert set(result) == {'Charadrius dubius', 'Thinornis dubius'}

    def test_winner_is_listed_first(self):
        # The singular resolver's answer leads, so callers have a stable
        # representative that matches prior behavior.
        result = resolve_to_scientific_names('Little Ringed Plover')
        assert result[0] == resolve_to_scientific_name('Little Ringed Plover')

    def test_taxonomy_split_via_alias_resolves_all(self):
        # Shikra: Accipiter badius (V2) + Tachyspiza badia (V3), same bird.
        # Also pins gender re-agreement of the epithet (badius -> badia).
        assert set(resolve_to_scientific_names('Shikra')) == {
            'Accipiter badius',
            'Tachyspiza badia',
        }

    def test_split_merges_when_common_names_differ(self):
        # The pair is linked only by label_en/label_en_uk: Bubulcus ibis is
        # canonically "Cattle Egret" and Ardea ibis "Western Cattle Egret".
        # Grouping on canonical common_name alone missed these entirely, so a
        # station that upgraded V2 -> V3 saw its history split across two pages.
        for name in ('Cattle Egret', 'Western Cattle Egret'):
            assert set(resolve_to_scientific_names(name)) == {
                'Bubulcus ibis',
                'Ardea ibis',
            }, name

    def test_split_merges_when_legacy_row_has_no_english_name(self):
        # Charadrius nivosus carries no English common_name (its common_name is
        # the scientific name); only label_en ties it to "Snowy Plover".
        assert set(resolve_to_scientific_names('Snowy Plover')) == {
            'Anarhynchus nivosus',
            'Charadrius nivosus',
        }

    def test_split_merges_across_er_gender_agreement(self):
        # Cossypha caffra -> Dessonornis caffer: the -er/-ra Latin adjective
        # syncopates the masculine, so a raw epithet comparison misses it.
        assert set(resolve_to_scientific_names('Cape Robin-Chat')) == {
            'Cossypha caffra',
            'Dessonornis caffer',
        }

    def test_shared_common_name_alone_does_not_merge_distinct_species(self):
        # Two genuinely different birds share the label "Black Vulture"
        # (Coragyps atratus canonically, Aegypius monachus via label_en_uk).
        # Different epithets, so they must stay apart.
        assert resolve_to_scientific_names('Black Vulture') == ['Coragyps atratus']
        assert resolve_to_scientific_names('Cinereous Vulture') == [
            'Aegypius monachus'
        ]

    def test_shared_common_name_does_not_merge_split_sister_species(self):
        # "Gulf Coast Toad" names two live V3 classes that are separate taxa
        # post-split (Incilius nebulifer / valliceps); merging them would sum
        # two species into one detail card. Same for Rusty-breasted Whistler.
        assert len(resolve_to_scientific_names('Gulf Coast Toad')) == 1
        assert len(resolve_to_scientific_names('Rusty-breasted Whistler')) == 1
        assert len(resolve_to_scientific_names('Green-winged Teal')) == 1

    def test_group_is_symmetric_from_either_english_name(self):
        # Both English names of a split resolve to the same set, so which page
        # a user lands on doesn't change which detections they see.
        for left, right in (('Cattle Egret', 'Western Cattle Egret'),
                            ('Northern Goshawk', 'Eurasian Goshawk'),
                            ('Gray Goshawk', 'Grey Goshawk')):
            assert set(resolve_to_scientific_names(left)) == set(
                resolve_to_scientific_names(right)), (left, right)

    def test_result_has_no_duplicates(self):
        for name in ('Little Ringed Plover', 'Shikra', 'Common Blackbird',
                     'Cattle Egret', 'Snowy Plover'):
            result = resolve_to_scientific_names(name)
            assert len(result) == len(set(result))

    def test_unknown_and_empty_return_empty_list(self):
        assert resolve_to_scientific_names('Definitely Not A Real Bird') == []
        assert resolve_to_scientific_names('') == []
        assert resolve_to_scientific_names(None) == []
        assert resolve_to_scientific_names('   ') == []


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
