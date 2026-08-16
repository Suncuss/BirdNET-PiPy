"""Focused unit tests for core.main helpers."""

import os
import tempfile
from unittest.mock import patch

import pytest


def make_detection(**overrides):
    """A handle_detection-shaped input dict (pre-save synthesized names)."""
    detection = {
        'common_name': 'American Robin',
        'scientific_name': 'Turdus migratorius',
        'confidence': 0.95,
        'timestamp': '2025-11-26T10:30:00',
        'chunk_index': 1,
        'total_chunks': 3,
        'bird_song_file_name': 'American_Robin_95_x.wav',
        'spectrogram_file_name': 'American_Robin_95_x.webp',
    }
    detection.update(overrides)
    return detection


class TestCreateDetectionSpectrogram:
    """Tests for spectrogram title generation."""

    def test_create_detection_spectrogram_uses_spectrogram_safe_display_name(self):
        detection = make_detection(
            spectrogram_file_name='American_Robin_95_test.webp')

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch('core.main.SPECTROGRAM_DIR', tmpdir), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_spectrogram_common_name', return_value='American Robin') as mock_name, \
             patch('core.main.publish_media_file', return_value=1234) as mock_publish, \
             patch('core.main.generate_spectrogram') as mock_generate:
            from core.main import create_detection_spectrogram

            result = create_detection_spectrogram(detection, '/tmp/input.wav')

        mock_name.assert_called_once_with('Turdus migratorius', 'American Robin')
        mock_generate.assert_called_once()
        assert mock_generate.call_args.args[2] == 'American Robin (0.95) - 2025-11-26T10:30:00'
        # Written to the temp name, atomically published to the final name
        final_path = os.path.join(tmpdir, 'American_Robin_95_test.webp')
        assert mock_generate.call_args.args[1] == final_path + '.part'
        mock_publish.assert_called_once_with(final_path + '.part', final_path)
        assert result == (final_path, 1234)


