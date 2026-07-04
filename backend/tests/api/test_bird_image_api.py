"""Tests for custom bird image upload/serve/delete endpoints."""

import io
import json
import os
import tempfile
from unittest.mock import patch

import pytest

# JPEG magic bytes (smallest valid JPEG header)
JPEG_HEADER = b'\xff\xd8\xff\xe0' + b'\x00' * 100
PNG_HEADER = b'\x89PNG' + b'\x00' * 100
GIF_HEADER = b'GIF89a' + b'\x00' * 100
WEBP_HEADER = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 100


class TestBirdImageUpload:
    """Test POST /api/bird/<species_name>/image endpoint."""

    @pytest.fixture
    def image_client(self):
        """Create a test client with temporary bird images directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    def test_upload_valid_jpeg(self, image_client):
        """Upload a valid JPEG image."""
        client, images_dir = image_client
        data = {'file': (io.BytesIO(JPEG_HEADER), 'bird.jpg')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 200
        assert response.get_json()['hasCustomImage'] is True

        # Verify file was saved
        assert os.path.exists(os.path.join(images_dir, 'American_Robin.jpg'))

    def test_upload_valid_png(self, image_client):
        """Upload a valid PNG image."""
        client, images_dir = image_client
        data = {'file': (io.BytesIO(PNG_HEADER), 'bird.png')}
        response = client.post(
            '/api/bird/House Sparrow/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 200
        assert os.path.exists(os.path.join(images_dir, 'House_Sparrow.png'))

    def test_upload_rejects_no_file(self, image_client):
        """Upload with no file field returns 400."""
        client, _ = image_client
        response = client.post(
            '/api/bird/American Robin/image',
            data={},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'No file' in response.get_json()['error']

    def test_upload_rejects_empty_file(self, image_client):
        """Upload with empty file returns 400."""
        client, _ = image_client
        data = {'file': (io.BytesIO(b''), 'bird.jpg')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'empty' in response.get_json()['error']

    def test_upload_rejects_invalid_extension(self, image_client):
        """Upload with non-image extension returns 400."""
        client, _ = image_client
        data = {'file': (io.BytesIO(b'not an image'), 'bird.txt')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'Invalid file type' in response.get_json()['error']

    def test_upload_rejects_oversized_file(self, image_client):
        """Upload file > 10MB returns 400."""
        client, _ = image_client
        # Create data larger than 10MB with valid JPEG header
        large_data = JPEG_HEADER + b'\x00' * (11 * 1024 * 1024)
        data = {'file': (io.BytesIO(large_data), 'bird.jpg')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'too large' in response.get_json()['error']

    def test_upload_rejects_wrong_magic_bytes(self, image_client):
        """Upload file with .jpg extension but non-image content returns 400."""
        client, _ = image_client
        data = {'file': (io.BytesIO(b'This is just text content!!!'), 'bird.jpg')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'valid image' in response.get_json()['error']

    def test_upload_replaces_existing_different_extension(self, image_client):
        """Uploading a new image deletes old image with different extension."""
        client, images_dir = image_client

        # Upload PNG first
        data = {'file': (io.BytesIO(PNG_HEADER), 'bird.png')}
        client.post('/api/bird/American Robin/image', data=data, content_type='multipart/form-data')
        assert os.path.exists(os.path.join(images_dir, 'American_Robin.png'))

        # Upload JPEG (should replace PNG)
        data = {'file': (io.BytesIO(JPEG_HEADER), 'bird.jpg')}
        response = client.post('/api/bird/American Robin/image', data=data, content_type='multipart/form-data')
        assert response.status_code == 200

        # New file exists, old is gone
        assert os.path.exists(os.path.join(images_dir, 'American_Robin.jpg'))
        assert not os.path.exists(os.path.join(images_dir, 'American_Robin.png'))

    def test_upload_requires_auth_when_enabled(self, image_client):
        """Upload returns 401 when auth is enabled and not logged in."""
        client, _ = image_client

        # Enable auth
        client.post('/api/auth/setup',
                    data=json.dumps({'password': 'testpass123'}),
                    content_type='application/json')
        client.post('/api/auth/logout')

        # Try to upload - should fail
        data = {'file': (io.BytesIO(JPEG_HEADER), 'bird.jpg')}
        response = client.post(
            '/api/bird/American Robin/image',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 401


class TestBirdImageServe:
    """Test GET /api/bird/<species_name>/image endpoint."""

    @pytest.fixture
    def image_client_with_file(self):
        """Create a test client with a pre-existing bird image."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
                    f.write(JPEG_HEADER)
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    def test_serve_existing_image(self, image_client_with_file):
        """Serving an existing custom image returns 200 with file content."""
        client, _ = image_client_with_file
        response = client.get('/api/bird/American Robin/image')
        assert response.status_code == 200
        assert len(response.data) > 0

    def test_serve_nonexistent_image_returns_404(self, image_client_with_file):
        """Serving a non-existent custom image returns 404."""
        client, _ = image_client_with_file
        response = client.get('/api/bird/Nonexistent Bird/image')
        assert response.status_code == 404


