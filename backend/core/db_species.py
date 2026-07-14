"""Species identity expressions and the species rollup table.

The ``species`` table is a ~205-row rollup of per-species facts
(detection_count, first/last detection, newest display name, ebird code)
that would otherwise be re-derived from the million-row detections table
on every dashboard, catalog, or detail-page query.

Everything in it is derivable from ``detections``: ``rebuild()``
recomputes the whole table in one pass, and DatabaseManager's startup
consistency check auto-rebuilds on any drift — so the rollup can never
become an unrecoverable source of truth. Writers keep it current
incrementally: ``apply_insert``/``apply_delete`` run inside the same
transaction as the detections write they mirror. The one writer that
bypasses them (migration.py's bulk import) triggers a rebuild when it
finishes.

Species identity
----------------
Rows group by the species key: scientific_name, falling back to
common_name when scientific_name is empty. The fallback keeps legacy
migrated rows (blank Sci_Name in old BirdNET-Pi CSVs) from collapsing
into one bogus group, while letting V2/V3 English drift for the same
species ("Eurasian Blackbird"/"Common Blackbird", both Turdus merula)
merge into one entry. The newest detection's common_name is the display
representative, so upgrading models updates the shown name automatically.
"""
from core.logging_config import get_logger

logger = get_logger(__name__)


# SQL expression for the stable species grouping key.
SPECIES_KEY = "COALESCE(NULLIF(scientific_name, ''), common_name)"


def species_key_of(scientific_name, common_name):
    """Python twin of SPECIES_KEY for one detection's fields."""
    return scientific_name if scientific_name else common_name


def species_where(scientific_name, common_name):
    """(where_sql, params) selecting one species' detections by its key,
    shaped so the scientific/common composite indexes serve the lookup."""
    if scientific_name:
        return "scientific_name = ?", [scientific_name]
    return "scientific_name = '' AND common_name = ?", [common_name]


# Width of the zero-padded id packed into the latest key; comfortably above
# the 19 digits of a max int64, so the id stays fixed-width and recoverable.
_LATEST_KEY_ID_WIDTH = 20

# Packs a detection's timestamp and id into one lexically sortable string:
# MAX() over it yields the newest row, with id breaking exact-timestamp
# ties. char(31) sorts below '.' and every digit, so a variable-width
# (microsecond) timestamp still orders chronologically.
LATEST_KEY = (f"timestamp || char(31) || "
              f"printf('%0{_LATEST_KEY_ID_WIDTH}d', id)")


def latest_key_id_expr(key_expr: str) -> str:
    """SQL expression recovering the integer id packed by LATEST_KEY."""
    return f"CAST(substr({key_expr}, -{_LATEST_KEY_ID_WIDTH}) AS INTEGER)"


def ebird_expr(alias: str = "") -> str:
    """json_valid-guarded extraction of extra's ebird_code, optionally
    qualified with a table alias prefix (e.g. ``"d."``).

    extra is unconstrained text and Python reads deliberately tolerate
    malformed JSON (_parse_extra returns {}), so every SQL-side extraction
    must carry this guard — a bare json_extract THROWS on the first bad
    value, which during the startup rebuild would crash-loop the service.
    """
    return (f"CASE WHEN json_valid({alias}extra) "
            f"THEN json_extract({alias}extra, '$.ebird_code') END")


_EBIRD = ebird_expr()


# "The inserted row is newer than the rollup's current latest" — inserts
# can arrive out of order (bulk imports of history), so every newest-wins
# field checks rather than assumes. All CASEs evaluate against the
# pre-update row, per standard UPDATE semantics.
_NEWER = ("(excluded.last_detected > last_detected OR "
          "(excluded.last_detected = last_detected AND "
          "excluded.latest_id > latest_id))")