class TestExtractDetectionAudio:
    """Tests for clip extraction and the playback-normalize setting."""

    def _run(self, settings):
        detection = {
            'chunk_index': 1,
            'total_chunks': 3,
            'bird_song_file_name': 'American_Robin_90_test.wav',
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch('core.main.EXTRACTED_AUDIO_DIR', tmpdir), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_runtime_settings', return_value=settings), \
             patch('core.main.publish_media_file', return_value=999) as mock_publish, \
             patch('core.main.extract_audio_segment') as mock_extract:
            from core.main import extract_detection_audio
            result = extract_detection_audio(detection, '/tmp/input.wav')
        self.mock_publish = mock_publish
        return mock_extract, result

    def test_passes_normalize_true_when_setting_enabled(self):
        mock_extract, _ = self._run({'playback': {'normalize': True}})
        assert mock_extract.call_args.kwargs.get('normalize') is True

    def test_defaults_to_no_normalize_when_setting_absent(self):
        mock_extract, _ = self._run({})
        assert mock_extract.call_args.kwargs.get('normalize') is False

    def test_extracts_to_part_then_publishes_atomically(self):
        """The clip is cut from the source straight to an MP3 temp name
        (explicit -f, since .part hides the container), then published
        atomically — a partial file never appears under the final name."""
        mock_extract, result = self._run({})

        mock_extract.assert_called_once()
        args = mock_extract.call_args.args
        assert args[0] == '/tmp/input.wav'
        assert args[1].endswith('American_Robin_90_test.mp3.part')
        assert mock_extract.call_args.kwargs.get('output_format') == 'mp3'
        # chunk_index=1 of 3, chunk length 3s -> context window is chunks 0-2
        assert args[2] == 0
        assert args[3] == 9
        final_path = args[1][:-len('.part')]
        self.mock_publish.assert_called_once_with(args[1], final_path)
        assert result == (final_path, 999)


class TestHandleDetectionRowFirst:
    """The row-first creation protocol: save → name via id+nonce →
    publish → record ownership → broadcast."""

    def _detection(self):
        return make_detection()

    def _run(self, record_side_effect=None):
        from unittest.mock import MagicMock
        calls = []
        detection = self._detection()

        def fake_save(d):
            calls.append('save')
            d['id'] = 7

        def fake_extract(d, path):
            calls.append('extract')
            return ('/media/' + d['bird_song_file_name'], 100)

        def fake_spectrogram(d, path):
            calls.append('spectrogram')
            return ('/media/' + d['spectrogram_file_name'], 50)

        mock_db = MagicMock()
        mock_db.get_media_nonce.return_value = 'ab' * 16
        if record_side_effect is not None:
            mock_db.record_detection_media.side_effect = record_side_effect

        with patch('core.main.save_detection_to_db', side_effect=fake_save), \
             patch('core.main.extract_detection_audio', side_effect=fake_extract), \
             patch('core.main.create_detection_spectrogram', side_effect=fake_spectrogram), \
             patch('core.main.db_manager', mock_db), \
             patch('core.main.get_runtime_settings', return_value={}), \
             patch('core.main.get_notification_service', return_value=None), \
             patch('core.main.broadcast_detection') as mock_broadcast, \
             patch('core.main.os.remove') as mock_remove:
            from unittest.mock import MagicMock as _MM

            from core.main import handle_detection
            handle_detection(detection, '/tmp/input.wav', _MM())

        return calls, detection, mock_db, mock_broadcast, mock_remove

    def test_row_saved_before_any_media_is_created(self):
        calls, _, _, _, _ = self._run()
        assert calls.index('save') < calls.index('extract') < calls.index('spectrogram')

    def test_filenames_carry_id_and_nonce_and_ownership_is_recorded(self):
        _, detection, mock_db, mock_broadcast, _ = self._run()
        suffix = f"7-{'ab' * 16}"
        assert detection['bird_song_file_name'] == f'American_Robin_95_x_{suffix}.mp3'
        assert detection['spectrogram_file_name'] == f'American_Robin_95_x_{suffix}.webp'
        files = mock_db.record_detection_media.call_args.args[1]
        assert [(f['kind'], f['rank'], f['bytes']) for f in files] == [
            ('audio', 0, 100), ('spectrogram', 0, 50)]
        mock_broadcast.assert_called_once()

    def test_delete_race_removes_published_files_and_stops(self):
        from core.media_ownership import DetectionMissingError
        _, detection, _, mock_broadcast, mock_remove = self._run(
            record_side_effect=DetectionMissingError('gone'))
        removed = {call.args[0] for call in mock_remove.call_args_list}
        assert removed == {
            '/media/' + detection['bird_song_file_name'],
            '/media/' + detection['spectrogram_file_name']}
        mock_broadcast.assert_not_called()


class TestWriterCrashStates:
    """A writer dying mid-creation leaves only recognizable states: a
    file-less row, a .part temp, or a published-but-unrecorded nonce-named
    orphan — never a partial file under a final name."""

    def _detection(self):
        return make_detection()

    def test_kill_during_audio_writer_leaves_only_part_file(self, tmp_path):
        """ffmpeg dies mid-write: a partial .part exists, the final name
        does not, and the row records no media."""
        from unittest.mock import MagicMock
        audio_dir = tmp_path / 'audio'
        audio_dir.mkdir()
        detection = self._detection()
        mock_db = MagicMock()
        mock_db.get_media_nonce.return_value = 'cd' * 16

        def dying_extract(src, part_path, *a, **kw):
            with open(part_path, 'wb') as f:
                f.write(b'trunca')  # partial write, then the process "dies"
            raise RuntimeError('writer killed')

        with patch('core.main.EXTRACTED_AUDIO_DIR', str(audio_dir)), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_runtime_settings', return_value={}), \
             patch('core.main.db_manager', mock_db), \
             patch('core.main.save_detection_to_db',
                   side_effect=lambda d: d.__setitem__('id', 9)), \
             patch('core.main.extract_audio_segment', side_effect=dying_extract):
            from core.main import handle_detection
            with pytest.raises(RuntimeError):
                handle_detection(detection, '/tmp/in.wav', MagicMock())

        files = {p.name for p in audio_dir.iterdir()}
        assert all(name.endswith('.part') for name in files)
        mock_db.record_detection_media.assert_not_called()

    def test_kill_after_publish_before_record_leaves_nonce_orphan(self, tmp_path):
        """Death between audio publication and record_media leaves exactly
        the designed orphan: a complete file under its id+nonce final name,
        no ownership rows — reconciliation's reattachment case."""
        from unittest.mock import MagicMock
        audio_dir = tmp_path / 'audio'
        spec_dir = tmp_path / 'spec'
        audio_dir.mkdir()
        spec_dir.mkdir()
        detection = self._detection()
        mock_db = MagicMock()
        mock_db.get_media_nonce.return_value = 'ef' * 16

        def working_extract(src, part_path, *a, **kw):
            with open(part_path, 'wb') as f:
                f.write(b'complete audio')

        with patch('core.main.EXTRACTED_AUDIO_DIR', str(audio_dir)), \
             patch('core.main.SPECTROGRAM_DIR', str(spec_dir)), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_runtime_settings', return_value={}), \
             patch('core.main.db_manager', mock_db), \
             patch('core.main.save_detection_to_db',
                   side_effect=lambda d: d.__setitem__('id', 9)), \
             patch('core.main.extract_audio_segment', side_effect=working_extract), \
             patch('core.main.create_detection_spectrogram',
                   side_effect=RuntimeError('killed before record')):
            from core.main import handle_detection
            with pytest.raises(RuntimeError):
                handle_detection(detection, '/tmp/in.wav', MagicMock())

        published = list(audio_dir.iterdir())
        assert len(published) == 1
        name = published[0].name
        assert name.endswith('.mp3') and f"9-{'ef' * 16}" in name
        assert published[0].read_bytes() == b'complete audio'
        mock_db.record_detection_media.assert_not_called()


class TestNotificationConsumesRecordedNames:

    def test_notify_receives_recorded_filenames(self):
        """The notification service (and everything after record_media)
        sees the recorded id+nonce names, not the synthesized ones."""
        from unittest.mock import MagicMock
        detection = make_detection()
        mock_db = MagicMock()
        mock_db.get_media_nonce.return_value = 'ab' * 16
        notif = MagicMock()

        with patch('core.main.save_detection_to_db',
                   side_effect=lambda d: d.__setitem__('id', 7)), \
             patch('core.main.extract_detection_audio',
                   return_value=('/x/a.mp3', 1)), \
             patch('core.main.create_detection_spectrogram',
                   return_value=('/x/s.webp', 1)), \
             patch('core.main.db_manager', mock_db), \
             patch('core.main.get_runtime_settings', return_value={}), \
             patch('core.main.broadcast_detection'), \
             patch('core.main.get_notification_service', return_value=notif):
            from core.main import handle_detection
            handle_detection(detection, '/tmp/in.wav', MagicMock())

        notified = notif.notify.call_args.args[0]
        suffix = f"7-{'ab' * 16}"
        assert notified['bird_song_file_name'] == f'American_Robin_95_x_{suffix}.mp3'
        assert notified['spectrogram_file_name'] == f'American_Robin_95_x_{suffix}.webp'
