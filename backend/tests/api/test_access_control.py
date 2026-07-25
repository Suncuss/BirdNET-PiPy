"""Tests for the default-deny public-access model (auth/privacy redesign Phase 1).

Covers require_scope('public:read') gating, the public_access master switch
(login wall), the public_access kill-switch overriding per-feature flags, the
anonymous per-species recordings cap, and the station_name pre-auth leak fix.

These need auth ENABLED (the existing api_client fixture runs auth-disabled, so
every caller is 'owner' and the gating is inert) — see conftest.auth_enabled_app.
"""
import json
from unittest.mock import patch

import pytest

from tests.api.conftest import (
    DEFAULT_STATION_NAME,
    auth_enabled_app,
    insert_detection,
    iso_ago,
    login_owner,
)


def test_public_window_cutoff_day_aligned_for_table_signature_agreement():
    """The Detections table floors an anonymous start_date to YYYY-MM-DD and the
    DB re-expands it to ``<date>T00:00:00``, while the media-signature gate
    compares the full cutoff timestamp. They must resolve to the SAME instant,
    or boundary-day rows get shown to anonymous callers with unplayable
    (unsigned) media. Day-flooring the cutoff guarantees it."""
    from core.detection_presenter import _public_window_cutoff
    cutoff = _public_window_cutoff()
    assert cutoff == f'{cutoff[:10]}T00:00:00'


class TestPublicAccessGating:
    """require_scope('public:read') + the public_access master switch."""

    def test_anonymous_can_read_when_public_access_on(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, _):
            assert client.get('/api/species/all').status_code == 200
            assert client.get('/api/dashboard').status_code == 200
            assert client.get('/api/observations/recent').status_code == 200

    def test_species_all_ok_with_detections_when_auth_enabled(self, real_db_manager):
        """Regression: the Species Catalog is built off the request thread (the
        gallery single-flight cache). Deriving the request tier per row there hit
        Flask ``session`` with no request context and 500'd /api/species/all for
        EVERY auth-enabled install with data — owner and anonymous alike — and the
        failed build never warmed the cache, so every later request 500'd too. The
        empty-catalog case above masks it because no row is ever localized."""
        insert_detection(real_db_manager, timestamp=iso_ago(days_ago=1))
        with auth_enabled_app(real_db_manager) as (client, _):
            resp = client.get('/api/species/all')  # anonymous, cold cache
            assert resp.status_code == 200
            assert 'American Robin' in [s['common_name'] for s in resp.get_json()]
            login_owner(client)  # owner hit the same off-thread crash
            assert client.get('/api/species/all').status_code == 200

    def test_anonymous_blocked_when_public_access_off(self, real_db_manager):
        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            assert client.get('/api/species/all').status_code == 401
            assert client.get('/api/dashboard').status_code == 401
            assert client.get('/api/observations/recent').status_code == 401
            assert client.get('/api/bird/American%20Robin/recordings').status_code == 401

    def test_owner_reads_even_when_public_access_off(self, real_db_manager):
        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            login_owner(client)
            assert client.get('/api/species/all').status_code == 200
            assert client.get('/api/dashboard').status_code == 200

    def test_public_access_off_overrides_feature_flag(self, real_db_manager):
        """A feature flagged public is still blocked when the master switch is
        off — public_access is a true kill-switch over the *_public flags."""
        with auth_enabled_app(
            real_db_manager, access={'public_access': False, 'table_public': True},
        ) as (client, _):
            assert client.get('/api/detections').status_code == 401

    def test_table_public_works_when_public_access_on(self, real_db_manager):
        with auth_enabled_app(
            real_db_manager, access={'public_access': True, 'table_public': True},
        ) as (client, _):
            assert client.get('/api/detections').status_code == 200

    def test_table_public_windowed_for_anonymous(self, real_db_manager):
        """A published table shows logged-out viewers only the recent window
        (so no full-archive metadata and every visible row stays playable); the
        owner still sees the full history."""
        species = 'American Robin'
        for ts in (iso_ago(days_ago=1), iso_ago(days_ago=400)):  # one recent, one old
            insert_detection(real_db_manager, timestamp=ts, common_name=species)
        with auth_enabled_app(real_db_manager, access={'table_public': True}) as (client, _):
            anon = client.get('/api/detections').get_json()
            assert anon['pagination']['total_items'] == 1  # recent only
            login_owner(client)
            owner = client.get('/api/detections').get_json()
            assert owner['pagination']['total_items'] == 2  # full history

    def test_settings_access_accepts_public_access(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, settings_file):
            login_owner(client)
            resp = client.put('/api/settings/access',
                              data=json.dumps({'public_access': False}),
                              content_type='application/json')
            assert resp.status_code == 200
            with open(settings_file) as f:
                assert json.load(f)['access']['public_access'] is False