class TestBirdImageDelete:
    """Test DELETE /api/bird/<species_name>/image endpoint."""

    @pytest.fixture
    def image_client_with_file(self):
        """Create a test client with a pre-existing bird image."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
                    f.write(JPEG_HEADER)
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    def test_delete_existing_image(self, image_client_with_file):
        """Deleting an existing image returns 200 and removes the file."""
        client, images_dir = image_client_with_file
        assert os.path.exists(os.path.join(images_dir, 'American_Robin.jpg'))

        response = client.delete('/api/bird/American Robin/image')
        assert response.status_code == 200
        assert response.get_json()['hasCustomImage'] is False
        assert not os.path.exists(os.path.join(images_dir, 'American_Robin.jpg'))

    def test_delete_nonexistent_is_idempotent(self, image_client_with_file):
        """Deleting a non-existent image still returns 200 (idempotent)."""
        client, _ = image_client_with_file
        response = client.delete('/api/bird/Nonexistent Bird/image')
        assert response.status_code == 200
        assert response.get_json()['hasCustomImage'] is False

    def test_delete_requires_auth_when_enabled(self, image_client_with_file):
        """Delete returns 401 when auth is enabled and not logged in."""
        client, _ = image_client_with_file

        # Enable auth
        client.post('/api/auth/setup',
                    data=json.dumps({'password': 'testpass123'}),
                    content_type='application/json')
        client.post('/api/auth/logout')

        response = client.delete('/api/bird/American Robin/image')
        assert response.status_code == 401


class TestWikimediaHasCustomImage:
    """Test that wikimedia endpoint includes hasCustomImage field."""

    @pytest.fixture
    def image_client(self):
        """Create test client with custom images dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    @patch('core.api.fetch_wikimedia_image')
    def test_wikimedia_returns_has_custom_image_false(self, mock_fetch, image_client):
        """Wikimedia endpoint returns hasCustomImage: false when no custom image."""
        client, _ = image_client
        mock_fetch.return_value = ({
            'imageUrl': 'https://example.com/robin.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'John',
            'authorUrl': 'https://example.com',
            'licenseType': 'CC BY-SA'
        }, None)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['hasCustomImage'] is False

    @patch('core.api.fetch_wikimedia_image')
    def test_wikimedia_returns_has_custom_image_true(self, mock_fetch, image_client):
        """Wikimedia endpoint returns hasCustomImage: true when custom image exists."""
        client, images_dir = image_client

        # Create a custom image
        with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
            f.write(JPEG_HEADER)

        mock_fetch.return_value = ({
            'imageUrl': 'https://example.com/robin.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'John',
            'authorUrl': 'https://example.com',
            'licenseType': 'CC BY-SA'
        }, None)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['hasCustomImage'] is True

    @patch('core.api.fetch_wikimedia_image')
    def test_wikimedia_error_with_custom_image_returns_200(self, mock_fetch, image_client):
        """When wikimedia fails but custom image exists, return 200 with hasCustomImage."""
        client, images_dir = image_client

        # Create a custom image
        with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
            f.write(JPEG_HEADER)

        mock_fetch.return_value = (None, {'message': 'No results found', 'status': 404, 'retry_after': None})

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['hasCustomImage'] is True

    @patch('core.api.fetch_wikimedia_image')
    def test_for_display_only_skips_fetch_when_custom_exists(self, mock_fetch, image_client):
        """Gallery's for_display_only=1: a custom upload short-circuits the WMF lookup."""
        client, images_dir = image_client
        with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
            f.write(JPEG_HEADER)

        response = client.get('/api/wikimedia_image',
                              query_string={'species': 'American Robin', 'for_display_only': '1'})
        assert response.status_code == 200
        assert response.get_json()['hasCustomImage'] is True
        mock_fetch.assert_not_called()

    @patch('core.api.fetch_wikimedia_image')
    def test_without_for_display_only_still_fetches_with_custom(self, mock_fetch, image_client):
        """Without the flag (e.g. BirdDetails) the WMF lookup still runs for metadata."""
        client, images_dir = image_client
        with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
            f.write(JPEG_HEADER)
        mock_fetch.return_value = ({
            'imageUrl': 'https://upload.wikimedia.org/r.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:R.jpg',
            'authorName': 'J', 'authorUrl': None, 'licenseType': 'CC'
        }, None)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        mock_fetch.assert_called_once()

    @patch('core.api.fetch_wikimedia_image')
    def test_429_propagates_status_and_retry_after_header(self, mock_fetch, image_client):
        """A 429 from upstream is surfaced (not collapsed to 500) with Retry-After."""
        client, _ = image_client
        mock_fetch.return_value = (None, {'message': 'Rate limited by Wikimedia', 'status': 429, 'retry_after': 42.0})

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 429
        assert response.headers.get('Retry-After') == '42'


