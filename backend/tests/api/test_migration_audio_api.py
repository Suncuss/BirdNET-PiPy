"""Tests for BirdNET-Pi migration audio and spectrogram API endpoints."""

import os
import tempfile
import time
import threading
import pytest
from unittest.mock import patch, Mock


def wait_for_audio_import(api_client, import_id, timeout=30):
    """Wait for an audio import to complete by polling the status endpoint.

    Args:
        api_client: Flask test client
        import_id: The import ID to poll for
        timeout: Maximum seconds to wait

    Returns:
        dict: Final status response
    """
    start = time.time()
    while time.time() - start < timeout:
        response = api_client.get(
            '/api/migration/audio/status',
            query_string={'import_id': import_id}
        )
        if response.status_code != 200:
            time.sleep(0.1)
            continue

        data = response.get_json()
        if data.get('status') in ('completed', 'failed'):
            return data

        time.sleep(0.1)

    raise TimeoutError(f"Audio import did not complete within {timeout} seconds")


def wait_for_spectrogram_generation(api_client, generation_id, timeout=60):
    """Wait for spectrogram generation to complete by polling the status endpoint.

    Args:
        api_client: Flask test client
        generation_id: The generation ID to poll for
        timeout: Maximum seconds to wait

    Returns:
        dict: Final status response
    """
    start = time.time()
    while time.time() - start < timeout:
        response = api_client.get(
            '/api/migration/spectrogram/status',
            query_string={'generation_id': generation_id}
        )
        if response.status_code != 200:
            time.sleep(0.1)
            continue

        data = response.get_json()
        if data.get('status') in ('completed', 'failed'):
            return data

        time.sleep(0.1)

    raise TimeoutError(f"Spectrogram generation did not complete within {timeout} seconds")


class TestMigrationAudioFoldersEndpoint:
    """Tests for /api/migration/audio/folders endpoint."""

    def test_list_folders_empty(self, api_client):
        """Test list folders when data directory is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.get('/api/migration/audio/folders')
                assert response.status_code == 200
                data = response.get_json()
                assert data['folders'] == []

    def test_list_folders_with_audio(self, api_client):
        """Test list folders finds directories with audio files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder with audio files
            audio_folder = os.path.join(tmpdir, 'my_audio')
            os.makedirs(audio_folder)
            with open(os.path.join(audio_folder, 'test.mp3'), 'wb') as f:
                f.write(b'fake audio')

            # Create folder without audio (should be excluded)
            empty_folder = os.path.join(tmpdir, 'empty_folder')
            os.makedirs(empty_folder)

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.get('/api/migration/audio/folders')
                assert response.status_code == 200
                data = response.get_json()
                assert len(data['folders']) == 1
                assert data['folders'][0]['name'] == 'my_audio'
                assert data['folders'][0]['audio_count'] == 1


class TestMigrationAudioScanEndpoint:
    """Tests for /api/migration/audio/scan endpoint."""

    def test_scan_no_source_folder(self, api_client):
        """Test scan returns error when no source_folder provided."""
        response = api_client.post('/api/migration/audio/scan', json={})
        assert response.status_code == 400
        data = response.get_json()
        assert 'source_folder' in data['error'].lower()

    def test_scan_nonexistent_folder(self, api_client):
        """Test scan returns source_exists=False when folder doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/scan',
                    json={'source_folder': 'nonexistent'}
                )
                assert response.status_code == 200
                data = response.get_json()
                assert data['source_exists'] is False
                assert data['matched_count'] == 0

    def test_scan_empty_directory(self, api_client, real_db_manager):
        """Test scan with empty source directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an empty folder
            empty_folder = os.path.join(tmpdir, 'empty_audio')
            os.makedirs(empty_folder)

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/scan',
                    json={'source_folder': 'empty_audio'}
                )
                assert response.status_code == 200
                data = response.get_json()
                assert data['source_exists'] is True
                assert data['matched_count'] == 0
                assert 'disk_usage' in data

    def test_scan_with_no_matching_records(self, api_client, real_db_manager):
        """Test scan when DB has no records with original_file_name."""
        # Insert detection without original_file_name in extra
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {}  # No original_file_name
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder with audio file
            audio_folder = os.path.join(tmpdir, 'audio')
            os.makedirs(audio_folder)
            audio_file = os.path.join(audio_folder, 'test.mp3')
            with open(audio_file, 'wb') as f:
                f.write(b'fake audio content')

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/scan',
                    json={'source_folder': 'audio'}
                )
                assert response.status_code == 200
                data = response.get_json()
                assert data['total_records'] == 0
                assert data['matched_count'] == 0

    def test_scan_with_matching_files(self, api_client, real_db_manager):
        """Test scan finds matching files."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'robin_test.mp3'}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder with matching audio file
            audio_folder = os.path.join(tmpdir, 'audio')
            os.makedirs(audio_folder)
            audio_file = os.path.join(audio_folder, 'robin_test.mp3')
            with open(audio_file, 'wb') as f:
                f.write(b'fake audio content of some size')

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/scan',
                    json={'source_folder': 'audio'}
                )
                assert response.status_code == 200
                data = response.get_json()
                assert data['total_records'] == 1
                assert data['matched_count'] == 1
                assert data['unmatched_count'] == 0
                assert data['total_size_bytes'] > 0

    def test_scan_recursive_search(self, api_client, real_db_manager):
        """Test scan searches subdirectories recursively."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'nested_robin.mp3'}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested directory structure like BirdNET-Pi
            audio_folder = os.path.join(tmpdir, 'audio')
            nested_dir = os.path.join(audio_folder, 'By_Date', '2024-01-15')
            os.makedirs(nested_dir)
            audio_file = os.path.join(nested_dir, 'nested_robin.mp3')
            with open(audio_file, 'wb') as f:
                f.write(b'fake audio content')

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/scan',
                    json={'source_folder': 'audio'}
                )
                assert response.status_code == 200
                data = response.get_json()
                assert data['matched_count'] == 1


