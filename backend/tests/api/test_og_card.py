"""Tests for the server-rendered Open Graph card used by link-unfurl crawlers
(iMessage/LinkPresentation, Slack, Discord, …) on detection share permalinks.

nginx routes only crawler user-agents to /api/og/recording/<id>; this endpoint
returns a tiny HTML doc whose <head> carries per-detection OG/Twitter tags so a
shared link previews as a titled card instead of a bare URL.
"""


def _insert_detection(db, **overrides):
    detection = {
        'timestamp': '2024-01-15T10:30:00',
        'group_timestamp': '2024-01-15T10:30:00',
        'common_name': 'American Robin',
        'scientific_name': 'Turdus migratorius',
        'confidence': 0.85,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25,
    }
    detection.update(overrides)
    return db.insert_detection(detection)


class TestOgCard:
    def test_renders_per_detection_card(self, api_client, real_db_manager):
        rec_id = _insert_detection(real_db_manager)

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        assert resp.status_code == 200
        assert resp.mimetype == 'text/html'
        body = resp.get_data(as_text=True)
        # Per-detection Open Graph tags the unfurler reads.
        assert 'property="og:title" content="American Robin"' in body
        assert 'property="og:description"' in body
        assert '85% confidence' in body
        assert 'Turdus migratorius' in body
        # Canonical share URL points back at the SPA route, not the API path.
        expected = f'http://localhost/bird/American%20Robin/recording/{rec_id}'
        assert f'property="og:url" content="{expected}"' in body
        assert f'rel="canonical" href="{expected}"' in body

    def test_missing_detection_falls_back_to_branded_card(self, api_client):
        # A deleted/stale id still previews — generic branded card, no crash.
        resp = api_client.get('/api/og/recording/999999')

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'BirdNET-PiPy' in body
        assert 'property="og:url" content="http://localhost/"' in body

    def test_honors_forwarded_host_and_proto(self, api_client, real_db_manager):
        # Behind a TLS-terminating proxy/tunnel, absolute URLs must use the
        # externally requested scheme+host (forwarded by nginx), not the inner
        # http://localhost — else iMessage can't fetch og:url.
        rec_id = _insert_detection(real_db_manager)

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
        rec_id = _insert_detection(
            real_db_manager, common_name='Evil "Bird" <script>',
            scientific_name='Malus injectus',
        )

        resp = api_client.get(f'/api/og/recording/{rec_id}')

        body = resp.get_data(as_text=True)
        assert '<script>' not in body
        assert '&lt;script&gt;' in body
        assert '&quot;Bird&quot;' in body