_UPSERT = f"""
INSERT INTO species (species_key, scientific_name, common_name, ebird_code,
                     detection_count, sum_confidence, first_detected,
                     last_detected, latest_id)
VALUES (:key, :sci, :common, :ebird, 1, :conf, :ts, :ts, :id)
ON CONFLICT(species_key) DO UPDATE SET
    detection_count = detection_count + 1,
    sum_confidence  = sum_confidence + excluded.sum_confidence,
    scientific_name = CASE WHEN excluded.scientific_name != ''
                           THEN excluded.scientific_name
                           ELSE scientific_name END,
    first_detected  = MIN(first_detected, excluded.first_detected),
    common_name     = CASE WHEN {_NEWER} THEN excluded.common_name
                           ELSE common_name END,
    ebird_code      = CASE WHEN {_NEWER} AND excluded.ebird_code IS NOT NULL
                           THEN excluded.ebird_code
                           ELSE COALESCE(ebird_code, excluded.ebird_code) END,
    last_detected   = CASE WHEN {_NEWER} THEN excluded.last_detected
                           ELSE last_detected END,
    latest_id       = CASE WHEN {_NEWER} THEN excluded.latest_id
                           ELSE latest_id END
"""


def _rederive_ebird(cursor, where, params, key):
    """Set the rollup's ebird_code to exactly what rebuild() derives:
    the latest row's code, else the newest row that has one, else NULL."""
    cursor.execute(
        f"""SELECT COALESCE(
            (SELECT {_EBIRD} FROM detections WHERE {where}
             ORDER BY timestamp DESC, id DESC LIMIT 1),
            (SELECT {_EBIRD} FROM detections WHERE {where}
             AND {_EBIRD} IS NOT NULL
             ORDER BY timestamp DESC, id DESC LIMIT 1))""",
        params + params)
    derived = cursor.fetchone()[0]
    cursor.execute(
        "UPDATE species SET ebird_code = ? WHERE species_key = ?",
        (derived, key))


def apply_insert(cursor, detection, detection_id, extra):
    """Roll a just-inserted detection into its species row. Must run on
    the same cursor/transaction as the detections INSERT. ``extra`` is the
    detection's parsed extra dict — this module owns knowing which of its
    fields the rollup tracks."""
    scientific_name = detection['scientific_name'] or ''
    common_name = detection['common_name']
    key = species_key_of(scientific_name, common_name)
    incoming_ebird = extra.get('ebird_code') if isinstance(extra, dict) else None
    cursor.execute(_UPSERT, {
        'key': key,
        'sci': scientific_name,
        'common': common_name,
        'ebird': incoming_ebird,
        'conf': detection['confidence'],
        'ts': detection['timestamp'],
        'id': detection_id,
    })

    if incoming_ebird is not None:
        # The upsert's keep-existing rule is only correct for in-order
        # inserts: an out-of-order code-bearing row may be newer than the
        # source of the stored code (which the rollup doesn't record), so
        # a conflicting stored value is ambiguous — re-derive it. One
        # primary-key read per code-bearing insert; the probes run only on
        # the rare conflict.
        cursor.execute("SELECT latest_id, ebird_code FROM species "
                       "WHERE species_key = ?", (key,))
        row = cursor.fetchone()
        if row[0] != detection_id and row[1] != incoming_ebird:
            where, params = species_where(scientific_name, common_name)
            _rederive_ebird(cursor, where, params, key)