class TestMigrationAudioImportEndpoint:
    """Tests for /api/migration/audio/import endpoint."""

    def test_import_no_source_folder(self, api_client):
        """Test import fails when no source_folder provided."""
        response = api_client.post('/api/migration/audio/import', json={})
        assert response.status_code == 400
        assert 'source_folder' in response.get_json()['error'].lower()

    def test_import_no_matched_files(self, api_client, real_db_manager):
        """Test import fails when no files match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_folder = os.path.join(tmpdir, 'audio')
            os.makedirs(audio_folder)

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                response = api_client.post(
                    '/api/migration/audio/import',
                    json={'source_folder': 'audio'}
                )
                assert response.status_code == 400
                assert 'No matching audio files' in response.get_json()['error']

    def test_import_insufficient_disk_space(self, api_client, real_db_manager):
        """Test import fails when disk space is insufficient."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'robin.mp3'}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_folder = os.path.join(tmpdir, 'audio')
            os.makedirs(audio_folder)
            audio_file = os.path.join(audio_folder, 'robin.mp3')
            with open(audio_file, 'wb') as f:
                f.write(b'fake audio content')

            # Mock disk space check to return insufficient space
            mock_disk_check = {
                'current_percent': 90,
                'after_import_percent': 95,
                'has_enough_space': False,
                'available_bytes': 0
            }

            with patch('core.migration_audio.DATA_DIR', tmpdir):
                # Patch where check_disk_space is used (in api.py)
                with patch('core.api.check_disk_space', return_value=mock_disk_check):
                    response = api_client.post(
                        '/api/migration/audio/import',
                        json={'source_folder': 'audio'}
                    )
                    assert response.status_code == 400
                    assert 'Not enough disk space' in response.get_json()['error']

    def test_import_success(self, api_client, real_db_manager):
        """Test successful audio import."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'robin_import_test.mp3'}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as dest_dir:
                audio_folder = os.path.join(tmpdir, 'audio')
                os.makedirs(audio_folder)
                audio_file = os.path.join(audio_folder, 'robin_import_test.mp3')
                with open(audio_file, 'wb') as f:
                    f.write(b'fake audio content')

                with patch('core.migration_audio.DATA_DIR', tmpdir):
                    with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', dest_dir):
                        response = api_client.post(
                            '/api/migration/audio/import',
                            json={'source_folder': 'audio'}
                        )
                        assert response.status_code == 200
                        data = response.get_json()
                        assert data['status'] in ('started', 'already_running')
                        assert 'import_id' in data

                        # Wait for completion
                        result = wait_for_audio_import(api_client, data['import_id'])
                        assert result['status'] == 'completed'
                        assert result['imported'] == 1

    def test_import_already_running_returns_existing_id(self, api_client, real_db_manager):
        """Test import returns running job ID when another import is in progress."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'robin_running_test.mp3'}
        })

        block_event = threading.Event()

        def blocking_import(db_manager, matched_files, import_id):
            from core.migration_audio import set_audio_import_progress
            total = len(matched_files)
            set_audio_import_progress(import_id, {
                'status': 'running',
                'processed': 0,
                'total': total,
                'imported': 0,
                'skipped': 0,
                'errors': 0
            })
            block_event.wait(timeout=2)
            set_audio_import_progress(import_id, {
                'status': 'completed',
                'processed': total,
                'total': total,
                'imported': total,
                'skipped': 0,
                'errors': 0
            })
            return {'imported': total, 'skipped': 0, 'errors': 0}

        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as dest_dir:
                audio_folder = os.path.join(tmpdir, 'audio')
                os.makedirs(audio_folder)
                audio_file = os.path.join(audio_folder, 'robin_running_test.mp3')
                with open(audio_file, 'wb') as f:
                    f.write(b'fake audio content')

                with patch('core.migration_audio.DATA_DIR', tmpdir):
                    with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', dest_dir):
                        with patch('core.api.import_audio_files', side_effect=blocking_import):
                            # Start first import (will block)
                            response1 = api_client.post(
                                '/api/migration/audio/import',
                                json={'source_folder': 'audio'}
                            )
                            assert response1.status_code == 200
                            data1 = response1.get_json()
                            assert data1['status'] == 'started'

                            # Start second import while first is running
                            response2 = api_client.post(
                                '/api/migration/audio/import',
                                json={'source_folder': 'audio'}
                            )
                            assert response2.status_code == 200
                            data2 = response2.get_json()
                            assert data2['status'] == 'already_running'
                            assert data2['import_id'] == data1['import_id']

                            # Unblock and ensure completion
                            block_event.set()
                            result = wait_for_audio_import(api_client, data1['import_id'])
                            assert result['status'] == 'completed'


