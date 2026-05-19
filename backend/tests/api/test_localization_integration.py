"""End-to-end localization tests for #47 / #48.

These pin the post-fix behavior: API responses reflect the user's
``display.bird_name_language`` setting, V2/V3 English drift for the same
species merges into single rows, and the bird-detail route resolves either
English variant to the full combined history for that scientific species.
"""

from unittest.mock import patch

import pytest


def _make_detection(*, common_name, scientific_name, timestamp,
                     confidence=0.9, group_timestamp=None):
    """Build a detection dict compatible with DatabaseManager.insert_detection."""
    return {
        'timestamp': timestamp,
        'group_timestamp': group_timestamp or timestamp,
        'scientific_name': scientific_name,
        'common_name': common_name,
        'confidence': confidence,
        'latitude': 0.0,
        'longitude': 0.0,
        'cutoff': 0.1,
        'sensitivity': 1.0,
        'overlap': 0.0,
        'extra': {},
        'audio_source': 'test_source',
    }


def _seed_blackbird_mixed_history(db):
    """Seed two detections for Turdus merula under both V2 and V3 English names."""
    db.insert_detection(_make_detection(
        common_name='Eurasian Blackbird',   # V2 inference label
        scientific_name='Turdus merula',
        timestamp='2025-06-15T10:00:00',
    ))
    db.insert_detection(_make_detection(
        common_name='Common Blackbird',     # V3 inference label
        scientific_name='Turdus merula',
        timestamp='2025-06-15T11:00:00',
    ))


def _patch_settings(language):
    """Return a patcher for load_user_settings that pins the given language."""
    settings = {
        'model': {'type': 'birdnet'},
        'display': {'bird_name_language': language},
    }
    return patch('core.api.load_user_settings', return_value=settings)


@pytest.fixture(autouse=True)
def _reset_label_caches():
    """Clear the lazily-loaded species table between tests."""
    from model_service.label_utils import clear_species_cache
    clear_species_cache()
    yield
    clear_species_cache()


class TestActivityOverviewMixedModelMerge:
    """A user with V2 history + V3 history sees ONE row per species."""

    def test_german_setting_translates_v2_history(self, api_client, real_db_manager):
        # V2-only detection: common_name is the V2 English string.
        real_db_manager.insert_detection(_make_detection(
            common_name='Eurasian Blackbird',
            scientific_name='Turdus merula',
            timestamp='2025-06-15T10:00:00',
        ))

        with _patch_settings('de'):
            response = api_client.get('/api/activity/overview?date=2025-06-15')
            assert response.status_code == 200
            data = response.get_json()

        merulas = [item for item in data if item['scientific_name'] == 'Turdus merula']
        assert len(merulas) == 1
        # Before the fix, displaySpecies would have stayed "Eurasian Blackbird"
        # because _common_to_idx had only V3's canonical "Common Blackbird".
        assert merulas[0]['displaySpecies'] == 'Amsel'

    def test_mixed_v2_v3_collapses_to_one_row(self, api_client, real_db_manager):
        _seed_blackbird_mixed_history(real_db_manager)

        with _patch_settings('de'):
            response = api_client.get('/api/activity/overview?date=2025-06-15')
            assert response.status_code == 200
            data = response.get_json()

        # Before the fix this returned two entries — one translated ("Amsel")
        # and one not ("Eurasian Blackbird"), matching the #48 screenshot.
        merulas = [item for item in data if item['scientific_name'] == 'Turdus merula']
        assert len(merulas) == 1
        assert merulas[0]['totalObservations'] == 2
        assert merulas[0]['displaySpecies'] == 'Amsel'


class TestBirdDetailsResolverIngress:
    """Both V2 and V3 English route params lead to the same combined history."""

    def test_v2_english_route_returns_full_history(self, api_client, real_db_manager):
        _seed_blackbird_mixed_history(real_db_manager)

        with _patch_settings('de'):
            response = api_client.get('/api/bird/Eurasian Blackbird')
            assert response.status_code == 200
            data = response.get_json()

        # Detail page combines V2 and V3 detections via scientific_name.
        assert data['scientific_name'] == 'Turdus merula'
        assert data['total_visits'] == 2
        assert data['display_common_name'] == 'Amsel'

    def test_v3_english_route_returns_full_history(self, api_client, real_db_manager):
        _seed_blackbird_mixed_history(real_db_manager)

        with _patch_settings('de'):
            response = api_client.get('/api/bird/Common Blackbird')
            assert response.status_code == 200
            data = response.get_json()

        assert data['scientific_name'] == 'Turdus merula'
        assert data['total_visits'] == 2
        assert data['display_common_name'] == 'Amsel'

    def test_unknown_english_falls_back_to_common_name_filter(
        self, api_client, real_db_manager
    ):
        # Legacy / fake species not in the species table. The resolver misses,
        # so the route falls back to filtering by common_name to preserve
        # access to migrated rows that the species table doesn't know about.
        real_db_manager.insert_detection(_make_detection(
            common_name='Some Legacy Migrated Bird',
            scientific_name='Fakeus birdus',
            timestamp='2025-06-15T10:00:00',
        ))

        with _patch_settings('en'):
            response = api_client.get('/api/bird/Some Legacy Migrated Bird')
            assert response.status_code == 200
            data = response.get_json()

        assert data['common_name'] == 'Some Legacy Migrated Bird'
        assert data['total_visits'] == 1


