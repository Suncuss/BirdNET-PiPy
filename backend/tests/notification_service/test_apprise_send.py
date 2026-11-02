"""Tests for Apprise sending: MQTT client cleanup and the Test button (GH #73).

Apprise's MQTT plugin never stopped the paho client it started, so every
MQTT notification leaked a thread, three file descriptors and a broker
connection until the process broke. The Test button also failed under the
API's gevent worker whenever the broker was slow to accept a connection.
"""

import json
import os
import subprocess
import sys
import threading
from unittest.mock import Mock, patch

import pytest

from tests.notification_service.fake_mqtt_broker import FakeMqttBroker


def _paho_threads():
    return [t for t in threading.enumerate() if t.name.startswith('paho-mqtt-client-')]


def _open_fd_count():
    return len(os.listdir('/proc/self/fd'))


@pytest.fixture
def broker():
    b = FakeMqttBroker()
    yield b
    b.close()


@pytest.fixture
def slow_broker():
    # Apprise only waits 10 ms for the CONNACK before forcing a reconnect.
    b = FakeMqttBroker(connack_delay=0.1)
    yield b
    b.close()


class TestCloseMqttClients:

    def test_disconnects_and_stops_only_mqtt_clients(self):
        import apprise

        from core.apprise_send import close_mqtt_clients

        ap = apprise.Apprise()
        ap.add('json://localhost')
        ap.add('mqtt://127.0.0.1:1883/birdnet/detection')
        mqtt_server = [s for s in ap if hasattr(s, 'client')][0]
        mqtt_server.client = Mock()

        close_mqtt_clients(ap)

        mqtt_server.client.disconnect.assert_called_once()
        mqtt_server.client.loop_stop.assert_called_once()

    def test_still_stops_the_loop_when_disconnect_raises(self):
        import apprise

        from core.apprise_send import close_mqtt_clients

        ap = apprise.Apprise()
        ap.add('mqtt://127.0.0.1:1883/birdnet/detection')
        server = list(ap)[0]
        server.client = Mock()
        server.client.disconnect.side_effect = OSError('socket gone')

        close_mqtt_clients(ap)

        server.client.loop_stop.assert_called_once()

    def test_never_raises(self):
        from core.apprise_send import close_mqtt_clients

        close_mqtt_clients(Mock())  # not iterable


class TestRealMqttSends:
    """Real Apprise + paho against an in-process broker."""

    def test_worker_sends_leave_no_client_behind(self, notification_service, broker):
        service, _ = notification_service
        threads_before = len(_paho_threads())
        fds_before = _open_fd_count()

        for i in range(5):
            assert service._send(f'Bird {i}', 'detected', urls=[broker.url()]) is True

        assert broker.published == ['birdnet/detection'] * 5
        assert len(_paho_threads()) == threads_before
        assert broker.wait_for_no_connections() == 0
        assert _open_fd_count() == fds_before

    def test_test_button_works_with_slow_broker(self, slow_broker):
        from core.notification_service import send_test_notification

        ok, message = send_test_notification(slow_broker.url('birdnet/test'))

        assert ok is True, message
        assert slow_broker.published == ['birdnet/test']
        assert slow_broker.wait_for_no_connections() == 0

    def test_test_button_works_from_gevent_worker(self, slow_broker):
        """The API worker is gevent-patched; sending in-process there failed."""
        script = (
            "from gevent import monkey; monkey.patch_all()\n"
            "import sys\n"
            "from core.notification_service import send_test_notification\n"
            "ok, message = send_test_notification(sys.argv[1])\n"
            "print('OK' if ok else 'FAIL ' + message)\n"
        )
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env = dict(os.environ, PYTHONPATH=backend_dir)

        proc = subprocess.run(
            [sys.executable, '-c', script, slow_broker.url('birdnet/test')],
            capture_output=True, text=True, timeout=60, env=env, cwd=backend_dir)

        assert proc.stdout.strip().splitlines()[-1:] == ['OK'], proc.stdout + proc.stderr
        assert slow_broker.published == ['birdnet/test']


