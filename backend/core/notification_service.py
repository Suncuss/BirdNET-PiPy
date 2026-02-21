"""Notification service for bird detection alerts via Apprise.

Supports 100+ notification services (Telegram, Discord, Slack, ntfy, email, etc.).
Uses async queue with background worker thread, following birdweather_service.py pattern.
"""

import queue
import threading
from datetime import datetime

from config.settings import load_user_settings
from core.logging_config import get_logger

logger = get_logger(__name__)

NOTIFICATION_QUEUE_MAXSIZE = 100


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
        """Load notification config from settings file."""
        settings = load_user_settings()
        notif = settings['notifications']
        self._apprise_urls = notif['apprise_urls']
        self._every_detection = notif['every_detection']
        self._rate_limit_seconds = notif['rate_limit_seconds']
        self._first_of_day = notif['first_of_day']
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

        if self._first_of_day:
            count = self._db.get_today_detection_count(sci_name, before_timestamp=detection_ts)
            if count == 1:
                triggers.append('first_of_day')

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
        if 'first_of_day' in triggers:
            return f"First sighting today: {common_name}"
        if 'rare_species' in triggers:
            return f"Rare species: {common_name}"
        return f"Bird detected: {common_name}"

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

        reasons = []
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
        bool: True if notification was sent successfully
    """
    try:
        import apprise
        ap = apprise.Apprise()
        ap.add(apprise_url)
        return ap.notify(
            title="BirdNET-PiPy Test Notification",
            body="If you see this, notifications are working correctly!"
        )
    except Exception as e:
        logger.error("Test notification failed", extra={'error': str(e)})
        return False
