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
            images_dir = os.path.join(tmpdir, 'bird_images')
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.CUSTOM_BIRD_IMAGES_DIR', images_dir), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):
                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, images_dir

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
            images_dir = os.path.join(tmpdir, 'bird_images')
            os.makedirs(images_dir)

            # Create a test image file
            test_file = os.path.join(images_dir, 'American_Robin.jpg')
            with open(test_file, 'wb') as f:
                f.write(JPEG_HEADER)

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.CUSTOM_BIRD_IMAGES_DIR', images_dir), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):
                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, images_dir

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
            images_dir = os.path.join(tmpdir, 'bird_images')
            os.makedirs(images_dir)

            test_file = os.path.join(images_dir, 'American_Robin.jpg')
            with open(test_file, 'wb') as f:
                f.write(JPEG_HEADER)

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.CUSTOM_BIRD_IMAGES_DIR', images_dir), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):
                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, images_dir

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
            images_dir = os.path.join(tmpdir, 'bird_images')
            os.makedirs(images_dir)

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.CUSTOM_BIRD_IMAGES_DIR', images_dir), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):
                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, images_dir

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

        mock_fetch.return_value = (None, 'No results found')

        response = client.get('/api/wikimedia_image', query_string={'species': 'American Robin'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['hasCustomImage'] is True


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
