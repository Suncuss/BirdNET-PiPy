"""Notification service for bird detection alerts via Apprise.

Supports 100+ notification services (Telegram, Discord, Slack, ntfy, email, etc.).
Uses async queue with background worker thread, following birdweather_service.py pattern.
"""

import queue
import threading
from datetime import datetime

from core.logging_config import get_logger
from core.runtime_config import get_runtime_settings, resolve_source_label

logger = get_logger(__name__)

NOTIFICATION_QUEUE_MAXSIZE = 100


def load_user_settings():
    """Compatibility wrapper around runtime settings cache."""
    return get_runtime_settings()


class NotificationService:
    """Thread-safe notification service with background processing."""

    def __init__(self, db_manager):
        self._db = db_manager
        self._queue = queue.Queue(maxsize=NOTIFICATION_QUEUE_MAXSIZE)
        self._last_notified = {}  # {scientific_name: detection_timestamp_str}
        self._load_config()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        logger.info("Notification service started", extra={'url_count': len(self._apprise_urls)})

    def _load_config(self):
        """Load notification config from runtime settings cache."""
        settings = load_user_settings()
        notif = settings['notifications']
        self._apprise_urls = notif['apprise_urls']
        self._every_detection = notif['every_detection']
        self._rate_limit_seconds = notif['rate_limit_seconds']
        self._first_of_day = notif['first_of_day']
        self._new_species = notif['new_species']
        self._rare_species = notif['rare_species']
        self._rare_threshold = notif['rare_threshold']
        self._rare_window_days = notif['rare_window_days']

    def notify(self, detection):
        """Queue detection for notification processing. Non-blocking."""
        try:
            self._queue.put_nowait(detection)
        except queue.Full:
            logger.warning("Notification queue full, dropping detection", extra={
                'species': detection.get('common_name')
            })

    def _worker_loop(self):
        """Process notifications sequentially in background."""
        while True:
            detection = self._queue.get()
            try:
                self._process_detection(detection)
            except Exception as e:
                logger.error("Notification processing failed", extra={'error': str(e)})

    def _process_detection(self, detection):
        """Evaluate triggers and send notification if any fire."""
        self._load_config()

        if not self._apprise_urls:
            return

        sci_name = detection.get('scientific_name', '')
        detection_ts = detection.get('timestamp', '')
        triggers = []

        if self._every_detection:
            if self._check_rate_limit(sci_name, detection_ts):
                triggers.append('every_detection')

        today_count = None
        if self._first_of_day:
            today_count = self._db.get_today_detection_count(sci_name, before_timestamp=detection_ts)
            if today_count == 1:
                triggers.append('first_of_day')

        if self._new_species:
            # If already seen multiple times today, definitely not a new species
            if today_count is not None and today_count > 1:
                pass
            else:
                total = self._db.get_species_total_count(sci_name, before_timestamp=detection_ts)
                if total == 1:
                    triggers.append('new_species')

        if self._rare_species:
            count = self._db.get_recent_detection_count(
                sci_name,
                days=self._rare_window_days,
                before_timestamp=detection_ts
            )
            if count <= self._rare_threshold:
                triggers.append('rare_species')

        if not triggers:
            return

        title = self._build_title(detection, triggers)
        message = self._build_message(detection, triggers)
        self._send(title, message)

    def _check_rate_limit(self, scientific_name, detection_ts):
        """Check per-species rate limit. Returns True if notification should be sent."""
        last_ts = self._last_notified.get(scientific_name)
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts)
                current_dt = datetime.fromisoformat(detection_ts)
                elapsed = (current_dt - last_dt).total_seconds()
                if elapsed < self._rate_limit_seconds:
                    return False
            except (ValueError, TypeError):
                pass
        self._last_notified[scientific_name] = detection_ts
        return True

    def _build_title(self, detection, triggers):
        """Build notification title based on most notable trigger."""
        common_name = detection.get('common_name', 'Unknown')
        if 'new_species' in triggers:
            return f"New species: {common_name}"
        if 'first_of_day' in triggers:
            return f"First sighting today: {common_name}"
        if 'rare_species' in triggers:
            return f"Rare species: {common_name}"
        return f"Bird detected: {common_name}"

    @staticmethod
    def _resolve_source_label(source_id):
        """Look up human-readable label for a source ID from runtime settings."""
        return resolve_source_label(source_id, fallback=source_id)

    def _build_message(self, detection, triggers):
        """Build notification message body."""
        common_name = detection.get('common_name', 'Unknown')
        sci_name = detection.get('scientific_name', '')
        confidence = detection.get('confidence', 0)
        timestamp = detection.get('timestamp', '')

        # Format time portion
        time_str = timestamp.split('T')[1].split('.')[0] if 'T' in timestamp else timestamp

        lines = [
            f"{common_name} ({sci_name})",
            f"Confidence: {confidence * 100:.0f}%",
            f"Time: {time_str}",
        ]

        # Include source label if available
        audio_source = detection.get('audio_source')
        if audio_source:
            source_label = self._resolve_source_label(audio_source)
            lines.append(f"Source: {source_label}")

        reasons = []
        if 'new_species' in triggers:
            reasons.append("Never seen before")
        if 'first_of_day' in triggers:
            reasons.append("First detection today")
        if 'rare_species' in triggers:
            reasons.append("Rarely seen species")
        if 'every_detection' in triggers and len(triggers) == 1:
            reasons.append("New detection")

        if reasons:
            lines.append(f"Trigger: {', '.join(reasons)}")

        return '\n'.join(lines)

    def _send(self, title, message):
        """Send notification to all configured Apprise URLs."""
        try:
            import apprise
            ap = apprise.Apprise()
            for url in self._apprise_urls:
                ap.add(url)
            result = ap.notify(title=title, body=message)
            if result:
                logger.info("Notification sent", extra={'title': title})
            else:
                logger.warning("Notification send returned failure", extra={'title': title})
        except Exception as e:
            logger.error("Failed to send notification", extra={'error': str(e)})


