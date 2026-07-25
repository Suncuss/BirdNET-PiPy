"""Utilities for parsing BirdNET label files and species lookups.

These are kept free of ML dependencies so they can be imported
by both the model service and the API server.
"""

import csv
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

_SPECIES_TABLE_PATH = os.path.join(
    os.path.dirname(__file__), 'models', 'species_table.csv'
)

# Columnar species store, populated by _ensure_loaded().
# Storing as parallel arrays keyed by row index keeps per-row dict overhead
# and duplicate-string allocations off the heap.
_sci_to_idx: dict[str, int] | None = None
_sci_names: list[str] | None = None
_common_to_idx: dict[str, int] | None = None
_common_names: list[str] | None = None
_synonym_to_idx: dict[str, int] | None = None
# scientific_name -> every scientific_name denoting the same bird, for the ~159
# species the label set carries twice after a taxonomy genus split (e.g.
# "Little Ringed Plover" = Charadrius dubius + Thinornis dubius). Detections can
# be stored under either key, so species-keyed reads must match them all.
# Only ambiguous species get an entry; unambiguous ones (the other ~11.4k) are
# absent and resolve to themselves — see _build_taxon_groups.
_sci_to_group: dict[str, tuple[str, ...]] | None = None
_in_v2: list[bool] | None = None
_in_v3: list[bool] | None = None
_loading_lock = threading.Lock()

# Per-language label arrays, loaded on first request for that language.
_lang_columns: dict[str, list[str]] = {}
_lang_lock = threading.Lock()


def _epithet_stem(sci_name: str) -> str:
    """Gender-neutral stem of a binomial's specific epithet.

    A genus rename keeps the epithet but may re-agree its gender with the new
    genus (``Accipiter badius`` -> ``Tachyspiza badia``, ``Cossypha caffra`` ->
    ``Dessonornis caffer``), so comparing raw epithets misses those pairs.
    Returns '' for anything that isn't a binomial, which never matches.
    """
    parts = sci_name.strip().split()
    if len(parts) < 2:
        return ''
    epithet = parts[-1].lower()
    # -er/-ra/-rum adjectives syncopate the masculine: caffer <-> caffra.
    if epithet.endswith('er') and len(epithet) - 2 >= 3:
        return epithet[:-2] + 'r'
    for suffix in ('us', 'um', 'is', 'a', 'e', 'i'):
        if epithet.endswith(suffix) and len(epithet) - len(suffix) >= 3:
            return epithet[:-len(suffix)]
    return epithet


def _build_taxon_groups(sci_names, name_to_idxs):
    """Group scientific names that denote one bird under a renamed genus.

    Two rows are the same bird when they share an English name *and* the same
    gender-neutral epithet stem. Requiring **both** is what separates a genus
    rename from a common-name collision:

    * ``Charadrius nivosus`` / ``Anarhynchus nivosus`` — linked only by the
      "Snowy Plover" label (their canonical common_names differ), same stem,
      so they merge. Matching on common_name alone missed these.
    * ``Coragyps atratus`` / ``Aegypius monachus`` — both labelled "Black
      Vulture", different stems, so they stay apart. Likewise ``Incilius
      nebulifer`` / ``Incilius valliceps`` ("Gulf Coast Toad"), two live V3
      classes. Matching on a shared name alone would have merged both.

    Returns ``{sci_name: (sci_name, ...)}`` holding only the ambiguous species
    (~159 of ~11.7k); everything else is absent and resolves to itself, which
    keeps this map ~30KB instead of a per-species entry.
    """
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    stems = [_epithet_stem(name) for name in sci_names]
    for idxs in name_to_idxs.values():
        if len(idxs) < 2:
            continue
        by_stem: dict[str, int] = {}
        for i in idxs:
            stem = stems[i]
            if not stem:
                continue
            first = by_stem.setdefault(stem, i)
            if first != i:
                root_a, root_b = find(first), find(i)
                if root_a != root_b:
                    parent[root_a] = root_b

    members: dict[int, list[int]] = {}
    for i in list(parent):
        members.setdefault(find(i), []).append(i)

    groups: dict[str, tuple[str, ...]] = {}
    for group in members.values():
        if len(group) < 2:
            continue
        names = tuple(sci_names[i] for i in sorted(group))
        for i in group:
            groups[sci_names[i]] = names
    return groups


