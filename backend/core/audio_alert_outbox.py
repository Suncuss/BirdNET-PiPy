"""Undelivered audio-status alerts, held and retried until they get through.

The usual reason an alert fails to send is the outage it reports: a dropped
uplink takes a remote stream and the notification route down together. With
a single attempt the "degraded" message is lost and only the "recovered"
one arrives, because that one is sent once the route is back.
"""

import time
from dataclasses import dataclass
from datetime import datetime

from config.constants import RecorderState
from core.logging_config import get_logger

logger = get_logger(__name__)

RETRY_INITIAL_SECONDS = 15
RETRY_MAX_SECONDS = 600
# A problem nobody could be told about for a day is no longer news.
MAX_AGE_SECONDS = 24 * 3600
MAX_PENDING = 50


@dataclass
class AudioAlert:
    """One audio-status message still owed to one notification URL."""

    url: str
    payload: dict
    occurred_at: datetime
    expires_at: float  # time.monotonic() deadline
    # Set when the recovery arrived before this problem alert was delivered;
    # the two then go out as a single message.
    recovered_at: datetime | None = None

    @property
    def awaiting_recovery(self) -> bool:
        return (self.recovered_at is None
                and self.payload.get('state') != RecorderState.RUNNING)


class AudioAlertOutbox:
    """Pending alerts, oldest first, with one shared retry timer.

    Every URL gets its own copy of an alert, so a retry reaches only the
    services that missed it; resending to all of them would repeat the
    alert on the ones that already have it.

    Not thread-safe: owned by the notification worker thread.
    """

    def __init__(self):
        self._alerts: list[AudioAlert] = []
        self._retry_delay = RETRY_INITIAL_SECONDS
        self._retry_at = 0.0

    def __len__(self) -> int:
        return len(self._alerts)

    def add(self, urls, payload, occurred_at) -> None:
        """Queue a status transition for each URL, due immediately."""
        recovered = payload.get('state') == RecorderState.RUNNING
        expires_at = time.monotonic() + MAX_AGE_SECONDS
        for url in urls:
            last = next((a for a in reversed(self._alerts) if a.url == url), None)
            if recovered and last is not None and last.awaiting_recovery:
                last.recovered_at = occurred_at
            else:
                self._alerts.append(
                    AudioAlert(url, payload, occurred_at, expires_at))

        overflow = len(self._alerts) - MAX_PENDING
        if overflow > 0:
            del self._alerts[:overflow]
            logger.warning("Audio alert backlog full, dropping oldest",
                           extra={'dropped': overflow})

        # A state change is the best hint that the route may be back.
        self._retry_delay = RETRY_INITIAL_SECONDS
        self._retry_at = 0.0

    def retry_due(self) -> bool:
        return bool(self._alerts) and time.monotonic() >= self._retry_at

    def seconds_until_retry(self) -> float | None:
        """How long the worker may sleep; None when nothing is pending."""
        if not self._alerts:
            return None
        return max(0.0, self._retry_at - time.monotonic())

    def flush(self, send) -> None:
        """Attempt every pending alert; ``send(alert)`` is True once delivered.

        Alerts that fail stay queued for the next attempt.
        """
        now = time.monotonic()
        failed_urls = set()
        pending = []
        expired = 0
        for alert in self._alerts:
            if alert.expires_at <= now:
                expired += 1
                continue
            # After a failure, that URL's later alerts wait their turn so
            # its messages arrive in order.
            if alert.url in failed_urls or not self._attempt(send, alert):
                failed_urls.add(alert.url)
                pending.append(alert)
        self._alerts = pending

        if expired:
            logger.warning("Giving up on undelivered audio alerts",
                           extra={'count': expired})
        if pending:
            logger.info("Audio alerts held for retry", extra={
                'pending': len(pending), 'retry_in_seconds': self._retry_delay,
            })
            self.defer_retry()
        else:
            self._retry_delay = RETRY_INITIAL_SECONDS

    @staticmethod
    def _attempt(send, alert) -> bool:
        try:
            return bool(send(alert))
        except Exception as e:
            # A message that fails to build won't build on a retry either.
            logger.error("Dropping audio alert that could not be sent",
                         extra={'error': str(e)})
            return True

    def defer_retry(self) -> None:
        """Schedule the next attempt, backing off further each time."""
        self._retry_at = time.monotonic() + self._retry_delay
        self._retry_delay = min(self._retry_delay * 2, RETRY_MAX_SECONDS)

    def clear(self) -> None:
        self._alerts.clear()