class TestFilenameSanitization:
    """Test filename sanitization for various species names."""

    def test_sanitize_basic_name(self):
        from core.api import _sanitize_species_filename
        assert _sanitize_species_filename('American Robin') == 'American_Robin'

    def test_sanitize_apostrophe(self):
        from core.api import _sanitize_species_filename
        assert _sanitize_species_filename("Cooper's Hawk") == 'Cooper_s_Hawk'

    def test_sanitize_special_chars(self):
        from core.api import _sanitize_species_filename
        result = _sanitize_species_filename('Bird (subspecies) - variant')
        assert '..' not in result
        assert '/' not in result
        assert ' ' not in result

    def test_sanitize_multiple_spaces(self):
        from core.api import _sanitize_species_filename
        result = _sanitize_species_filename('Some   Bird   Name')
        assert '__' not in result


def _imageinfo(url, *, thumburl=None, author='Unknown', license_name='CC0'):
    """Build a single Wikimedia imageinfo entry for tests. Keeps test bodies focused on intent."""
    entry = {
        'url': url,
        'extmetadata': {
            'LicenseShortName': {'value': license_name},
            'Artist': {'value': author},
        },
    }
    if thumburl is not None:
        entry['thumburl'] = thumburl
    return entry


def _fake_wikimedia_get(*, search_results, imageinfo_pages, capture=None):
    """Build a fake `requests.get` for Wikimedia API calls.

    `search_results` is the list assigned to `query.search`; `imageinfo_pages` is the
    `query.pages` dict. Pass a dict for `capture` to record the imageinfo call's params.
    """
    class _R:
        status_code = 200
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    def fake_get(url, params=None, headers=None, timeout=None):
        if params.get('list') == 'search':
            return _R({'query': {'search': search_results}})
        if capture is not None:
            capture['imageinfo_params'] = dict(params)
        return _R({'query': {'pages': imageinfo_pages}})
    return fake_get