class TestMigrationAudioStatusEndpoint:
    """Tests for /api/migration/audio/status endpoint."""

    def test_status_missing_import_id(self, api_client):
        """Test status fails without import_id parameter."""
        response = api_client.get('/api/migration/audio/status')
        assert response.status_code == 400
        assert 'import_id' in response.get_json()['error'].lower()

    def test_status_not_found(self, api_client):
        """Test status returns 404 for unknown import_id."""
        response = api_client.get(
            '/api/migration/audio/status',
            query_string={'import_id': 'nonexistent_import_123'}
        )
        assert response.status_code == 404
        assert response.get_json()['status'] == 'not_found'


class TestMigrationAudioSkipEndpoint:
    """Tests for /api/migration/audio/skip endpoint."""

    def test_skip_success(self, api_client):
        """Test skip returns success."""
        response = api_client.post('/api/migration/audio/skip')
        assert response.status_code == 200
        assert response.get_json()['status'] == 'skipped'


class TestMigrationSpectrogramScanEndpoint:
    """Tests for /api/migration/spectrogram/scan endpoint."""

    def test_scan_no_audio_directory(self, api_client):
        """Test scan when audio directory doesn't exist."""
        with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', '/nonexistent/path'):
            response = api_client.post('/api/migration/spectrogram/scan')
            assert response.status_code == 200
            data = response.get_json()
            assert data['count'] == 0

    def test_scan_empty_directory(self, api_client):
        """Test scan with empty audio directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', tmpdir):
                response = api_client.post('/api/migration/spectrogram/scan')
                assert response.status_code == 200
                data = response.get_json()
                assert data['count'] == 0
                assert 'disk_usage' in data

    def test_scan_files_needing_spectrograms(self, api_client):
        """Test scan counts files without spectrograms."""
        with tempfile.TemporaryDirectory() as audio_dir:
            with tempfile.TemporaryDirectory() as spec_dir:
                # Create MP3 audio files (only MP3 is supported now)
                for name in ['file1.mp3', 'file2.mp3', 'file3.mp3']:
                    with open(os.path.join(audio_dir, name), 'wb') as f:
                        f.write(b'fake audio')

                # Create spectrogram for one file
                with open(os.path.join(spec_dir, 'file1.webp'), 'wb') as f:
                    f.write(b'fake spectrogram')

                with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', audio_dir):
                    with patch('core.migration_audio.SPECTROGRAM_DIR', spec_dir):
                        response = api_client.post('/api/migration/spectrogram/scan')
                        assert response.status_code == 200
                        data = response.get_json()
                        # file2.mp3 and file3.mp3 need spectrograms (file1.mp3 has one)
                        assert data['count'] == 2
                        assert data['estimated_size_bytes'] > 0


class TestMigrationSpectrogramGenerateEndpoint:
    """Tests for /api/migration/spectrogram/generate endpoint."""

    def test_generate_no_files(self, api_client):
        """Test generate when no files need spectrograms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', tmpdir):
                response = api_client.post('/api/migration/spectrogram/generate')
                assert response.status_code == 200
                data = response.get_json()
                assert data['status'] == 'no_files'

    def test_generate_insufficient_disk_space(self, api_client):
        """Test generate fails when disk space is insufficient."""
        with tempfile.TemporaryDirectory() as audio_dir:
            with tempfile.TemporaryDirectory() as spec_dir:
                # Create audio file
                with open(os.path.join(audio_dir, 'test.mp3'), 'wb') as f:
                    f.write(b'fake audio')

                mock_disk_check = {
                    'current_percent': 90,
                    'after_import_percent': 95,
                    'has_enough_space': False,
                    'available_bytes': 0
                }

                with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', audio_dir):
                    with patch('core.migration_audio.SPECTROGRAM_DIR', spec_dir):
                        with patch('core.migration_audio.check_disk_space', return_value=mock_disk_check):
                            response = api_client.post('/api/migration/spectrogram/generate')
                            assert response.status_code == 400
                            assert 'Insufficient disk space' in response.get_json()['error']

    def test_generate_success(self, api_client):
        """Test successful spectrogram generation."""
        import struct

        with tempfile.TemporaryDirectory() as audio_dir:
            with tempfile.TemporaryDirectory() as spec_dir:
                # Create a real WAV file (minimal valid format)
                # Patch AUDIO_EXTENSIONS to include .wav for this test
                wav_path = os.path.join(audio_dir, 'Test_Bird_85_2024-01-15-birdnet-10:30:00.wav')

                # Create minimal valid WAV header + silent audio
                sample_rate = 48000
                duration = 1  # 1 second
                num_samples = sample_rate * duration
                audio_data = b'\x00\x00' * num_samples  # Silent 16-bit mono

                with open(wav_path, 'wb') as f:
                    # RIFF header
                    f.write(b'RIFF')
                    f.write(struct.pack('<I', 36 + len(audio_data)))
                    f.write(b'WAVE')
                    # fmt chunk
                    f.write(b'fmt ')
                    f.write(struct.pack('<I', 16))  # chunk size
                    f.write(struct.pack('<H', 1))   # audio format (PCM)
                    f.write(struct.pack('<H', 1))   # num channels
                    f.write(struct.pack('<I', sample_rate))  # sample rate
                    f.write(struct.pack('<I', sample_rate * 2))  # byte rate
                    f.write(struct.pack('<H', 2))   # block align
                    f.write(struct.pack('<H', 16))  # bits per sample
                    # data chunk
                    f.write(b'data')
                    f.write(struct.pack('<I', len(audio_data)))
                    f.write(audio_data)

                # Patch AUDIO_EXTENSIONS to include .wav for spectrogram generation test
                with patch('core.migration_audio.AUDIO_EXTENSIONS', ('.mp3', '.wav')):
                    with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', audio_dir):
                        with patch('core.migration_audio.SPECTROGRAM_DIR', spec_dir):
                            response = api_client.post('/api/migration/spectrogram/generate')
                            assert response.status_code == 200
                            data = response.get_json()
                            assert data['status'] == 'started'
                            assert 'generation_id' in data

                            # Wait for completion
                            result = wait_for_spectrogram_generation(api_client, data['generation_id'])
                            assert result['status'] == 'completed'
                            assert result['generated'] == 1

    def test_generate_already_running_returns_existing_id(self, api_client):
        """Test generate returns running job ID when another generation is in progress."""
        block_event = threading.Event()

        def blocking_generate(audio_files, generation_id):
            from core.migration_audio import set_spectrogram_progress
            total = len(audio_files)
            set_spectrogram_progress(generation_id, {
                'status': 'running',
                'processed': 0,
                'total': total,
                'generated': 0,
                'errors': 0
            })
            block_event.wait(timeout=2)
            set_spectrogram_progress(generation_id, {
                'status': 'completed',
                'processed': total,
                'total': total,
                'generated': total,
                'errors': 0
            })
            return {'generated': total, 'errors': 0}

        with tempfile.TemporaryDirectory() as audio_dir:
            with tempfile.TemporaryDirectory() as spec_dir:
                # Create a minimal MP3 placeholder
                with open(os.path.join(audio_dir, 'already_running_test.mp3'), 'wb') as f:
                    f.write(b'fake audio')

                with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', audio_dir):
                    with patch('core.migration_audio.SPECTROGRAM_DIR', spec_dir):
                        with patch('core.api.generate_spectrograms_batch', side_effect=blocking_generate):
                            # Start first generation (will block)
                            response1 = api_client.post('/api/migration/spectrogram/generate')
                            assert response1.status_code == 200
                            data1 = response1.get_json()
                            assert data1['status'] == 'started'

                            # Start second generation while first is running
                            response2 = api_client.post('/api/migration/spectrogram/generate')
                            assert response2.status_code == 200
                            data2 = response2.get_json()
                            assert data2['status'] == 'already_running'
                            assert data2['generation_id'] == data1['generation_id']

                            # Unblock and ensure completion
                            block_event.set()
                            result = wait_for_spectrogram_generation(api_client, data1['generation_id'])
                            assert result['status'] == 'completed'


