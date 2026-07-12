"""Notification service for bird detection alerts via Apprise.

Supports 100+ notification services (Telegram, Discord, Slack, ntfy, email, etc.).
Uses async queue with background worker thread, following birdweather_service.py pattern.
"""

import html
import queue
import threading
from datetime import datetime

from config.constants import RecorderState
from core.bird_name_utils import get_localized_common_name
from core.logging_config import get_logger
from core.runtime_config import get_runtime_settings, resolve_source_label
from core.timezone_service import local_now
from core.utils import build_detection_permalink

logger = get_logger(__name__)

NOTIFICATION_QUEUE_MAXSIZE = 100


class _AudioStatusEvent:
    """Queue envelope marking an audio-pipeline status change.

    Wrapping the payload (rather than putting a bare dict on the queue)
    keeps it unambiguously distinct from detection dicts the worker also
    processes.
    """

    __slots__ = ('payload',)

    def __init__(self, payload):
        self.payload = payload


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
        # Keep the full settings dict so the message-builders can reach the
        # display.bird_name_language preference without a second load.
        self._settings = settings
        notif = settings['notifications']
        self._apprise_urls = notif['apprise_urls']
        self._every_detection = notif['every_detection']
        self._rate_limit_seconds = notif['rate_limit_seconds']
        self._first_of_day = notif['first_of_day']
        self._new_species = notif['new_species']
        self._rare_species = notif['rare_species']
        self._rare_threshold = notif['rare_threshold']
        self._rare_window_days = notif['rare_window_days']
        self._audio_status = notif.get('audio_status', False)

    def notify(self, detection):
        """Queue detection for notification processing. Non-blocking."""
        try:
            self._queue.put_nowait(detection)
        except queue.Full:
            logger.warning("Notification queue full, dropping detection", extra={
                'species': detection.get('common_name')
            })

    def notify_audio_status(self, payload):
        """Queue an audio-pipeline status change for notification.

        Non-blocking. ``payload`` is a dict describing the transition; see
        ``_process_audio_status`` for the expected shape. The audio_status
        toggle is re-checked at send time so this is safe to call
        unconditionally from the recording thread.
        """
        try:
            self._queue.put_nowait(_AudioStatusEvent(payload))
        except queue.Full:
            logger.warning("Notification queue full, dropping audio status", extra={
                'state': payload.get('state'),
            })

    def _worker_loop(self):
        """Process notifications sequentially in background."""
        while True:
            item = self._queue.get()
            try:
                if isinstance(item, _AudioStatusEvent):
                    self._process_audio_status(item.payload)
                else:
                    self._process_detection(item)
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

    def _process_audio_status(self, payload):
        """Send an audio-pipeline status notification if enabled.

        ``payload`` keys:
            state:         current aggregate state ('degraded'|'stopped'|'running')
            previous_state: state before this transition (may be None)
            problem_sources: list of {label, state, error} for affected sources
                             (empty on a recovery)
        """
        self._load_config()

        if not self._apprise_urls or not self._audio_status:
            return

        state = payload.get('state', '')
        recovered = state == RecorderState.RUNNING

        if recovered:
            title = f"{self._station_prefix()}Audio recovered"
        elif state == RecorderState.STOPPED:
            title = f"{self._station_prefix()}Audio stopped"
        else:
            title = f"{self._station_prefix()}Audio degraded"

        message = self._build_audio_status_message(payload, recovered)
        self._send(title, message)

    def _build_audio_status_message(self, payload, recovered):
        """Build the audio-status notification body as HTML."""
        state = payload.get('state', '')
        previous_state = payload.get('previous_state')
        problem_sources = payload.get('problem_sources') or []

        when = self._format_when(local_now().isoformat())

        if recovered:
            headline = "Audio capture has recovered and is running normally."
        elif state == RecorderState.STOPPED:
            headline = "Audio capture has stopped — no recordings are being made."
        else:
            headline = "Audio capture is degraded."

        lines = [f"<b>{html.escape(headline)}</b>"]

        if previous_state:
            lines.append(
                f"State: {html.escape(str(previous_state))} → {html.escape(str(state))}"
            )
        else:
            lines.append(f"State: {html.escape(str(state))}")

        for src in problem_sources:
            label = html.escape(str(src.get('label', 'Unknown source')))
            src_state = html.escape(str(src.get('state', '')))
            lines.append(f"<b>{label}</b> ({src_state})")
            error = src.get('error')
            if error:
                # Errors can be multi-line ffmpeg output; keep it compact.
                snippet = str(error).strip().splitlines()[0][:200]
                lines.append(f"  {html.escape(snippet)}")

        lines.append(f"Time: {html.escape(when)}")

        station = self._settings.get('display', {}).get('station_name', '').strip()
        if station:
            lines.append(f"Station: {html.escape(station)}")

        return '<br>\n'.join(lines)

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

    def _station_prefix(self):
        """Return '[Station Name] ' if station_name is configured, else ''."""
        station = self._settings.get('display', {}).get('station_name', '').strip()
        return f"[{station}] " if station else ""

    def _build_title(self, detection, triggers):
        """Build notification title based on most notable trigger."""
        display_name = get_localized_common_name(
            detection.get('scientific_name'),
            detection.get('common_name'),
            settings=self._settings,
        ) or 'Unknown'
        prefix = self._station_prefix()
        if 'new_species' in triggers:
            return f"{prefix}New species: {display_name}"
        if 'first_of_day' in triggers:
            return f"{prefix}First sighting today: {display_name}"
        if 'rare_species' in triggers:
            return f"{prefix}Rare species: {display_name}"
        return f"{prefix}Bird detected: {display_name}"

    def _format_when(self, timestamp):
        """Format an ISO timestamp as 'YYYY-MM-DD HH:MM:SS', honoring the
        user's display.time_format ('12h' / '24h'). Unset or legacy values
        fall back to 24-hour, matching the stored ISO time.
        """
        if not timestamp:
            return ''
        try:
            dt = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            # Best-effort: drop the 'T' separator and fractional seconds.
            return timestamp.replace('T', ' ').split('.')[0]

        fmt = self._settings.get('display', {}).get('time_format')
        if fmt == '12h':
            # %I is zero-padded (01–12); strip the leading zero for "2:30:05 PM".
            time_part = dt.strftime('%I:%M:%S %p').lstrip('0')
        else:
            time_part = dt.strftime('%H:%M:%S')
        return f"{dt.strftime('%Y-%m-%d')} {time_part}"

    def _build_detection_link(self, detection):
        """Absolute permalink for this detection, or None when unavailable.

        Requires display.site_url (owner-configured — notifications run
        outside any HTTP request, so there is no external URL to derive) and
        the detection's DB row id. A share token is appended only when the
        station is private (auth on, public access off): everywhere else the
        bare link already works, and skipping the token keeps routine
        notification emails out of the share-secret mass-revocation blast
        radius. "Already works" leans on the public recent window
        (api.RECORDINGS_PUBLIC_WINDOW_DAYS) and the share-token TTL
        (share_tokens.SHARE_TOKEN_TTL_SECONDS) both being 30 days — if the
        public window ever shrinks below the token TTL, revisit this gate.
        """
        base = (self._settings.get('display', {}).get('site_url') or '').strip()
        detection_id = detection.get('id')
        if not base or not detection_id:
            return None

        # Imported lazily: core.auth drags in flask + bcrypt (~21MB RSS),
        # which the recording container shouldn't pay at startup for a
        # feature that is off by default.
        from core.auth import is_auth_enabled, is_public_access_enabled
        from core.share_tokens import mint_share_token

        token = None
        try:
            if is_auth_enabled() and not is_public_access_enabled():
                token = mint_share_token(detection_id)
        except Exception as e:
            # A private station's bare link dead-ends for logged-out readers,
            # but the notification is still useful — send it without a token.
            logger.warning("Could not mint share token for notification link",
                           extra={'error': str(e)})
        return build_detection_permalink(
            base, detection.get('common_name'), detection_id, share_token=token
        )

    @staticmethod
    def _resolve_source_label(source_id):
        """Look up human-readable label for a source ID from runtime settings."""
        return resolve_source_label(source_id, fallback=source_id)

    def _build_message(self, detection, triggers):
        """Build the notification body as HTML.

        Apprise downconverts this to clean plain text for services that
        don't render HTML (Telegram, ntfy, etc.), so email gets the rich
        version while everything else stays readable. User-controllable
        fields are HTML-escaped to keep the markup intact.
        """
        sci_name = detection.get('scientific_name', '')
        display_name = get_localized_common_name(
            sci_name,
            detection.get('common_name'),
            settings=self._settings,
        ) or 'Unknown'
        confidence = detection.get('confidence', 0)
        timestamp = detection.get('timestamp', '')

        when = self._format_when(timestamp)

        esc_name = html.escape(display_name)
        esc_sci = html.escape(sci_name)

        lines = [
            f"<b>{esc_name}</b>" + (f" <i>({esc_sci})</i>" if esc_sci else ""),
            f"Confidence: {confidence * 100:.0f}%",
            f"Time: {html.escape(when)}",
        ]

        # Include source label if available
        audio_source = detection.get('audio_source')
        if audio_source:
            source_label = self._resolve_source_label(audio_source)
            lines.append(f"Source: {html.escape(str(source_label))}")

        station = self._settings.get('display', {}).get('station_name', '').strip()
        if station:
            lines.append(f"Station: {html.escape(station)}")

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
            lines.append(f"Trigger: {html.escape(', '.join(reasons))}")

        link = self._build_detection_link(detection)
        if link:
            # The URL is its own link text so Apprise's HTML→text
            # downconversion (ntfy etc.) keeps a usable URL instead of a
            # bare label whose href got stripped.
            esc_link = html.escape(link, quote=True)
            lines.append(f'<a href="{esc_link}">{esc_link}</a>')

        return '<br>\n'.join(lines)

    def _send(self, title, message):
        """Send notification to all configured Apprise URLs."""
        try:
            import apprise
            ap = apprise.Apprise()
            for url in self._apprise_urls:
                ap.add(url)
            result = ap.notify(
                title=title,
                body=message,
                body_format=apprise.NotifyFormat.HTML,
            )
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