class TestSendTestNotification:
    """The API side: runs core/apprise_send.py as a child and reads its JSON."""

    @staticmethod
    def _completed(stdout='', returncode=0, stderr=''):
        return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)

    def test_passes_url_on_stdin_not_argv(self):
        from core.notification_service import (
            TEST_SEND_TIMEOUT_SECONDS,
            send_test_notification,
        )

        url = 'mqtt://user:secret@broker/topic'
        reply = json.dumps({'ok': True, 'detail': 'Test notification sent successfully'})
        with patch('core.notification_service.subprocess.run',
                   return_value=self._completed(reply + '\n')) as run:
            assert send_test_notification(url) == (True, 'Test notification sent successfully')

        argv = run.call_args.args[0]
        assert argv[1] == '-I' and argv[2].endswith('apprise_send.py')
        assert url not in ' '.join(argv)
        assert run.call_args.kwargs['input'] == url
        assert run.call_args.kwargs['timeout'] == TEST_SEND_TIMEOUT_SECONDS

    def test_returns_child_failure_detail(self):
        from core.notification_service import send_test_notification

        reply = json.dumps({'ok': False, 'detail': 'Connection refused. Check the server address and port.'})
        with patch('core.notification_service.subprocess.run',
                   return_value=self._completed(reply)):
            assert send_test_notification('mqtt://broker/t') == (
                False, 'Connection refused. Check the server address and port.')

    def test_timeout(self):
        from core.notification_service import send_test_notification

        with patch('core.notification_service.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(cmd='python', timeout=25)):
            ok, message = send_test_notification('mqtt://broker/t')
        assert ok is False
        assert 'Timed out' in message

    def test_crashed_child(self):
        from core.apprise_send import FALLBACK_TEST_ERROR
        from core.notification_service import send_test_notification

        with patch('core.notification_service.subprocess.run',
                   return_value=self._completed('', 1, 'Traceback...\nImportError: boom')):
            assert send_test_notification('mqtt://broker/t') == (False, FALLBACK_TEST_ERROR)


class TestSendTest:
    """The child side: the in-process Apprise test send."""

    def test_success(self):
        from core.apprise_send import send_test

        ap = Mock()
        ap.notify.return_value = True
        with patch('apprise.Apprise', return_value=ap), \
             patch('core.apprise_send.close_mqtt_clients') as close:
            ok, message = send_test('tgram://bot/chat')

        assert ok is True
        assert 'success' in message.lower()
        ap.add.assert_called_once_with('tgram://bot/chat')
        close.assert_called_once_with(ap)

    def test_failure_returns_error_detail(self):
        from core.apprise_send import send_test

        ap = Mock()
        ap.notify.return_value = False
        with patch('apprise.Apprise', return_value=ap):
            ok, message = send_test('invalid://url')

        assert ok is False
        assert isinstance(message, str) and message

    def test_exception_is_returned_and_clients_still_closed(self):
        from core.apprise_send import send_test

        ap = Mock()
        ap.notify.side_effect = RuntimeError('Message publish failed: The connection was lost.')
        with patch('apprise.Apprise', return_value=ap), \
             patch('core.apprise_send.close_mqtt_clients') as close:
            ok, message = send_test('mqtt://broker/t')

        assert ok is False
        assert 'connection was lost' in message
        close.assert_called_once_with(ap)


class TestExtractAppriseError:

    def test_friendly_messages(self):
        from core.apprise_send import extract_apprise_error

        assert 'resolve hostname' in extract_apprise_error('socket.gaierror: Name or service not known')
        assert 'Connection refused' in extract_apprise_error('ConnectionRefusedError: Connection refused')
        assert 'timed out' in extract_apprise_error('socket.timeout: timed out')
        assert 'Check your configuration' in extract_apprise_error('')
        assert 'Check your configuration' in extract_apprise_error('   ')

    def test_raw_message(self):
        from core.apprise_send import extract_apprise_error

        result = extract_apprise_error('MQTT Connection Error received from 127.0.0.1:9999')
        assert result == 'MQTT Connection Error received from 127.0.0.1:9999'
