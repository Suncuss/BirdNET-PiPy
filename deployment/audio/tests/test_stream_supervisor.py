"""Run with: python3 -m unittest discover -s deployment/audio/tests -v"""
import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stream = load_module('stream_supervisor', ROOT / 'deployment/audio/scripts/stream_supervisor.py')
sources = load_module('source_config', ROOT / 'backend/core/source_config.py')
sys.path.insert(0, str(ROOT / 'backend'))
from config.settings import _migrate_audio_sources  # noqa: E402  (the API's legacy migration)


def camera(sid, url=None):
    return {'id': sid, 'type': 'rtsp', 'url': url or f'rtsp://user:password@camera/{sid}', 'enabled': True}


class SupervisorTests(unittest.TestCase):
    def test_revision_contract_matches_backend_and_ignores_labels(self):
        for source in (camera('source_0'), {'id': 'source_1', 'type': 'pulseaudio'},
                       {'id': 'source_2', 'type': 'pulseaudio', 'device': 'mic.ü'}):
            self.assertEqual(stream.source_revision(source), sources.source_revision(source))
            self.assertEqual(stream.source_revision(source), stream.source_revision({**source, 'label': 'New name'}))

    def make_supervisor(self):
        def publisher(source):
            result = Mock(revision=stream.source_revision(source))
            result.state.return_value = 'active'
            return result
        factory = Mock(side_effect=publisher)
        return stream.Supervisor(factory), factory

    def test_source_changes_reconnect_only_that_publisher(self):
        supervisor, factory = self.make_supervisor()
        desired = {sid: camera(sid) for sid in ('source_0', 'source_1')}
        supervisor.reconcile(desired, 0)
        first, second = supervisor.publishers.values()
        desired['source_0']['label'] = 'Renamed'
        supervisor.reconcile(desired, 1)
        self.assertEqual(factory.call_count, 2)
        desired['source_0']['url'] = 'rtsp://replacement/audio'
        supervisor.reconcile(desired, 2)
        first.stop.assert_called_once()
        second.stop.assert_not_called()
        self.assertIs(supervisor.publishers['source_1'], second)
        del desired['source_0']
        supervisor.reconcile(desired, 3)
        self.assertEqual(set(supervisor.publishers), {'source_1'})

    def test_failed_source_retries_with_backoff_while_healthy_one_continues(self):
        supervisor, factory = self.make_supervisor()
        desired = {sid: camera(sid) for sid in ('source_0', 'source_1')}
        supervisor.reconcile(desired, 0)
        first, second = supervisor.publishers.values()
        first.state.return_value = 'failed'
        status = supervisor.reconcile(desired, 1)
        self.assertEqual(status['source_0']['state'], 'failed')
        supervisor.reconcile(desired, 2)
        self.assertEqual(factory.call_count, 2)
        supervisor.reconcile(desired, 6)
        self.assertEqual(factory.call_count, 3)
        second.stop.assert_not_called()

    def test_failed_stop_never_starts_a_duplicate_or_reports_disabled(self):
        supervisor, factory = self.make_supervisor()
        supervisor.reconcile({'source_0': camera('source_0')}, 0)
        old = supervisor.publishers['source_0']
        old.stop.side_effect = subprocess.TimeoutExpired('ffmpeg', 2)
        status = supervisor.reconcile({}, 1)
        self.assertIn('source_0', status)
        self.assertEqual(factory.call_count, 1)
        old.stop.side_effect = None
        self.assertEqual(supervisor.reconcile({}, 2), {})

    def test_legacy_settings_stream_exactly_what_the_api_records(self):
        # Runtime readers never persist the API's legacy migration, so the
        # supervisor must derive the same enabled sources from the raw file.
        for legacy in ({'recording_mode': 'rtsp', 'rtsp_url': 'rtsp://second', 'rtsp_urls': ['rtsp://first', 'rtsp://second']},
                       {'recording_mode': 'rtsp', 'rtsp_url': 'rtsp://only', 'rtsp_urls': []},
                       {'recording_mode': 'pulseaudio', 'rtsp_urls': ['rtsp://unused']},
                       {'recording_mode': 'pulseaudio'}):
            expected = copy.deepcopy({'audio': legacy})
            _migrate_audio_sources(expected, persist=False)
            recorded = {s['id']: (s['type'], s.get('url'), s.get('device', 'default'))
                        for s in expected['audio']['sources'] if s['enabled']}
            streamed = {sid: (s['type'], s.get('url'), s.get('device', 'default'))
                        for sid, s in stream.enabled_sources({'audio': legacy}).items()}
            self.assertEqual(streamed, recorded, legacy)
            self.assertTrue(recorded, legacy)

    def test_unusable_sources_are_skipped_but_invalid_lists_are_rejected(self):
        sources = [{**camera('source_0'), 'enabled': 'false'}, {**camera('source_1'), 'url': 'http://x'},
                   camera('source_2'), camera('source_2')]
        self.assertEqual(set(stream.enabled_sources({'audio': {'sources': sources}})), {'source_2'})
        with self.assertRaises(ValueError):
            stream.enabled_sources({'audio': {'sources': 'source_0'}})

    def test_status_is_atomic_private_and_does_not_contain_credentials(self):
        supervisor, _ = self.make_supervisor()
        status = supervisor.reconcile({'source_0': camera('source_0')}, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            stream.write_status(path, {'sources': status})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('password', path.read_text())
            self.assertNotIn('rtsp://', path.read_text())

    def test_active_requires_advancing_audio_progress(self):
        reader, writer = os.pipe()
        process = Mock(stdout=os.fdopen(reader, 'rb', buffering=0))
        process.poll.return_value = None
        now = [0]
        try:
            with patch.object(stream.subprocess, 'Popen', return_value=process), \
                 patch.object(stream.time, 'monotonic', side_effect=lambda: now[0]):
                publisher = stream.Publisher(camera('source_0'), 'secret', '128k')
                self.assertEqual(publisher.state(), 'connecting')
                os.write(writer, b'out_time_us=1000000\n')
                self.assertEqual(publisher.state(), 'active')
                now[0] = 16
                os.write(writer, b'out_time_us=1000000\n')
                self.assertEqual(publisher.state(), 'failed')
        finally:
            process.stdout.close()
            os.close(writer)


if __name__ == '__main__':
    unittest.main()