def apply_delete(cursor, deleted):
    """Roll a just-deleted detection out of its species row. Must run on
    the same cursor/transaction as the detections DELETE (the boundary
    recomputes read the post-delete state).

    Incremental on purpose: re-deriving the whole row the way rebuild()
    does costs a full aggregate over the species' surviving rows — ~2s
    measured for a 143K-row species, per delete — so count/sum decrement
    in O(1) and only fields the deleted row could have defined get
    recomputed. Parity with rebuild() is pinned by
    test_incremental_matches_rebuild.

    ``deleted`` is the detection dict as it was before deletion. A missing
    species row means the rollup already drifted; leave it to the startup
    consistency check rather than guessing here.
    """
    scientific_name = deleted.get('scientific_name') or ''
    common_name = deleted['common_name']
    key = species_key_of(scientific_name, common_name)

    cursor.execute(
        "SELECT detection_count, latest_id, first_detected "
        "FROM species WHERE species_key = ?", (key,))
    row = cursor.fetchone()
    if row is None:
        return
    detection_count, latest_id, first_detected = row[0], row[1], row[2]

    if detection_count <= 1:
        cursor.execute("DELETE FROM species WHERE species_key = ?", (key,))
        return

    cursor.execute(
        "UPDATE species SET detection_count = detection_count - 1, "
        "sum_confidence = sum_confidence - ? WHERE species_key = ?",
        (deleted['confidence'], key))

    where, params = species_where(scientific_name, common_name)

    if deleted['id'] == latest_id:
        # The deleted row defined the newest-wins fields; take them from
        # the new latest row.
        cursor.execute(
            f"SELECT timestamp, id, common_name FROM detections "
            f"WHERE {where} ORDER BY timestamp DESC, id DESC LIMIT 1",
            params)
        new_latest = cursor.fetchone()  # count > 1, so a row remains
        cursor.execute(
            "UPDATE species SET last_detected = ?, latest_id = ?, "
            "common_name = ? WHERE species_key = ?",
            (new_latest[0], new_latest[1], new_latest[2], key))

    deleted_ebird = deleted.get('extra', {}).get('ebird_code') \
        if isinstance(deleted.get('extra'), dict) else None
    if deleted['id'] == latest_id or deleted_ebird is not None:
        # Unlike the other newest-wins fields, ebird_code can be sourced
        # from ANY row (the backfill rule), so deleting a non-latest row
        # that carried a code can orphan the rollup's value. A deleted
        # code-less, non-latest row can't change the derivation — skipped.
        _rederive_ebird(cursor, where, params, key)

    if deleted['timestamp'] == first_detected:
        cursor.execute(
            f"SELECT MIN(timestamp) FROM detections WHERE {where}", params)
        new_first = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE species SET first_detected = ? WHERE species_key = ?",
            (new_first, key))


def rebuild(cursor):
    """Recompute the whole rollup from detections in one grouped pass.

    The aggregate subquery packs each species' newest (timestamp, id) into
    a latest key; joining back on the recovered id fetches that newest
    row's display name and ebird code without a second sort. Species whose
    newest row predates ebird stamping get a bounded backfill probe.
    """
    cursor.execute("DELETE FROM species")
    cursor.execute(f"""
        INSERT INTO species (species_key, scientific_name, common_name,
                             ebird_code, detection_count, sum_confidence,
                             first_detected, last_detected, latest_id)
        SELECT s.species_key,
               s.scientific_name,
               d.common_name,
               {ebird_expr('d.')},
               s.detection_count,
               s.sum_confidence,
               s.first_detected,
               d.timestamp,
               d.id
        FROM (
            SELECT {SPECIES_KEY} AS species_key,
                   MAX(scientific_name) AS scientific_name,
                   COUNT(*) AS detection_count,
                   SUM(confidence) AS sum_confidence,
                   MIN(timestamp) AS first_detected,
                   MAX({LATEST_KEY}) AS latest_key
            FROM detections
            GROUP BY species_key
        ) s
        JOIN detections d ON d.id = {latest_key_id_expr('s.latest_key')}
    """)
    # Backfill: newest row that has a code, per key shape (sci-keyed
    # species correlate on scientific_name, legacy blank-sci on common)
    for species_filter, correlation in (
        ("scientific_name != ''",
         "d.scientific_name = species.scientific_name"),
        ("scientific_name = ''",
         "d.scientific_name = '' AND d.common_name = species.common_name"),
    ):
        cursor.execute(f"""
            UPDATE species SET ebird_code = (
                SELECT {ebird_expr('d.')} FROM detections d
                WHERE {correlation} AND {ebird_expr('d.')} IS NOT NULL
                ORDER BY d.timestamp DESC, d.id DESC LIMIT 1
            ) WHERE ebird_code IS NULL AND {species_filter}
        """)


def ensure_consistent(cursor):
    """Verify the rollup against detections; rebuild on any drift.

    The check is a cheap invariant (row counts must agree), not a full
    audit — apply_insert/apply_delete keep the details right, and anything
    that bypasses them (bulk import, manual edits, a restored backup from
    before this table existed) breaks the count and lands here.
    """
    cursor.execute("SELECT COUNT(*) FROM detections")
    detections_total = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(detection_count), 0) FROM species")
    rollup_total = cursor.fetchone()[0]

    if rollup_total != detections_total:
        logger.warning(
            f"Species rollup out of sync ({rollup_total} rolled up vs "
            f"{detections_total} detections) — rebuilding")
        rebuild(cursor)