class TestMigrationSpectrogramStatusEndpoint:
    """Tests for /api/migration/spectrogram/status endpoint."""

    def test_status_missing_generation_id(self, api_client):
        """Test status fails without generation_id parameter."""
        response = api_client.get('/api/migration/spectrogram/status')
        assert response.status_code == 400
        assert 'generation_id' in response.get_json()['error'].lower()

    def test_status_not_found(self, api_client):
        """Test status returns 404 for unknown generation_id."""
        response = api_client.get(
            '/api/migration/spectrogram/status',
            query_string={'generation_id': 'nonexistent_gen_123'}
        )
        assert response.status_code == 404
        assert response.get_json()['status'] == 'not_found'


class TestMigrationSpectrogramSkipEndpoint:
    """Tests for /api/migration/spectrogram/skip endpoint."""

    def test_skip_success(self, api_client):
        """Test skip returns success."""
        response = api_client.post('/api/migration/spectrogram/skip')
        assert response.status_code == 200
        assert response.get_json()['status'] == 'skipped'


class TestMigrationAudioIntegration:
    """Integration tests for the audio migration workflow."""

    def test_full_audio_workflow(self, api_client, real_db_manager):
        """Test complete audio migration workflow: scan -> import."""
        # Insert detection with original_file_name
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': {'original_file_name': 'workflow_test.mp3'}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as dest_dir:
                # Create source file in nested directory (like BirdNET-Pi)
                audio_folder = os.path.join(tmpdir, 'audio')
                nested = os.path.join(audio_folder, 'By_Date', '2024-01-15')
                os.makedirs(nested)
                audio_file = os.path.join(nested, 'workflow_test.mp3')
                with open(audio_file, 'wb') as f:
                    f.write(b'fake audio content for workflow test')

                # Create a mock for list_available_folders that returns our test folder
                mock_folders = [{
                    'name': 'audio',
                    'path': 'audio',
                    'audio_count': 1
                }]

                with patch('core.migration_audio.DATA_DIR', tmpdir):
                    with patch('core.migration_audio.EXTRACTED_AUDIO_DIR', dest_dir):
                        # Patch list_available_folders where it's used (in api.py)
                        with patch('core.api.list_available_folders', return_value=mock_folders):
                            # Step 1: List folders
                            response = api_client.get('/api/migration/audio/folders')
                            assert response.status_code == 200
                            folders_data = response.get_json()
                            assert len(folders_data['folders']) == 1
                            assert folders_data['folders'][0]['name'] == 'audio'

                        # Step 2: Scan (outside of folder mock)
                        response = api_client.post(
                            '/api/migration/audio/scan',
                            json={'source_folder': 'audio'}
                        )
                        assert response.status_code == 200
                        scan_data = response.get_json()
                        assert scan_data['matched_count'] == 1
                        assert scan_data['disk_usage']['has_enough_space'] is True

                        # Step 3: Import
                        response = api_client.post(
                            '/api/migration/audio/import',
                            json={'source_folder': 'audio'}
                        )
                        assert response.status_code == 200
                        import_data = response.get_json()
                        assert import_data['status'] == 'started'

                        # Step 4: Wait and verify
                        result = wait_for_audio_import(api_client, import_data['import_id'])
                        assert result['status'] == 'completed'
                        assert result['imported'] == 1
                        assert result['errors'] == 0

                        # Verify file was copied to destination
                        files = os.listdir(dest_dir)
                        assert len(files) == 1
                        # File should be renamed to BirdNET-PiPy format
                        assert 'American_Robin' in files[0]