def _make_client(tmpdir):
    """Build a test client wired to a tmp images dir; reused across the wikimedia-choice tests."""
    images_dir = os.path.join(tmpdir, 'bird_images')
    os.makedirs(images_dir, exist_ok=True)
    patches = (
        patch('core.auth.AUTH_CONFIG_DIR', tmpdir),
        patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')),
        patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')),
        patch('core.api.CUSTOM_BIRD_IMAGES_DIR', images_dir),
        patch('core.api.db_manager'),
        patch('core.api.socketio'),
    )
    for p in patches:
        p.start()
    from core.api import create_app
    app, _ = create_app()
    app.config['TESTING'] = True
    return app, images_dir, patches


class TestWikimediaCandidates:
    """Test GET /api/wikimedia_image/candidates."""

    @pytest.fixture
    def candidates_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()
                # Clear the in-process Wikimedia cache between tests so cache-key
                # assertions and mocked fetches are deterministic.
                from core.api import image_cache
                image_cache.clear()

    @patch('core.api.fetch_wikimedia_candidates')
    def test_candidates_returns_list(self, mock_fetch, candidates_client):
        client, _ = candidates_client
        mock_fetch.return_value = ([
            {'fileTitle': 'File:A.jpg', 'imageUrl': 'https://upload.wikimedia.org/A.jpg',
             'pageUrl': 'https://commons.wikimedia.org/wiki/File:A.jpg',
             'authorName': 'Alice', 'authorUrl': 'https://example.com/a',
             'licenseType': 'CC BY 2.0'},
            {'fileTitle': 'File:B.jpg', 'imageUrl': 'https://upload.wikimedia.org/B.jpg',
             'pageUrl': 'https://commons.wikimedia.org/wiki/File:B.jpg',
             'authorName': 'Bob', 'authorUrl': None, 'licenseType': 'CC0'}
        ], None)

        response = client.get('/api/wikimedia_image/candidates',
                              query_string={'species': 'American Robin', 'limit': 8})
        assert response.status_code == 200
        body = response.get_json()
        assert body['species'] == 'American Robin'
        assert len(body['candidates']) == 2
        assert body['candidates'][0]['fileTitle'] == 'File:A.jpg'
        assert body['selectedFileTitle'] is None
        assert body['hasCustomImage'] is False
        mock_fetch.assert_called_once_with('American Robin', limit=8)

    @patch('core.api.fetch_wikimedia_candidates')
    def test_candidates_clamps_limit(self, mock_fetch, candidates_client):
        client, _ = candidates_client
        mock_fetch.return_value = ([], None)
        client.get('/api/wikimedia_image/candidates',
                   query_string={'species': 'X', 'limit': '999'})
        # Limit clamped to 20 (upper bound).
        mock_fetch.assert_called_once_with('X', limit=20)

    @patch('core.api.fetch_wikimedia_candidates')
    def test_candidates_includes_selected_file_title_from_sidecar(self, mock_fetch, candidates_client):
        client, images_dir = candidates_client
        sidecar_path = os.path.join(images_dir, 'American_Robin.choice.json')
        with open(sidecar_path, 'w') as f:
            json.dump({
                'imageUrl': 'https://upload.wikimedia.org/B.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:B.jpg',
                'licenseType': 'CC0',
                'fileTitle': 'File:B.jpg',
            }, f)
        mock_fetch.return_value = ([], None)

        response = client.get('/api/wikimedia_image/candidates',
                              query_string={'species': 'American Robin'})
        body = response.get_json()
        assert body['selectedFileTitle'] == 'File:B.jpg'

    def test_candidates_cache_key_is_per_limit(self, candidates_client):
        # Hit the real cache helpers (not a mocked fetcher).
        from core.api import get_cached_image, image_cache, set_cached_image
        image_cache.clear()
        set_cached_image('American Robin', [{'a': 1}], limit=1)
        set_cached_image('American Robin', [{'a': 1}, {'b': 2}], limit=8)
        assert len(get_cached_image('American Robin', limit=1)) == 1
        assert len(get_cached_image('American Robin', limit=8)) == 2
        # Different limits must not collide.
        assert get_cached_image('American Robin', limit=4) is None

    def test_candidates_filters_egg_skeleton_titles(self, candidates_client):
        # End-to-end through fetch_wikimedia_candidates with a mocked requests.get.
        from core import api as api_module
        api_module.image_cache.clear()
        fake = _fake_wikimedia_get(
            search_results=[
                {'title': 'File:Robin.jpg'},
                {'title': 'File:Robin egg.jpg'},  # filtered by title regex
                {'title': 'File:Robin skeleton.jpg'},  # filtered
                {'title': 'File:Another robin.jpg'},
            ],
            imageinfo_pages={
                '1': {'title': 'File:Robin.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/Robin.jpg', author='A')]},
                '2': {'title': 'File:Another robin.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/Another.jpg', author='B')]},
            },
        )
        with patch('core.api.requests.get', side_effect=fake):
            cands, err = api_module.fetch_wikimedia_candidates('Robin', limit=8)
        assert err is None
        assert [c['fileTitle'] for c in cands] == ['File:Robin.jpg', 'File:Another robin.jpg']

    def test_candidates_preserve_search_order_after_batched_imageinfo(self, candidates_client):
        from core import api as api_module
        api_module.image_cache.clear()
        # imageinfo pages keyed by page-id, returned out of search order.
        fake = _fake_wikimedia_get(
            search_results=[{'title': 'File:First.jpg'}, {'title': 'File:Second.jpg'}],
            imageinfo_pages={
                '99': {'title': 'File:Second.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/2.jpg', author='B')]},
                '1': {'title': 'File:First.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/1.jpg', author='A')]},
            },
        )
        with patch('core.api.requests.get', side_effect=fake):
            cands, err = api_module.fetch_wikimedia_candidates('Robin', limit=8)
        assert err is None
        assert [c['fileTitle'] for c in cands] == ['File:First.jpg', 'File:Second.jpg']

    def test_candidates_request_thumbnail_url_and_expose_it(self, candidates_client):
        """imageinfo call sets iiurlwidth and the returned thumburl flows into thumbUrl."""
        from core import api as api_module
        api_module.image_cache.clear()
        captured = {}
        fake = _fake_wikimedia_get(
            search_results=[{'title': 'File:Robin.jpg'}],
            imageinfo_pages={
                '1': {'title': 'File:Robin.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/Robin_full.jpg',
                    thumburl='https://upload.wikimedia.org/thumb/Robin_400.jpg',
                    author='A')]},
            },
            capture=captured,
        )
        with patch('core.api.requests.get', side_effect=fake):
            cands, err = api_module.fetch_wikimedia_candidates('Robin', limit=8)

        assert err is None
        assert captured['imageinfo_params'].get('iiurlwidth') == str(api_module.WIKIMEDIA_THUMB_WIDTH)
        assert cands[0]['thumbUrl'] == 'https://upload.wikimedia.org/thumb/Robin_400.jpg'
        assert cands[0]['imageUrl'] == 'https://upload.wikimedia.org/Robin_full.jpg'

    def test_candidates_thumbUrl_falls_back_to_imageUrl_when_missing(self, candidates_client):
        """Older or partial Wikimedia responses without `thumburl` should still be usable."""
        from core import api as api_module
        api_module.image_cache.clear()
        fake = _fake_wikimedia_get(
            search_results=[{'title': 'File:NoThumb.jpg'}],
            imageinfo_pages={
                '1': {'title': 'File:NoThumb.jpg', 'imageinfo': [_imageinfo(
                    'https://upload.wikimedia.org/NoThumb.jpg', author='A')]},
            },
        )
        with patch('core.api.requests.get', side_effect=fake):
            cands, err = api_module.fetch_wikimedia_candidates('NoThumb', limit=8)

        assert err is None
        assert cands[0]['thumbUrl'] == cands[0]['imageUrl']

    def test_user_agent_carries_contact_url(self, candidates_client):
        """Wikimedia requests send a compliant UA with a contact URL (200/min tier)."""
        from core import api as api_module
        api_module.image_cache.clear()
        captured = {}

        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {'query': {'search': []}}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured['ua'] = (headers or {}).get('User-Agent', '')
            return _R()

        with patch('core.api.requests.get', side_effect=fake_get):
            api_module.fetch_wikimedia_candidates('Robin', limit=1)

        assert captured['ua'].startswith('BirdNET-PiPy/')
        assert 'https://github.com/Suncuss/BirdNET-PiPy' in captured['ua']

    def test_candidates_surfaces_429_with_retry_after(self, candidates_client):
        """A 429 from Wikimedia becomes a structured error with status + Retry-After."""
        import requests as _requests

        from core import api as api_module
        api_module.image_cache.clear()

        class _Resp429:
            status_code = 429
            headers = {'Retry-After': '42'}

        def fake_get(url, params=None, headers=None, timeout=None):
            err = _requests.HTTPError('429 Too Many Requests')
            err.response = _Resp429()
            raise err

        with patch('core.api.requests.get', side_effect=fake_get):
            cands, err = api_module.fetch_wikimedia_candidates('Robin', limit=8)
        assert cands == []
        assert err['status'] == 429
        assert err['retry_after'] == 42.0

    def test_concurrent_misses_share_one_upstream_fetch(self, candidates_client):
        """Single-flight: two concurrent cache-misses for the same key do one fetch."""
        import threading as _threading
        import time as _time

        from core import api as api_module
        api_module.image_cache.clear()
        api_module._wikimedia_inflight.clear()

        search_calls = {'n': 0}
        leader_in_flight = _threading.Event()
        release = _threading.Event()

        class _R:
            status_code = 200
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        def fake_get(url, params=None, headers=None, timeout=None):
            if params.get('list') == 'search':
                search_calls['n'] += 1
                leader_in_flight.set()
                release.wait(timeout=5)  # hold the leader so the follower arrives
                return _R({'query': {'search': [{'title': 'File:Robin.jpg'}]}})
            return _R({'query': {'pages': {'1': {
                'title': 'File:Robin.jpg',
                'imageinfo': [_imageinfo('https://upload.wikimedia.org/Robin.jpg')],
            }}}})

        results = {}
        def worker(name):
            results[name] = api_module.fetch_wikimedia_candidates('Robin', limit=8)

        with patch('core.api.requests.get', side_effect=fake_get):
            leader = _threading.Thread(target=worker, args=('leader',))
            leader.start()
            assert leader_in_flight.wait(timeout=5)  # leader now owns the in-flight slot
            follower = _threading.Thread(target=worker, args=('follower',))
            follower.start()
            _time.sleep(0.2)  # let the follower reach the wait()
            release.set()
            leader.join(timeout=5)
            follower.join(timeout=5)

        assert search_calls['n'] == 1  # follower did NOT hit upstream
        assert results['leader'][1] is None and results['follower'][1] is None
        assert results['leader'][0] == results['follower'][0]


