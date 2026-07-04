"""Tests for the server-rendered Open Graph card used by link-unfurl crawlers
(iMessage/LinkPresentation, Slack, Discord, …) on detection share permalinks.

nginx routes only crawler user-agents to /api/og/recording/<id>; this endpoint
returns a tiny HTML doc whose <head> carries per-detection OG/Twitter tags so a
shared link previews as a titled card instead of a bare URL.
"""
from tests.api.conftest import auth_enabled_app, insert_detection, iso_ago, login_owner


class TestOgCard:
    def test_renders_per_detection_card(self, api_client, real_db_manager):
        rec_id = insert_detection(real_db_manager, confidence=0.85)

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        assert resp.status_code == 200
        assert resp.mimetype == 'text/html'
        body = resp.get_data(as_text=True)
        # Per-detection Open Graph tags the unfurler reads. The title leads with
        # the app and the species (iMessage's no-image card mostly shows this).
        assert ('property="og:title" '
                'content="BirdNET-PiPy overheard an American Robin"') in body
        assert 'property="og:description"' in body
        assert '85% confidence' in body
        assert 'Turdus migratorius' in body
        # Canonical share URL points back at the SPA route, not the API path.
        expected = f'http://localhost/bird/American%20Robin/recording/{rec_id}'
        assert f'property="og:url" content="{expected}"' in body
        assert f'rel="canonical" href="{expected}"' in body
        # A branded image upgrades the card to a large-thumbnail preview.
        assert ('property="og:image" '
                'content="http://localhost/default_bird.png"') in body
        assert 'name="twitter:card" content="summary_large_image"' in body

    def test_missing_detection_falls_back_to_branded_card(self, api_client):
        # A deleted/stale id still previews — generic branded card, no crash.
        resp = api_client.get('/api/og/recording/999999')

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'BirdNET-PiPy' in body
        assert 'property="og:url" content="http://localhost/"' in body
        # Fallback card is still a rich image card.
        assert ('property="og:image" '
                'content="http://localhost/default_bird.png"') in body

    def test_og_image_uses_forwarded_origin(self, api_client, real_db_manager):
        # The image URL must resolve to the external origin too, else the crawler
        # fetches it from the wrong host (or an unreachable inner localhost).
        rec_id = insert_detection(real_db_manager)

        resp = api_client.get(
            f'/api/og/recording/{rec_id}',
            headers={'X-Forwarded-Proto': 'https',
                     'X-Forwarded-Host': 'birds.example.com'},
        )

        body = resp.get_data(as_text=True)
        assert ('property="og:image" '
                'content="https://birds.example.com/default_bird.png"') in body

    def test_honors_forwarded_host_and_proto(self, api_client, real_db_manager):
        # Behind a TLS-terminating proxy/tunnel, absolute URLs must use the
        # externally requested scheme+host (forwarded by nginx), not the inner
        # http://localhost — else iMessage can't fetch og:url.
        rec_id = insert_detection(real_db_manager)

        resp = api_client.get(
            f'/api/og/recording/{rec_id}',
            headers={'X-Forwarded-Proto': 'https',
                     'X-Forwarded-Host': 'birds.example.com'},
        )

        body = resp.get_data(as_text=True)
        expected = f'https://birds.example.com/bird/American%20Robin/recording/{rec_id}'
        assert f'property="og:url" content="{expected}"' in body

    def test_escapes_html_in_fields(self, api_client, real_db_manager):
        # Species names are reflected into HTML attributes; they must be escaped.
        rec_id = insert_detection(
            real_db_manager, common_name='Evil "Bird" <script>',
            scientific_name='Malus injectus',
        )

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        body = resp.get_data(as_text=True)
        assert '<script>' not in body
        assert '&lt;script&gt;' in body
        assert '&quot;Bird&quot;' in body

    def test_description_omits_audio_source(self, api_client, real_db_manager):
        # The audio source is an internal label, not something a link recipient
        # should see — it must not leak into the shared card.
        rec_id = insert_detection(real_db_manager, audio_source='source_3')

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        body = resp.get_data(as_text=True)
        assert 'source_3' not in body

    def test_title_uses_an_before_vowel(self, api_client, real_db_manager):
        # Unknown scientific_name so the localizer falls back to common_name
        # (the displayed name is otherwise resolved from the species DB).
        rec_id = insert_detection(
            real_db_manager, common_name='Eastern Bluebird',
            scientific_name='Testus vowelis',
        )

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        body = resp.get_data(as_text=True)
        assert 'content="BirdNET-PiPy overheard an Eastern Bluebird"' in body

    def test_title_uses_a_before_eu_word(self, api_client, real_db_manager):
        # 'Eu-' species read with a 'y' glide: "a European Starling", not "an".
        rec_id = insert_detection(
            real_db_manager, common_name='European Starling',
            scientific_name='Testus euensis',
        )

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        body = resp.get_data(as_text=True)
        assert 'content="BirdNET-PiPy overheard a European Starling"' in body

    def test_rejects_forged_forwarded_host(self, api_client, real_db_manager):
        # X-Forwarded-Host is client-controlled (nginx copies the client's own
        # Host header into it); anything but a plain host[:port] degrades to
        # the request's own host instead of planting a foreign URL on the card.
        rec_id = insert_detection(real_db_manager)

        resp = api_client.get(
            f'/api/og/recording/{rec_id}',
            headers={'X-Forwarded-Proto': 'javascript',
                     'X-Forwarded-Host': 'evil.example/phish?x='},
        )

        body = resp.get_data(as_text=True)
        assert 'evil.example' not in body
        assert 'javascript' not in body
        assert ('property="og:image" '
                'content="http://localhost/default_bird.png"') in body