# Singleton
_notification_service = None


def get_notification_service(db_manager=None):
    """Get or create NotificationService singleton.

    Only creates the service if apprise_urls is configured. Returns None otherwise,
    allowing callers to skip notification processing entirely.
    """
    global _notification_service
    if _notification_service is None and db_manager is not None:
        settings = load_user_settings()
        if settings['notifications']['apprise_urls']:
            _notification_service = NotificationService(db_manager)
    return _notification_service


def send_test_notification(apprise_url):
    """Send a test notification synchronously. Used by the test endpoint.

    Args:
        apprise_url: Single Apprise URL to test

    Returns:
        tuple: (True, message) on success, (False, error_detail) on failure
    """
    import io
    import logging

    try:
        import apprise
        ap = apprise.Apprise()
        ap.add(apprise_url)

        # Capture apprise logger output to extract error details
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.WARNING)
        apprise_logger = logging.getLogger('apprise')
        apprise_logger.addHandler(handler)

        try:
            result = ap.notify(
                title="BirdNET-PiPy Test Notification",
                body="If you see this, notifications are working correctly!"
            )
        finally:
            apprise_logger.removeHandler(handler)

        if result:
            return True, 'Test notification sent successfully'

        log_output = stream.getvalue().strip()
        detail = _extract_apprise_error(log_output)
        return False, detail

    except Exception as e:
        logger.error("Test notification failed", extra={'error': str(e)})
        return False, str(e)


def _extract_apprise_error(log_output):
    """Extract a user-friendly error message from apprise log output."""
    if not log_output or not log_output.strip():
        return 'Failed to send test notification. Check your configuration.'

    # Apprise sometimes logs a clean one-liner (e.g. "MQTT Connection Error...")
    # Other times it logs a full traceback — grab the last line for the root cause
    lines = log_output.strip().split('\n')
    last_line = lines[-1].strip()

    # If the last line is a recognizable exception, make it friendlier
    friendly = {
        'Name or service not known': 'Could not resolve hostname. Check the server address.',
        'Connection refused': 'Connection refused. Check the server address and port.',
        'timed out': 'Connection timed out. Check the server address and port.',
        'No route to host': 'No route to host. Check the server address.',
        'Connection reset': 'Connection was reset by the server.',
    }
    for keyword, message in friendly.items():
        if keyword in last_line:
            return message

    # Return the raw last line if it's short enough to be useful
    if len(last_line) < 200:
        return last_line

    return 'Failed to send test notification. Check your configuration.'