class TestWikimediaChoiceSidecar:
    """Test GET|PUT|DELETE /api/bird/<name>/wikimedia_choice."""

    @pytest.fixture
    def choice_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    def test_get_returns_404_when_no_sidecar(self, choice_client):
        client, _ = choice_client
        response = client.get('/api/bird/American Robin/wikimedia_choice')
        assert response.status_code == 404
        assert response.get_json()['hasChoice'] is False

    def test_put_creates_sidecar(self, choice_client):
        client, images_dir = choice_client
        payload = {
            'fileTitle': 'File:Robin.jpg',
            'imageUrl': 'https://upload.wikimedia.org/Robin.jpg',
            'thumbUrl': 'https://upload.wikimedia.org/thumb/Robin_400.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'Alice',
            'authorUrl': 'https://example.com/a',
            'licenseType': 'CC BY 2.0'
        }
        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body['fileTitle'] == 'File:Robin.jpg'
        assert body['source'] == 'wikimedia'
        assert body['schemaVersion'] == 2
        assert body['thumbUrl'] == 'https://upload.wikimedia.org/thumb/Robin_400.jpg'
        assert 'savedAt' in body
        assert os.path.exists(os.path.join(images_dir, 'American_Robin.choice.json'))

    def test_put_defaults_thumb_to_image_when_omitted(self, choice_client):
        """Older clients that send no thumbUrl get thumbUrl == imageUrl stored."""
        client, _ = choice_client
        payload = {
            'fileTitle': 'File:Robin.jpg',
            'imageUrl': 'https://upload.wikimedia.org/Robin.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'Alice',
            'authorUrl': None,
            'licenseType': 'CC BY 2.0'
        }
        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.get_json()['thumbUrl'] == 'https://upload.wikimedia.org/Robin.jpg'

    def test_put_rejects_non_wikimedia_thumb_url(self, choice_client):
        client, _ = choice_client
        payload = {
            'fileTitle': 'File:Robin.jpg',
            'imageUrl': 'https://upload.wikimedia.org/Robin.jpg',
            'thumbUrl': 'https://evil.example.com/thumb.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'Alice',
            'authorUrl': None,
            'licenseType': 'CC BY 2.0'
        }
        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_put_rejects_non_wikimedia_url(self, choice_client):
        client, _ = choice_client
        payload = {
            'fileTitle': 'File:Bad.jpg',
            'imageUrl': 'https://evil.example.com/bad.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Bad.jpg',
            'authorName': 'Hacker',
            'authorUrl': None,
            'licenseType': 'CC0'
        }
        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code == 400
        assert 'wikimedia.org' in response.get_json()['error']

    def test_put_rejects_missing_keys(self, choice_client):
        client, _ = choice_client
        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps({'fileTitle': 'File:Robin.jpg'}),
            content_type='application/json',
        )
        assert response.status_code == 400
        assert 'Missing keys' in response.get_json()['error']

    def test_put_requires_auth_when_enabled(self, choice_client):
        client, _ = choice_client
        client.post('/api/auth/setup',
                    data=json.dumps({'password': 'testpass123'}),
                    content_type='application/json')
        client.post('/api/auth/logout')

        response = client.put(
            '/api/bird/American Robin/wikimedia_choice',
            data=json.dumps({
                'fileTitle': 'File:Robin.jpg',
                'imageUrl': 'https://upload.wikimedia.org/Robin.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
                'authorName': 'A', 'authorUrl': None, 'licenseType': 'CC0'
            }),
            content_type='application/json',
        )
        assert response.status_code == 401

    def test_delete_is_idempotent(self, choice_client):
        client, images_dir = choice_client
        # Create a sidecar
        with open(os.path.join(images_dir, 'American_Robin.choice.json'), 'w') as f:
            json.dump({
                'imageUrl': 'https://upload.wikimedia.org/x.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:X.jpg',
                'licenseType': 'CC0'
            }, f)
        r1 = client.delete('/api/bird/American Robin/wikimedia_choice')
        assert r1.status_code == 200
        # Second call: file already gone, still 200.
        r2 = client.delete('/api/bird/American Robin/wikimedia_choice')
        assert r2.status_code == 200

    def test_delete_requires_auth_when_enabled(self, choice_client):
        client, _ = choice_client
        client.post('/api/auth/setup',
                    data=json.dumps({'password': 'testpass123'}),
                    content_type='application/json')
        client.post('/api/auth/logout')
        response = client.delete('/api/bird/American Robin/wikimedia_choice')
        assert response.status_code == 401