def _ensure_loaded() -> None:
    """Load species metadata + index on first access (thread-safe).

    Reads the canonical columns plus ``label_en`` and ``label_en_uk`` to build
    a case-folded English-synonym index. Other ``label_*`` translation columns
    are loaded lazily by :func:`_ensure_language_loaded` on first request.
    """
    global _sci_to_idx, _sci_names, _common_to_idx, _common_names
    global _synonym_to_idx, _sci_to_group, _in_v2, _in_v3
    if _sci_to_idx is not None:
        return

    with _loading_lock:
        if _sci_to_idx is not None:
            return

        sci_to_idx: dict[str, int] = {}
        sci_names: list[str] = []
        common_to_idx: dict[str, int] = {}
        common_names: list[str] = []
        # casefold(english name) -> [row idx, ...], over canonical common_names
        # and label_en/label_en_uk alike. Feeds _build_taxon_groups after the
        # loop and is dropped afterwards; the synonym indexes below can't serve
        # that job because they keep only one idx per name.
        name_to_idxs: dict[str, list[int]] = {}
        in_v2: list[bool] = []
        in_v3: list[bool] = []
        # Collected during the row loop and merged afterwards so that
        # canonical common_names always shadow label_en / label_en_uk aliases
        # — without this, an earlier row's UK alias (e.g. Aegypius monachus
        # label_en_uk = "Black Vulture") would mis-route the canonical
        # "Black Vulture" (Coragyps atratus) by virtue of CSV row order.
        canonical_synonyms: dict[str, int] = {}
        alias_synonyms: dict[str, int] = {}

        try:
            with open(_SPECIES_TABLE_PATH, encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for idx, row in enumerate(reader):
                    sci = sys.intern(row['sci_name'])
                    sci_to_idx[sci] = idx
                    sci_names.append(sci)
                    common = sys.intern(row.get('common_name', ''))
                    common_names.append(common)
                    if common:
                        common_to_idx[common] = idx
                        # Canonical wins on collision: overwrite, not setdefault.
                        # Two rows sharing a canonical common_name would still
                        # collide here, but that's an authoritative ambiguity in
                        # the species table itself.
                        folded = common.casefold()
                        canonical_synonyms[folded] = idx
                        name_to_idxs.setdefault(folded, []).append(idx)
                    for col in ('label_en', 'label_en_uk'):
                        val = (row.get(col) or '').strip()
                        if val:
                            # Aliases use setdefault — first occurrence wins
                            # when nothing canonical claims the same key.
                            folded_alias = val.casefold()
                            alias_synonyms.setdefault(folded_alias, idx)
                            # All appends for one row are consecutive, so this
                            # dedupes label_en == common_name (the usual case).
                            seen_idxs = name_to_idxs.setdefault(folded_alias, [])
                            if not seen_idxs or seen_idxs[-1] != idx:
                                seen_idxs.append(idx)
                    in_v2.append(row.get('in_v2') == 'True')
                    in_v3.append(row.get('in_v3') == 'True')

            # Merge: aliases first, then canonical so canonical always wins.
            synonym_to_idx: dict[str, int] = {**alias_synonyms, **canonical_synonyms}
            sci_to_group = _build_taxon_groups(sci_names, name_to_idxs)
            logger.info(
                "Loaded species table",
                extra={
                    'species_count': len(sci_to_idx),
                    'synonym_count': len(synonym_to_idx),
                    'ambiguous_species_count': len(sci_to_group),
                },
            )
        except Exception:
            logger.exception("Failed to load species table from %s", _SPECIES_TABLE_PATH)
            synonym_to_idx = {}
            sci_to_group = {}

        _common_to_idx = common_to_idx
        _common_names = common_names
        _synonym_to_idx = synonym_to_idx
        _sci_to_group = sci_to_group
        _in_v2 = in_v2
        _in_v3 = in_v3
        _sci_names = sci_names
        _sci_to_idx = sci_to_idx


def _ensure_language_loaded(language: str) -> list[str] | None:
    """Load a single language column on demand.

    Returns the column array (idx -> translated name), or None if loading
    failed. The CSV is reread once per language; the OS page cache makes
    the second pass effectively free.
    """
    column = _lang_columns.get(language)
    if column is not None:
        return column

    with _lang_lock:
        column = _lang_columns.get(language)
        if column is not None:
            return column

        col_name = f'label_{language}'
        values: list[str] = []
        try:
            with open(_SPECIES_TABLE_PATH, encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                if col_name not in (reader.fieldnames or ()):
                    logger.warning(
                        "Requested language column missing",
                        extra={'language': language, 'column': col_name},
                    )
                    return None
                for row in reader:
                    values.append(sys.intern(row.get(col_name, '')))
            logger.info(
                "Loaded species language column",
                extra={'language': language, 'species_count': len(values)},
            )
        except Exception:
            logger.exception(
                "Failed to load language column %s from %s",
                col_name,
                _SPECIES_TABLE_PATH,
            )
            return None

        _lang_columns[language] = values
        return values


def clear_species_cache() -> None:
    """Reset the loaded species table. Used by tests."""
    global _sci_to_idx, _sci_names, _common_to_idx, _common_names
    global _synonym_to_idx, _sci_to_group, _in_v2, _in_v3
    _sci_to_idx = None
    _sci_names = None
    _common_to_idx = None
    _common_names = None
    _synonym_to_idx = None
    _sci_to_group = None
    _in_v2 = None
    _in_v3 = None
    _lang_columns.clear()


def _localized_at(idx: int | None, language: str) -> str | None:
    """Resolve the translation for a row index in a given language."""
    if idx is None:
        return None
    column = _ensure_language_loaded(language)
    if column is None:
        return None
    return column[idx] or None


def get_localized_name(sci_name: str, language: str) -> str | None:
    """Look up localized common name for a species.

    Returns None if species or language translation not found.
    """
    _ensure_loaded()
    return _localized_at(_sci_to_idx.get(sci_name), language)


def get_localized_name_from_english(common_name: str, language: str) -> str | None:
    """Look up localized name given an English common name.

    Returns None if species or translation not found.
    """
    _ensure_loaded()
    return _localized_at(_common_to_idx.get(common_name), language)


def resolve_to_scientific_name(name: str | None) -> str | None:
    """Resolve an English bird name to its canonical scientific name.

    Accepts any English variant carried by the species table: the canonical
    ``common_name`` (built from V3.1), the V2.4 English label (``label_en``),
    or the UK English variant (``label_en_uk``). Matching is case-insensitive
    and trims surrounding whitespace.

    Used at API ingress so a route param like ``/api/bird/Eurasian Blackbird``
    can be served by querying the DB on the stable ``Turdus merula`` key.
    Returns None for unknown names — callers should fall back to filtering by
    common_name to preserve access to legacy or migrated rows.
    """
    if not name:
        return None
    _ensure_loaded()
    idx = _synonym_to_idx.get(name.strip().casefold())
    return _sci_names[idx] if idx is not None else None


def resolve_to_scientific_names(name: str | None) -> list[str]:
    """Resolve an English bird name to *every* scientific name denoting it.

    Like :func:`resolve_to_scientific_name`, but for the ~159 species the model
    label set carries under two scientific names after a taxonomy genus split
    (e.g. "Little Ringed Plover" = ``Charadrius dubius`` + ``Thinornis
    dubius``) it returns both, not just the singular resolver's winner.
    Detections can be stored under either key — whichever the model emitted at
    the time — so species-keyed reads must match them all or the detail page
    blanks out on history the station really recorded.

    Siblings come from :func:`_build_taxon_groups`, which pairs rows on a
    shared English name *and* a matching epithet stem, so a common name two
    genuinely different birds share (e.g. "Black Vulture") does not merge them.

    The resolved winner (matching the singular resolver) is returned first for
    a stable representative; any siblings follow in CSV order. Returns an empty
    list for unknown names — callers fall back to filtering by common_name.
    """
    if not name:
        return []
    _ensure_loaded()
    idx = _synonym_to_idx.get(name.strip().casefold())
    if idx is None:
        return []
    primary = _sci_names[idx]
    siblings = _sci_to_group.get(primary)
    if not siblings:
        return [primary]
    return [primary] + [s for s in siblings if s != primary]


def same_taxon_group(sci_name: str | None) -> tuple[str, ...]:
    """Every scientific name denoting the same bird as ``sci_name``.

    A 1-tuple for the ~11.4k unambiguous species, the full set for the ~159 the
    label set carries twice after a genus rename. Unknown or unlisted names come
    back as a 1-tuple of themselves, so callers can group unconditionally
    without special-casing legacy or migrated rows. Both members of a group
    return the identical tuple, making ``group[0]`` a stable merge key.
    """
    if not sci_name:
        return ()
    _ensure_loaded()
    return _sci_to_group.get(sci_name) or (sci_name,)


def get_species_list(model_type: str) -> list[dict]:
    """Return species for a given model type.

    Returns list of dicts with 'scientific_name' and 'common_name' keys,
    sorted by common name.
    """
    from config.constants import ModelType

    _ensure_loaded()
    flags = _in_v3 if model_type == ModelType.BIRDNET_V3.value else _in_v2

    species = [
        {'scientific_name': sci, 'common_name': _common_names[idx]}
        for sci, idx in _sci_to_idx.items()
        if flags[idx]
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
    with open(path, encoding='utf-8-sig') as f:
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
    """Parse V3.1 semicolon-delimited CSV labels file.

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