class TestBirdRecordingsResolverIngress:
    """V2 and V3 route params both produce the merged recording list."""

    def test_merges_recordings_across_english_variants(
        self, api_client, real_db_manager
    ):
        _seed_blackbird_mixed_history(real_db_manager)

        with _patch_settings('en'):
            v2 = api_client.get('/api/bird/Eurasian Blackbird/recordings')
            v3 = api_client.get('/api/bird/Common Blackbird/recordings')

        assert v2.status_code == 200
        assert v3.status_code == 200
        # Two detections total under one scientific_name; both routes see them.
        assert len(v2.get_json()) == 2
        assert len(v3.get_json()) == 2


class TestDashboardSummaryLocalization:
    """The mostCommonBird summary surface uses the resolved scientific_name."""

    def test_summary_localizes_most_common_bird(self, api_client, real_db_manager):
        # Three detections of one species so it wins "most common".
        for i in range(3):
            real_db_manager.insert_detection(_make_detection(
                common_name='Eurasian Blackbird',
                scientific_name='Turdus merula',
                timestamp=f'2025-06-15T1{i}:00:00',
            ))

        with _patch_settings('de'):
            response = api_client.get('/api/observations/summary')
            assert response.status_code == 200
            data = response.get_json()

        all_time = data['allTime']
        # The English fields keep V2's string (for backward-compat with any
        # consumer that reads them), but the Display field is localized.
        assert all_time['mostCommonBirdScientificName'] == 'Turdus merula'
        assert all_time['mostCommonBirdDisplay'] == 'Amsel'


class TestLatestDetectionsUniqueDeduplication:
    """The 'unique' toggle merges V2/V3 history (regression for the duplicate
    species row reported in #48)."""

    def test_unique_collapses_v2_v3_english_variants(
        self, api_client, real_db_manager
    ):
        _seed_blackbird_mixed_history(real_db_manager)

        with _patch_settings('de'):
            response = api_client.get('/api/dashboard')
            assert response.status_code == 200
            data = response.get_json()

        unique = data['recentObservations']['unique']
        merulas = [d for d in unique if d['scientific_name'] == 'Turdus merula']
        assert len(merulas) == 1
        # And the display name comes back localized.
        assert merulas[0]['display_common_name'] == 'Amsel'


class TestEmptyScientificNameLegacyRows:
    """Two legacy/migrated rows with blank scientific_name must NOT collapse
    into one. migration.py defaults Sci_Name to '' when the source CSV omits
    it, and the schema only enforces NOT NULL (not non-empty); a naive
    GROUP BY scientific_name would merge unrelated species under a single
    blank key."""

    def test_blank_sci_rows_stay_separate_in_activity_overview(
        self, api_client, real_db_manager
    ):
        real_db_manager.insert_detection(_make_detection(
            common_name='Legacy Bird A',
            scientific_name='',
            timestamp='2025-06-15T10:00:00',
        ))
        real_db_manager.insert_detection(_make_detection(
            common_name='Legacy Bird B',
            scientific_name='',
            timestamp='2025-06-15T11:00:00',
        ))

        with _patch_settings('en'):
            response = api_client.get('/api/activity/overview?date=2025-06-15')
            assert response.status_code == 200
            data = response.get_json()

        # Without the COALESCE(NULLIF(sci, ''), common) fallback both rows
        # would group under scientific_name = '' and become one entry.
        names = sorted(item['species'] for item in data)
        assert names == ['Legacy Bird A', 'Legacy Bird B']

    def test_blank_sci_rows_distinct_unique_species_count(
        self, api_client, real_db_manager
    ):
        real_db_manager.insert_detection(_make_detection(
            common_name='Legacy Bird A',
            scientific_name='',
            timestamp='2025-06-15T10:00:00',
        ))
        real_db_manager.insert_detection(_make_detection(
            common_name='Legacy Bird B',
            scientific_name='',
            timestamp='2025-06-15T11:00:00',
        ))

        with _patch_settings('en'):
            response = api_client.get('/api/observations/summary')
            assert response.status_code == 200
            data = response.get_json()

        # COUNT(DISTINCT COALESCE(...)) should treat the two as two species.
        assert data['allTime']['uniqueSpecies'] == 2