class TestWikimediaImageHonorsSidecar:
    """The single-result /api/wikimedia_image endpoint should return the sidecar when present."""

    @pytest.fixture
    def sidecar_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    @patch('core.api.fetch_wikimedia_image')
    def test_returns_sidecar_when_present(self, mock_fetch, sidecar_client):
        client, images_dir = sidecar_client
        with open(os.path.join(images_dir, 'American_Robin.choice.json'), 'w') as f:
            json.dump({
                'imageUrl': 'https://upload.wikimedia.org/saved.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:Saved.jpg',
                'licenseType': 'CC0',
                'fileTitle': 'File:Saved.jpg',
                'authorName': 'Saved',
                'authorUrl': None,
            }, f)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        body = response.get_json()
        assert body['imageUrl'] == 'https://upload.wikimedia.org/saved.jpg'
        assert body['fileTitle'] == 'File:Saved.jpg'
        assert body['source'] == 'sidecar'
        # Legacy sidecar (no thumbUrl) falls back to the full imageUrl.
        assert body['thumbUrl'] == 'https://upload.wikimedia.org/saved.jpg'
        # Crucially: do not call upstream when sidecar serves the request.
        mock_fetch.assert_not_called()

    @patch('core.api.fetch_wikimedia_image')
    def test_returns_sidecar_thumb_when_present(self, mock_fetch, sidecar_client):
        client, images_dir = sidecar_client
        with open(os.path.join(images_dir, 'American_Robin.choice.json'), 'w') as f:
            json.dump({
                'schemaVersion': 2,
                'imageUrl': 'https://upload.wikimedia.org/saved.jpg',
                'thumbUrl': 'https://upload.wikimedia.org/thumb/saved_400.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:Saved.jpg',
                'licenseType': 'CC0',
                'fileTitle': 'File:Saved.jpg',
                'authorName': 'Saved',
                'authorUrl': None,
            }, f)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        body = response.get_json()
        assert body['thumbUrl'] == 'https://upload.wikimedia.org/thumb/saved_400.jpg'
        assert body['imageUrl'] == 'https://upload.wikimedia.org/saved.jpg'
        mock_fetch.assert_not_called()

    @patch('core.api.fetch_wikimedia_image')
    def test_falls_through_when_sidecar_corrupt(self, mock_fetch, sidecar_client):
        client, images_dir = sidecar_client
        with open(os.path.join(images_dir, 'American_Robin.choice.json'), 'w') as f:
            f.write('{ not valid json')

        mock_fetch.return_value = ({
            'imageUrl': 'https://upload.wikimedia.org/Robin.jpg',
            'pageUrl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
            'authorName': 'A', 'authorUrl': None, 'licenseType': 'CC0'
        }, None)

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        body = response.get_json()
        assert body['source'] == 'wikimedia-search'
        mock_fetch.assert_called_once()