class TestStationNameLeak:
    """station_name must not leak to an anonymous visitor behind a login wall."""

    def test_hidden_behind_login_wall(self, real_db_manager):
        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            data = client.get('/api/auth/status').get_json()
            assert data['public_access'] is False
            assert data['station_name'] == ''
            assert data['public_features'] == []

    def test_shown_when_public_access_on(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, _):
            data = client.get('/api/auth/status').get_json()
            assert data['public_access'] is True
            assert data['station_name'] == DEFAULT_STATION_NAME

    def test_shown_to_authenticated_owner(self, real_db_manager):
        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            login_owner(client)
            data = client.get('/api/auth/status').get_json()
            assert data['station_name'] == DEFAULT_STATION_NAME


class TestAnonymousRecordingsCap:
    """Anonymous callers get a tighter per-species recordings slice than owners."""

    def _seed(self, db_manager, create_recording_files, species, count):
        for i in range(count):
            insert_detection(
                db_manager,
                timestamp=iso_ago(days_ago=i),  # all recent (within the public window)
                common_name=species,
                scientific_name='Corvus brachyrhynchos',
                confidence=0.80 + i * 0.001,
            )
        create_recording_files(db_manager, species_name=species)

    def test_anonymous_capped_owner_uncapped(self, real_db_manager, create_recording_files):
        from core.routes import media as api_module
        species = 'American Crow'
        self._seed(real_db_manager, create_recording_files, species, 8)

        with patch.object(api_module, 'RECORDINGS_PUBLIC_MAX', 5):
            with auth_enabled_app(real_db_manager) as (client, _):
                # Anonymous: clamped to the public cap.
                anon = client.get(f'/api/bird/{species}/recordings').get_json()
                assert len(anon) == 5
                # Owner: sees all (only the 500 hard ceiling applies).
                login_owner(client)
                owner = client.get(f'/api/bird/{species}/recordings').get_json()
                assert len(owner) == 8

    def test_anonymous_window_excludes_old_clips(self, real_db_manager, create_recording_files):
        """Anonymous recordings are recency-windowed — old all-time clips are not
        returned (even via 'best' sort) — while the owner sees the full history."""
        species = 'Blue Jay'
        for ts in (iso_ago(days_ago=1), iso_ago(days_ago=400)):  # one recent, one old
            insert_detection(real_db_manager, timestamp=ts, common_name=species,
                             scientific_name='Cyanocitta cristata')
        create_recording_files(real_db_manager, species_name=species)

        with auth_enabled_app(real_db_manager) as (client, _):
            anon = client.get(f'/api/bird/{species}/recordings?sort=best').get_json()
            assert len(anon) == 1  # only the recent clip, even under 'best' sort
            login_owner(client)
            owner = client.get(f'/api/bird/{species}/recordings?sort=best').get_json()
            assert len(owner) == 2