class TestOgCardAccess:
    """With auth enabled, the card's detail mirrors the by-id permalink gate:
    owner / share token / public recent window see species detail; everyone
    else gets the generic branded card — identical for denied and nonexistent
    ids, so the route is not an id-walk existence oracle."""

    def _generic_body(self, client):
        return client.get('/api/og/recording/999999').get_data(as_text=True)

    def test_anonymous_in_window_gets_detailed_card(self, real_db_manager):
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=1),
        )
        with auth_enabled_app(real_db_manager) as (client, _):
            resp = client.get(f'/api/og/recording/{rec_id}')

            assert resp.status_code == 200
            assert 'American Robin' in resp.get_data(as_text=True)

    def test_anonymous_out_of_window_gets_generic_card(self, real_db_manager):
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=45),
        )
        with auth_enabled_app(real_db_manager) as (client, _):
            resp = client.get(f'/api/og/recording/{rec_id}')

            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert 'American Robin' not in body
            # Byte-identical to a nonexistent id: no existence oracle.
            assert body == self._generic_body(client)

    def test_anonymous_behind_login_wall_gets_generic_card(self, real_db_manager):
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=1),
        )
        with auth_enabled_app(
            real_db_manager, access={'public_access': False},
        ) as (client, _):
            resp = client.get(f'/api/og/recording/{rec_id}')

            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert 'American Robin' not in body
            assert body == self._generic_body(client)

    def test_share_token_reveals_detail_even_on_private_station(self, real_db_manager):
        # Out-of-window AND public_access off — the share token alone entitles
        # the crawler to this one detection's card (nginx forwards ?s= through).
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=45),
        )
        with auth_enabled_app(
            real_db_manager, access={'public_access': False},
        ) as (client, _):
            login_owner(client)
            token = client.post(f'/api/detections/{rec_id}/share').get_json()['token']
            client.post('/api/auth/logout')

            resp = client.get(f'/api/og/recording/{rec_id}?s={token}')

            assert 'American Robin' in resp.get_data(as_text=True)

    def test_forged_share_token_gets_generic_card(self, real_db_manager):
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=45),
        )
        with auth_enabled_app(real_db_manager) as (client, _):
            resp = client.get(f'/api/og/recording/{rec_id}?s=forged-token')

            assert resp.status_code == 200
            assert 'American Robin' not in resp.get_data(as_text=True)

    def test_owner_sees_detail_regardless_of_window(self, real_db_manager):
        rec_id = insert_detection(
            real_db_manager, timestamp=iso_ago(days_ago=45),
        )
        with auth_enabled_app(real_db_manager) as (client, _):
            login_owner(client)

            resp = client.get(f'/api/og/recording/{rec_id}')

            assert 'American Robin' in resp.get_data(as_text=True)
