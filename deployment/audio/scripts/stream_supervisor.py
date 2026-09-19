#!/usr/bin/env python3
"""Own one FFmpeg publisher per source; reconcile settings without restarting Icecast.

Standard library only. Status contains hashes and source IDs, never connection
URLs or credentials. Raw FFmpeg stderr is suppressed because it can echo URLs.
"""
import hashlib
import json
import logging
import os
import re
import select
import signal
import subprocess
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

DATA_DIR = Path(os.environ.get('BIRDNET_DATA_DIR', '/app/data'))
logger = logging.getLogger('stream-supervisor')


def source_revision(source):
    # Wire contract shared with core/source_config.py (tested for parity).
    values = [source.get('type'), source.get('url', '') if source.get('type') == 'rtsp'
              else source.get('device', 'default')]
    return hashlib.sha256(json.dumps(values, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def read_json(path, *, missing=None):
    try:
        with path.open() as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        return value
    except FileNotFoundError:
        if missing is not None:
            return missing
        raise


def enabled_sources(settings):
    audio = settings.get('audio', {})
    sources = audio.get('sources', [])
    # Read-only mirror of the API's legacy audio migration
    # (config/settings.py, tested for parity). Runtime readers never persist
    # that migration, so a station whose file predates multi-source keeps the
    # old keys on disk until its next explicit save.
    if any(key in audio for key in ('recording_mode', 'rtsp_url', 'rtsp_urls',
                                    'rtsp_labels', 'pulseaudio_source', 'stream_url')):
        sources = []
        mode = audio.get('recording_mode', 'pulseaudio')
        if mode == 'pulseaudio':
            sources.append({'id': 'source_0', 'type': 'pulseaudio', 'device': 'default'})
        urls = [url for url in audio.get('rtsp_urls', []) if url]
        active = audio.get('rtsp_url')
        if mode == 'rtsp' and active and active not in urls:
            urls.append(active)
        for url in urls:
            sources.append({'id': f'source_{len(sources)}', 'type': 'rtsp', 'url': url,
                            'enabled': mode == 'rtsp' and url == active})
    if not isinstance(sources, list):
        raise ValueError('Invalid audio sources')
    desired, seen = {}, set()
    for source in sources:
        # Same policy as the API's settings loader: an entry the recorder
        # could not use is skipped, not a reason to stream nothing.
        error = _source_error(source)
        if error or source['id'] in seen:
            logger.warning('Skipping audio source: %s', error or 'duplicate id')
            continue
        seen.add(source['id'])
        if source.get('enabled', True):
            desired[source['id']] = source
    return desired


def _source_error(source):
    if not isinstance(source, dict) or not re.fullmatch(r'source_[0-9]+', str(source.get('id', ''))):
        return 'invalid source'
    if source.get('type') not in ('rtsp', 'pulseaudio'):
        return 'invalid source type'
    if 'enabled' in source and type(source['enabled']) is not bool:
        return 'invalid enabled flag'
    for key in ('url', 'device'):
        if key in source and (not isinstance(source[key], str) or '\x00' in source[key]):
            return 'invalid connection'
    if source['type'] == 'rtsp' and not source.get('url', '').startswith(('rtsp://', 'rtsps://')):
        return 'invalid RTSP URL'


def write_status(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.stream-status-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Publisher:
    def __init__(self, source, password, bitrate):
        self.revision = source_revision(source)
        self.last_progress = time.monotonic()
        self.started = self.last_progress
        self.active = False
        self.progress = 0
        self.buffer = b''
        if source['type'] == 'rtsp':
            inputs = ['-rtsp_flags', 'prefer_tcp', '-timeout', '10000000', '-allowed_media_types', 'audio',
                      '-fflags', '+genpts+discardcorrupt', '-use_wallclock_as_timestamps', '1',
                      '-i', source['url'], '-map', '0:a:0']
        else:
            inputs = ['-f', 'pulse', '-i', source.get('device', 'default')]
        destination = f'icecast://source:{quote(password, safe="")}@localhost:8888/{source["id"]}.mp3'
        self.process = subprocess.Popen(
            ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', *inputs,
             '-codec:a', 'libmp3lame', '-b:a', bitrate, '-f', 'mp3', '-content_type', 'audio/mpeg',
             '-progress', 'pipe:1', '-stats_period', '1', destination],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        os.set_blocking(self.process.stdout.fileno(), False)

    def state(self):
        if self.process.poll() is not None:
            return 'failed'
        fd = self.process.stdout.fileno()
        if select.select([fd], [], [], 0)[0]:
            self.buffer += os.read(fd, 65536)
            lines = self.buffer.split(b'\n')
            self.buffer = lines.pop()[-4096:]
            for line in lines:
                if line.startswith(b'out_time_us=') and line[12:].isdigit() and int(line[12:]) > self.progress:
                    self.progress = int(line[12:])
                    self.active = True
                    self.last_progress = time.monotonic()
        if time.monotonic() - self.last_progress > (15 if self.active else 45):
            return 'failed'
        return 'active' if self.active else 'connecting'

    def stop(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=2)
        self.process.stdout.close()


class Supervisor:
    def __init__(self, factory):
        self.factory = factory
        self.publishers = {}
        self.retry_at = {}

    def reconcile(self, desired, now):
        failures = set()
        for sid, publisher in list(self.publishers.items()):
            if sid not in desired or publisher.revision != source_revision(desired[sid]):
                try:
                    publisher.stop()
                except (OSError, subprocess.TimeoutExpired):
                    failures.add(sid)
                    continue
                del self.publishers[sid]
                self.retry_at.pop(sid, None)
                logger.info('Reconnecting/stopping %s after settings change', sid)
        status = {}
        for sid, source in desired.items():
            publisher = self.publishers.get(sid)
            if publisher is None and now >= self.retry_at.get(sid, 0):
                try:
                    publisher = self.factory(source)
                    self.publishers[sid] = publisher
                    logger.info('Connecting %s', sid)
                except (OSError, ValueError, KeyError):
                    self.retry_at[sid] = now + 5
            state = publisher.state() if publisher and sid not in failures else 'failed'
            status[sid] = {'config_revision': source_revision(source), 'state': state}
            if state == 'failed' and publisher and sid not in failures:
                try:
                    publisher.stop()
                    del self.publishers[sid]
                    self.retry_at[sid] = now + 5
                except (OSError, subprocess.TimeoutExpired):
                    pass
                logger.warning('Stream %s unavailable; retrying', sid)
        self.retry_at = {sid: retry for sid, retry in self.retry_at.items() if sid in desired}
        for sid in failures - desired.keys():
            status[sid] = {'config_revision': self.publishers[sid].revision, 'state': 'failed'}
        return status

    def stop(self):
        for publisher in self.publishers.values():
            try:
                publisher.stop()
            except (OSError, subprocess.TimeoutExpired):
                logger.warning('Unable to stop stream publisher')
        self.publishers.clear()


def main():
    (DATA_DIR / 'logs').mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / 'logs/icecast.log', maxBytes=5 * 1024 * 1024, backupCount=1)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), handler],
                        format='%(asctime)s %(levelname)s %(message)s')
    running = True

    def stop(_signal, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    supervisor = Supervisor(lambda source: Publisher(source, os.environ['ICECAST_PASSWORD'],
                                                     os.environ.get('STREAM_BITRATE', '320k')))
    desired = {}
    settings_seen = False
    settings_path = DATA_DIR / 'config/user_settings.json'
    try:
        while running:
            error = None
            try:
                # An unreadable or invalid file keeps the last valid configuration.
                desired = enabled_sources(read_json(settings_path, missing={} if not settings_seen else None))
                settings_seen |= settings_path.exists()
            except (OSError, ValueError, TypeError, AttributeError):
                error = 'Unable to load streaming settings; using the last valid configuration'
            sources = supervisor.reconcile(desired, time.monotonic())
            write_status(DATA_DIR / 'streaming_status.json', {
                'updated_at': time.time(), 'sources': sources, 'error': error})
            time.sleep(1)
    finally:
        supervisor.stop()
        write_status(DATA_DIR / 'streaming_status.json', {'updated_at': 0, 'sources': {}, 'error': 'Streaming stopped'})


if __name__ == '__main__':
    main()
