"""Apprise send helpers shared by the notification worker and the Test button.

Imports nothing else from ``core``: the Test button runs this file as a
standalone script (``python -I apprise_send.py``, URL on stdin, JSON result on
stdout) so the test send happens in a plain interpreter rather than the
gevent-patched API worker. See ``notification_service.send_test_notification``.
"""

import io
import json
import logging
import sys

FALLBACK_TEST_ERROR = 'Failed to send test notification. Check your configuration.'

_FRIENDLY_ERRORS = {
    'Name or service not known': 'Could not resolve hostname. Check the server address.',
    'Connection refused': 'Connection refused. Check the server address and port.',
    'timed out': 'Connection timed out. Check the server address and port.',
    'No route to host': 'No route to host. Check the server address.',
    'Connection reset': 'Connection was reset by the server.',
}


def close_mqtt_clients(ap):
    """Disconnect the MQTT clients an Apprise send left running.

    Apprise's MQTT plugin starts a paho network thread on its first send and
    never stops it, and that thread keeps the client alive, so every send
    otherwise leaves a thread, three file descriptors and an open broker
    connection behind for the life of the process. Never raises.
    """
    try:
        from apprise.plugins.mqtt import NotifyMQTT
        servers = [s for s in ap if isinstance(s, NotifyMQTT)]
    except Exception:
        return
    for server in servers:
        client = server.client
        # Both are no-ops on a client that never connected or already stopped.
        for close in (client.disconnect, client.loop_stop):
            try:
                close()
            except Exception:
                pass


def extract_apprise_error(log_output):
    """Extract a user-friendly error message from apprise log output."""
    if not log_output or not log_output.strip():
        return FALLBACK_TEST_ERROR

    # Apprise sometimes logs a clean one-liner (e.g. "MQTT Connection Error...")
    # Other times it logs a full traceback — grab the last line for the root cause
    last_line = log_output.strip().split('\n')[-1].strip()

    for keyword, message in _FRIENDLY_ERRORS.items():
        if keyword in last_line:
            return message

    # Return the raw last line if it's short enough to be useful
    if len(last_line) < 200:
        return last_line

    return FALLBACK_TEST_ERROR


def send_test(apprise_url):
    """Send one test notification in this process.

    Returns:
        tuple: (True, message) on success, (False, error_detail) on failure
    """
    import apprise

    ap = apprise.Apprise()
    # Capture apprise logger output to extract error details
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.WARNING)
    apprise_logger = logging.getLogger('apprise')
    apprise_logger.addHandler(handler)
    try:
        ap.add(apprise_url)
        result = ap.notify(
            title="BirdNET-PiPy Test Notification",
            body="If you see this, notifications are working correctly!"
        )
    except Exception as e:
        return False, str(e)
    finally:
        apprise_logger.removeHandler(handler)
        close_mqtt_clients(ap)

    if result:
        return True, 'Test notification sent successfully'
    return False, extract_apprise_error(stream.getvalue())


def main():
    ok, detail = send_test(sys.stdin.read().strip())
    print(json.dumps({'ok': ok, 'detail': detail}))


if __name__ == '__main__':
    main()