class TestMediaSignedUrls:
    """Anonymous media access requires a signed URL minted by a public payload."""

    def _seed_one(self, db_manager, create_recording_files, species='American Robin', days_ago=1):
        insert_detection(db_manager, timestamp=iso_ago(days_ago=days_ago), common_name=species)
        return create_recording_files(db_manager, species_name=species)[0]

    def test_anonymous_needs_signature_owner_does_not(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        rec = self._seed_one(real_db_manager, create_recording_files, species)
        audio_fn = rec['audio_filename']

        with auth_enabled_app(real_db_manager) as (client, _):
            # Bare deterministic filename is no longer enough for anonymous.
            assert client.get(f'/api/audio/{audio_fn}').status_code == 401

            # The bounded recordings payload carries a valid signed query.
            payload = client.get(f'/api/bird/{species}/recordings').get_json()
            assert 'audio_sig' in payload[0] and 'spectrogram_sig' in payload[0]
            assert client.get(
                f'/api/audio/{audio_fn}?{payload[0]["audio_sig"]}'
            ).status_code == 200

            # Owner needs no signature.
            login_owner(client)
            assert client.get(f'/api/audio/{audio_fn}').status_code == 200

    def test_valid_signature_works_alongside_a_dead_token(self, real_db_manager, create_recording_files):
        # The share-link viewer sends ?s=<token>&exp=..&sig=.. ; an expired or
        # garbage token must fall back to the signature on a public station
        # (rather than breaking media that would otherwise play).
        species = 'American Robin'
        rec = self._seed_one(real_db_manager, create_recording_files, species)
        audio_fn = rec['audio_filename']
        with auth_enabled_app(real_db_manager) as (client, _):
            sig = client.get(f'/api/bird/{species}/recordings').get_json()[0]['audio_sig']
            resp = client.get(f'/api/audio/{audio_fn}?s=garbage-token&{sig}')
            assert resp.status_code == 200

    def test_old_clip_gets_no_media_signature(self):
        """_add_media_signatures mints sigs only for in-window detections, so old
        clips surfaced by any payload carry no usable media URL (owners play via
        their session; share links carry the token)."""
        from core import detection_presenter as api_module
        from core import media_access
        recent = {'audio_filename': 'r.mp3', 'spectrogram_filename': 'r.webp', 'timestamp': iso_ago(days_ago=1)}
        old = {'audio_filename': 'o.mp3', 'spectrogram_filename': 'o.webp', 'timestamp': iso_ago(days_ago=400)}
        with patch.object(media_access, '_cached_secret', 'unit-secret'):
            api_module._add_media_signatures(recent)
            api_module._add_media_signatures(old)
        assert recent.get('audio_sig') and recent.get('spectrogram_sig')
        assert not old.get('audio_sig') and not old.get('spectrogram_sig')

    def test_sightings_unique_date_walk_windowed_for_anonymous(self, real_db_manager):
        """Anonymous can't date-walk old species-by-day metadata; the owner can."""
        old = iso_ago(days_ago=400)
        insert_detection(real_db_manager, timestamp=old)
        old_date = old.split('T')[0]
        with auth_enabled_app(real_db_manager) as (client, _):
            assert client.get(f'/api/sightings/unique?date={old_date}').get_json() == []
            login_owner(client)
            assert len(client.get(f'/api/sightings/unique?date={old_date}').get_json()) == 1

    def test_signature_rejected_when_public_access_off(self, real_db_manager, create_recording_files):
        from core.media_access import sign_media_query
        species = 'American Robin'
        rec = self._seed_one(real_db_manager, create_recording_files, species)
        audio_fn = rec['audio_filename']

        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            # Even a validly-signed URL is refused once the login wall is up.
            sig = sign_media_query(audio_fn)
            assert client.get(f'/api/audio/{audio_fn}?{sig}').status_code == 401
            assert client.get(f'/api/audio/{audio_fn}').status_code == 401


class TestShareLinks:
    """Per-detection share tokens: scoped to one detection, work behind the wall."""

    def _seed(self, db_manager, create_recording_files, species='American Robin', count=1, days_ago=1):
        for i in range(count):
            insert_detection(
                db_manager,
                timestamp=iso_ago(days_ago=days_ago, seconds=i),
                common_name=species,
                confidence=0.90 - i * 0.01,
            )
        return create_recording_files(db_manager, species_name=species)

    def test_token_opens_one_detection_on_private_station(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        rec = self._seed(real_db_manager, create_recording_files, species)[0]
        rid, audio_fn = rec['id'], rec['audio_filename']

        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            # Private station: no token -> permalink + media both denied.
            assert client.get(f'/api/bird/{species}/recording/{rid}').status_code == 404
            assert client.get(f'/api/audio/{audio_fn}').status_code == 401

            # Owner mints a share token.
            login_owner(client)
            minted = client.post(f'/api/detections/{rid}/share')
            assert minted.status_code == 200
            token = minted.get_json()['token']
            client.post('/api/auth/logout')  # back to anonymous

            # The token opens exactly this detection and its media, wall or not.
            detail = client.get(f'/api/bird/{species}/recording/{rid}?s={token}')
            assert detail.status_code == 200
            assert detail.get_json()['id'] == rid
            assert client.get(f'/api/audio/{audio_fn}?s={token}').status_code == 200

    def test_token_cannot_reach_other_detection(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        recs = self._seed(real_db_manager, create_recording_files, species, count=2)
        a, b = recs[0], recs[1]

        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            login_owner(client)
            token = client.post(f'/api/detections/{a["id"]}/share').get_json()['token']
            client.post('/api/auth/logout')

            assert client.get(f'/api/bird/{species}/recording/{a["id"]}?s={token}').status_code == 200
            # Same token, different id -> signed sub mismatch -> 404.
            assert client.get(f'/api/bird/{species}/recording/{b["id"]}?s={token}').status_code == 404
            # And it does not authorize the other detection's media.
            assert client.get(f'/api/audio/{b["audio_filename"]}?s={token}').status_code == 401

    def test_mint_requires_owner(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        rec = self._seed(real_db_manager, create_recording_files, species)[0]
        with auth_enabled_app(real_db_manager) as (client, _):
            # Anonymous cannot mint a share token.
            assert client.post(f'/api/detections/{rec["id"]}/share').status_code == 401

    def test_by_id_open_to_anonymous_when_public_access_on(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        rec = self._seed(real_db_manager, create_recording_files, species)[0]  # recent
        with auth_enabled_app(real_db_manager) as (client, _):  # public_access defaults on
            assert client.get(f'/api/bird/{species}/recording/{rec["id"]}').status_code == 200

    def test_old_detection_needs_token_even_when_public_access_on(self, real_db_manager, create_recording_files):
        """An out-of-window detection is 404 for anonymous without a token (no
        id-walking the historical archive), but a share token opens it + its media."""
        species = 'American Robin'
        rec = self._seed(real_db_manager, create_recording_files, species, days_ago=400)[0]
        rid, audio_fn = rec['id'], rec['audio_filename']

        with auth_enabled_app(real_db_manager) as (client, _):  # public_access ON
            # Anonymous, no token: outside the recent window -> 404.
            assert client.get(f'/api/bird/{species}/recording/{rid}').status_code == 404
            # And no signed media either (the payload it would need is denied).
            login_owner(client)
            token = client.post(f'/api/detections/{rid}/share').get_json()['token']
            client.post('/api/auth/logout')
            # The token bypasses the window for exactly this detection + its media.
            assert client.get(f'/api/bird/{species}/recording/{rid}?s={token}').status_code == 200
            assert client.get(f'/api/audio/{audio_fn}?s={token}').status_code == 200


class TestObservationsContract:
    """Public observation payloads honor the signed-media contract (audio_sig)."""

    def _seed(self, db_manager, species='American Robin'):
        insert_detection(db_manager, timestamp=iso_ago(days_ago=1), common_name=species)

    def test_latest_and_recent_include_media_signatures(self, real_db_manager):
        self._seed(real_db_manager)
        with auth_enabled_app(real_db_manager) as (client, _):
            latest = client.get('/api/observations/latest').get_json()
            assert latest and latest.get('audio_sig')
            recent = client.get('/api/observations/recent').get_json()
            assert recent and recent[0].get('audio_sig')


class TestDefaultDenyBackstop:
    """The before_request allowlist denies anonymous callers any non-allowlisted route."""

    def test_owner_only_endpoints_denied_for_anonymous(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, _):
            # Not in the anonymous allowlist -> blocked before the view runs.
            assert client.get('/api/system/logs').status_code == 401
            assert client.get('/api/recorder/status').status_code == 401

    def test_allowlist_has_no_stale_entries(self, real_db_manager):
        from core import api_infra as api_module
        with auth_enabled_app(real_db_manager) as (client, _):
            view_funcs = {name.rsplit('.', 1)[-1] for name in client.application.view_functions}
            missing = api_module._ANON_REACHABLE_ENDPOINTS - view_funcs
            assert not missing, f'stale allowlist entries: {missing}'

    def test_sensitive_endpoints_not_allowlisted(self):
        """No owner-only/destructive endpoint may be in the anonymous allowlist."""
        from core import api_infra as api_module
        sensitive = {
            'get_settings', 'update_settings', 'save_access_settings', 'export_detections_csv',
            'delete_detection', 'delete_detections_batch', 'create_share_link', 'auth_toggle',
            'auth_change_password', 'trigger_system_update', 'trigger_service_restart',
            'get_system_logs', 'get_recorder_status', 'migration_import', 'migration_validate',
            'upload_bird_image', 'delete_bird_image',
        }
        leaked = sensitive & api_module._ANON_REACHABLE_ENDPOINTS
        assert not leaked, f'sensitive endpoints in anonymous allowlist: {leaked}'

    def test_route_access_audit_catches_undeclared_route(self, real_db_manager):
        """The boot-time audit passes on the real route map (create_app already
        ran it) and rejects a route with neither a gate marker nor an allowlist
        entry — the drift class that silently 401'd the OG-card route."""
        from core import api_infra as api_module
        with auth_enabled_app(real_db_manager) as (client, _):
            app = client.application
            api_module._assert_route_access_declared(app)

            def rogue_route():
                return 'oops'
            app.view_functions['api.rogue_route'] = rogue_route
            try:
                with pytest.raises(RuntimeError, match='rogue_route'):
                    api_module._assert_route_access_declared(app)
            finally:
                del app.view_functions['api.rogue_route']

    def test_route_access_audit_catches_gate_allowlist_mismatch(self, real_db_manager):
        """Anonymous-reachable gate off the allowlist = dead decorator; the
        audit names it rather than letting the before_request silently 401."""
        from core import api_infra as api_module
        with auth_enabled_app(real_db_manager) as (client, _):
            app = client.application

            def half_public():
                return 'oops'
            half_public._access_gate = 'public:read'
            app.view_functions['api.half_public'] = half_public
            try:
                with pytest.raises(RuntimeError, match='half_public'):
                    api_module._assert_route_access_declared(app)
            finally:
                del app.view_functions['api.half_public']


class TestSystemInfoGating:
    """System info is readable in the public view but not behind the login wall."""

    # Assert the gate (401 vs. not-401) rather than handler success — the version/
    # storage handlers can return non-200 in the test env (no version.json), which
    # is irrelevant to whether the login wall blocks them.
    def test_readable_when_public_access_on(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, _):
            assert client.get('/api/system/version').status_code != 401
            assert client.get('/api/system/storage').status_code != 401

    def test_blocked_behind_login_wall(self, real_db_manager):
        with auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _):
            assert client.get('/api/system/version').status_code == 401
            assert client.get('/api/system/storage').status_code == 401
            login_owner(client)
            assert client.get('/api/system/version').status_code != 401

    def test_version_fingerprint_hidden_from_anonymous(self, real_db_manager):
        """The exact commit + branch (build fingerprint for CVE matching) are
        owner-only; the public view still gets version + runtime_mode so the
        background update check works without a login wall."""
        vinfo = {'version': '9.9.9', 'commit': 'deadbeef', 'commit_date': '2026-01-01',
                 'branch': 'main', 'remote_url': 'https://github.com/x/y'}
        with auth_enabled_app(real_db_manager) as (client, _):
            with patch('core.routes.system.get_runtime_mode', return_value='native'), \
                 patch('core.routes.system.load_version_info', return_value=vinfo):
                anon = client.get('/api/system/version').get_json()
                assert anon['version'] == '9.9.9'
                assert 'current_commit' not in anon
                assert 'current_branch' not in anon
                login_owner(client)
                owner = client.get('/api/system/version').get_json()
                assert owner['current_commit'] == 'deadbeef'
                assert owner['current_branch'] == 'main'


class TestExtraMetadataStripping:
    """Owner-only per-detection metadata (source_label, audio_source) is stripped
    from anonymous payloads but kept for the owner."""

    def _seed(self, db_manager, create_recording_files, species='American Robin'):
        insert_detection(
            db_manager, timestamp=iso_ago(days_ago=1), common_name=species,
            extra={'source_label': 'Backyard Mic', 'weather': {'code': 0}},
        )
        return create_recording_files(db_manager, species_name=species)[0]

    def test_by_id_strips_source_label_for_anonymous_keeps_for_owner(self, real_db_manager, create_recording_files):
        species = 'American Robin'
        rid = self._seed(real_db_manager, create_recording_files, species)['id']
        with auth_enabled_app(real_db_manager) as (client, _):
            anon = client.get(f'/api/bird/{species}/recording/{rid}').get_json()
            assert 'source_label' not in (anon.get('extra') or {})
            assert (anon.get('extra') or {}).get('weather')   # weather kept
            assert 'audio_source' not in anon

            login_owner(client)
            owner = client.get(f'/api/bird/{species}/recording/{rid}').get_json()
            assert owner['extra'].get('source_label') == 'Backyard Mic'

    def test_dashboard_strips_source_label_for_anonymous(self, real_db_manager):
        insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=1),
            extra={'source_label': 'Backyard Mic', 'weather': {'code': 1}},
        )
        with auth_enabled_app(real_db_manager) as (client, _):
            recent = client.get('/api/dashboard').get_json()['recentObservations']['all']
            assert recent and 'source_label' not in (recent[0].get('extra') or {})