class TestSidecarUntouchedByImageMutations:
    """POST and DELETE on /image must leave a sidecar in place (precedence: custom > sidecar > default)."""

    @pytest.fixture
    def both_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app, images_dir, patches = _make_client(tmpdir)
            try:
                with app.test_client() as client:
                    yield client, images_dir
            finally:
                for p in patches:
                    p.stop()

    def _write_sidecar(self, images_dir, name='American_Robin'):
        path = os.path.join(images_dir, f'{name}.choice.json')
        with open(path, 'w') as f:
            json.dump({
                'imageUrl': 'https://upload.wikimedia.org/x.jpg',
                'pageUrl': 'https://commons.wikimedia.org/wiki/File:X.jpg',
                'licenseType': 'CC0'
            }, f)
        return path

    def test_upload_does_not_delete_sidecar(self, both_client):
        client, images_dir = both_client
        sidecar = self._write_sidecar(images_dir)

        data = {'file': (io.BytesIO(JPEG_HEADER), 'bird.jpg')}
        response = client.post('/api/bird/American Robin/image',
                               data=data, content_type='multipart/form-data')
        assert response.status_code == 200
        assert os.path.exists(sidecar)

    def test_delete_image_does_not_delete_sidecar(self, both_client):
        client, images_dir = both_client
        # Set up both a custom file and a sidecar.
        with open(os.path.join(images_dir, 'American_Robin.jpg'), 'wb') as f:
            f.write(JPEG_HEADER)
        sidecar = self._write_sidecar(images_dir)

        response = client.delete('/api/bird/American Robin/image')
        assert response.status_code == 200
        assert os.path.exists(sidecar)
