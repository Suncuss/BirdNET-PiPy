import os
from unittest.mock import patch

import core.media_storage as media_storage

INTERNAL_TARGET = {
    'id': media_storage.MEDIA_TARGET_INTERNAL,
    'label': 'Internal storage (SD card)',
    'mount_path': '/app/data',
    'writable': True,
    'available': True,
    'filesystem': None,
    'free_bytes': 100,
    'total_bytes': 200,
    'source': 'internal',
}


class TestMediaStorageTargets:
    def test_returns_internal_and_external_targets(self):
        drive = '/external-media'
        external_target = {
            'id': drive,
            'label': 'Configured external storage',
            'mount_path': drive,
            'writable': True,
            'available': True,
            'filesystem': 'ext4',
            'free_bytes': 500,
            'total_bytes': 1000,
            'source': 'external',
        }

        with patch.object(media_storage, '_internal_target_info', return_value=INTERNAL_TARGET), \
            patch.object(media_storage, '_external_media_configured', return_value=True), \
            patch.object(media_storage.os.path, 'isdir', return_value=True), \
            patch.object(media_storage, '_iter_candidate_dirs', return_value=[drive]), \
            patch.object(media_storage, '_mount_filesystems', return_value={drive: 'ext4'}), \
            patch.object(media_storage, '_external_target_info', return_value=external_target):
            targets = media_storage.get_available_media_targets()

        assert [target['id'] for target in targets] == [media_storage.MEDIA_TARGET_INTERNAL, drive]
        assert targets[1]['filesystem'] == 'ext4'
        assert targets[1]['label'] == 'Configured external storage'

    def test_returns_only_internal_when_external_path_is_not_configured(self):
        with patch.object(media_storage, '_internal_target_info', return_value=INTERNAL_TARGET), \
            patch.object(media_storage, '_external_media_configured', return_value=False):
            targets = media_storage.get_available_media_targets()

        assert targets == [INTERNAL_TARGET]

    def test_managed_mounted_drive_appears_without_manual_external_configuration(self):
        drive = '/managed-media/12345678-1234-1234-1234-123456789abc'
        with patch.object(media_storage, '_internal_target_info', return_value=INTERNAL_TARGET), \
            patch.object(media_storage, '_external_media_configured', return_value=False), \
            patch.object(media_storage.os.path, 'isdir', return_value=True), \
            patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path), \
            patch.object(media_storage.os, 'access', return_value=True), \
            patch.object(media_storage.shutil, 'disk_usage') as usage, \
            patch.object(media_storage, '_mount_filesystems', return_value={drive: 'ext4'}):
            usage.return_value.free = 500
            usage.return_value.total = 1000
            targets = media_storage.get_available_media_targets()
            assert [target['id'] for target in targets] == ['internal', drive]
            assert targets[1]['label'] == 'BIRDSTORE 12345678'
            status = media_storage.get_media_storage_status({'storage': {'media_target': drive}})
            assert status['effective_target_id'] == drive
            assert status['fallback_active'] is False

    def test_empty_managed_mount_folder_is_not_offered_as_a_drive(self):
        with patch.object(media_storage, '_internal_target_info', return_value=INTERNAL_TARGET), \
            patch.object(media_storage, '_external_media_configured', return_value=False), \
            patch.object(media_storage.os.path, 'isdir', return_value=True), \
            patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path), \
            patch.object(media_storage, '_mount_filesystems', return_value={'/managed-media': 'ext4'}):
            assert media_storage.get_available_media_targets() == [INTERNAL_TARGET]

    def test_configured_parent_exposes_only_direct_child_mounts(self):
        root = '/external-media'
        filesystems = {
            root: 'ext4',
            f'{root}/USB_ONE': 'exfat',
            f'{root}/USB_TWO': 'ext4',
            f'{root}/USB_ONE/nested': 'tmpfs',
            '/unrelated': 'ext4',
        }

        with patch.object(media_storage.os.path, 'isdir', return_value=True), \
            patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path):
            candidates = media_storage._iter_candidate_dirs(root, filesystems)

        assert candidates == [f'{root}/USB_ONE', f'{root}/USB_TWO']

    def test_single_configured_drive_uses_the_root_target(self):
        root = '/external-media'

        with patch.object(media_storage.os.path, 'isdir', return_value=True), \
            patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path):
            candidates = media_storage._iter_candidate_dirs(root, {root: 'ext4'})

        assert candidates == [root]

    def test_falls_back_to_internal_when_selected_target_is_missing(self):
        preferred = '/external-media'
        settings = {'storage': {'media_target': preferred}}

        with patch.object(media_storage, 'get_available_media_targets', return_value=[INTERNAL_TARGET]), \
            patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path):
            status = media_storage.get_media_storage_status(settings)

        assert status['preferred_target_id'] == preferred
        assert status['effective_target_id'] == media_storage.MEDIA_TARGET_INTERNAL
        assert status['fallback_active'] is True
        assert status['fallback_reason'] == 'missing'
        assert status['preferred_target']['available'] is False

    def test_uses_external_target_when_available_and_writable(self):
        preferred = '/external-media'
        settings = {'storage': {'media_target': preferred}}
        external = {
            'id': preferred,
            'label': 'BIRDSTORE',
            'mount_path': preferred,
            'writable': True,
            'available': True,
            'filesystem': 'ext4',
            'free_bytes': 500,
            'total_bytes': 1000,
            'source': 'external',
        }

        with patch.object(media_storage, 'get_available_media_targets', return_value=[INTERNAL_TARGET, external]):
            status = media_storage.get_media_storage_status(settings)

        assert status['effective_target_id'] == preferred
        assert status['fallback_active'] is False
        assert status['effective_target']['source'] == 'external'

    def test_effective_media_dirs_use_external_app_subdirectory(self):
        preferred = '/external-media'
        settings = {'storage': {'media_target': preferred}}
        status = {
            'preferred_target_id': preferred,
            'preferred_target': {'id': preferred},
            'effective_target_id': preferred,
            'effective_target': {
                'id': preferred,
                'mount_path': preferred,
                'label': 'BIRDSTORE',
                'writable': True,
                'available': True,
                'source': 'external',
            },
            'fallback_active': False,
            'fallback_reason': None,
            'targets': [INTERNAL_TARGET],
        }
        created = []

        with patch.object(media_storage, 'get_media_storage_status', return_value=status), \
            patch.object(media_storage.os, 'makedirs', side_effect=lambda path, exist_ok=True: created.append(path)):
            media_storage.ensure_effective_media_dirs(settings)
            recording_dir = media_storage.get_effective_recording_dir(settings)
            extracted_dir = media_storage.get_effective_extracted_audio_dir(settings)

        expected_root = os.path.join(preferred, media_storage.EXTERNAL_MEDIA_APP_DIR)
        assert recording_dir == os.path.join(expected_root, 'audio', 'recordings')
        assert extracted_dir == os.path.join(expected_root, 'audio', 'extracted_songs')
        assert os.path.join(expected_root, 'spectrograms') in created

    def test_search_dirs_include_internal_fallback(self):
        with patch.object(
            media_storage,
            'get_effective_spectrogram_dir',
            return_value='/external-media/BirdNET-PiPy/spectrograms',
        ):
            search_dirs = media_storage.get_spectrogram_search_dirs(
                {'storage': {'media_target': '/external-media'}}
            )

        assert search_dirs == [
            '/external-media/BirdNET-PiPy/spectrograms',
            media_storage.SPECTROGRAM_DIR,
        ]

    def test_valid_media_target_ids_are_limited_to_allowed_mount_roots(self):
        with patch.object(media_storage.os.path, 'realpath', side_effect=lambda path: path):
            assert media_storage.is_valid_media_target_id('internal') is True
            assert media_storage.is_valid_media_target_id('/external-media') is True
            assert media_storage.is_valid_media_target_id('/external-media/USB_ONE') is True
            assert media_storage.is_valid_media_target_id('/external-media/USB_ONE/subdir') is False
            assert media_storage.is_valid_media_target_id('/tmp/not-allowed') is False
            assert media_storage.is_valid_media_target_id('/managed-media/drive') is True
            assert media_storage.is_valid_media_target_id('/managed-media') is False
