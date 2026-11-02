"""Tests for the audio alert outbox: retry timing and per-URL bookkeeping."""

from datetime import datetime
from types import SimpleNamespace

import pytest

T0 = datetime(2024, 6, 15, 10, 30, 0)
T1 = datetime(2024, 6, 15, 10, 31, 0)
MAIL = 'mailtos://a'
NTFY = 'ntfy://b'

DEGRADED = {'state': 'degraded', 'previous_state': 'running'}
STOPPED = {'state': 'stopped', 'previous_state': 'degraded'}
RECOVERED = {'state': 'running', 'previous_state': 'degraded'}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Sender:
    """Stand-in for the service's send callback; fails for URLs in ``down``."""

    def __init__(self, down=()):
        self.down = set(down)
        self.attempts = 0
        self.delivered = []

    def __call__(self, alert):
        self.attempts += 1
        if alert.url in self.down:
            return False
        self.delivered.append(
            (alert.url, alert.payload['state'], alert.recovered_at))
        return True


@pytest.fixture
def clock(monkeypatch):
    # Swap the module's own ``time`` rather than patching time.monotonic
    # globally, which other threads in the test process rely on.
    import core.audio_alert_outbox as outbox_module
    fake = FakeClock()
    monkeypatch.setattr(outbox_module, 'time',
                        SimpleNamespace(monotonic=fake.monotonic))
    return fake


@pytest.fixture
def outbox(clock):
    from core.audio_alert_outbox import AudioAlertOutbox
    return AudioAlertOutbox()


class TestRetryTiming:

    def test_delivered_alert_leaves_nothing_pending(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        send = Sender()
        outbox.flush(send)

        assert send.delivered == [(MAIL, 'degraded', None)]
        assert len(outbox) == 0
        assert outbox.seconds_until_retry() is None
        assert not outbox.retry_due()

    def test_new_alert_is_due_immediately(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        assert outbox.retry_due()
        assert outbox.seconds_until_retry() == 0

    def test_failed_alert_is_kept_and_retried_after_the_delay(self, outbox, clock):
        from core.audio_alert_outbox import RETRY_INITIAL_SECONDS

        outbox.add([MAIL], DEGRADED, T0)
        outbox.flush(Sender(down=[MAIL]))

        assert len(outbox) == 1
        assert not outbox.retry_due()
        assert outbox.seconds_until_retry() == RETRY_INITIAL_SECONDS

        clock.advance(RETRY_INITIAL_SECONDS)
        assert outbox.retry_due()
        send = Sender()
        outbox.flush(send)
        assert send.delivered == [(MAIL, 'degraded', None)]
        assert len(outbox) == 0

    def test_backoff_doubles_up_to_the_cap(self, outbox, clock):
        from core.audio_alert_outbox import RETRY_MAX_SECONDS

        outbox.add([MAIL], DEGRADED, T0)
        delays = []
        for _ in range(8):
            outbox.flush(Sender(down=[MAIL]))
            delays.append(outbox.seconds_until_retry())
            clock.advance(delays[-1])

        assert delays == [15, 30, 60, 120, 240, 480, RETRY_MAX_SECONDS,
                          RETRY_MAX_SECONDS]

    def test_new_transition_resets_the_backoff(self, outbox, clock):
        from core.audio_alert_outbox import RETRY_INITIAL_SECONDS

        outbox.add([MAIL], DEGRADED, T0)
        for _ in range(4):
            outbox.flush(Sender(down=[MAIL]))
            clock.advance(outbox.seconds_until_retry())

        outbox.flush(Sender(down=[MAIL]))
        assert outbox.seconds_until_retry() > RETRY_INITIAL_SECONDS

        outbox.add([MAIL], RECOVERED, T1)
        assert outbox.retry_due()
        outbox.flush(Sender(down=[MAIL]))
        assert outbox.seconds_until_retry() == RETRY_INITIAL_SECONDS

    def test_expired_alerts_are_dropped(self, outbox, clock):
        from core.audio_alert_outbox import MAX_AGE_SECONDS

        outbox.add([MAIL], DEGRADED, T0)
        outbox.flush(Sender(down=[MAIL]))

        clock.advance(MAX_AGE_SECONDS)
        send = Sender()
        outbox.flush(send)
        assert send.attempts == 0
        assert len(outbox) == 0

    def test_send_error_drops_the_alert_instead_of_retrying_forever(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)

        def broken(_alert):
            raise ValueError('cannot build message')

        outbox.flush(broken)
        assert len(outbox) == 0

    def test_backlog_is_capped(self, outbox):
        from core.audio_alert_outbox import MAX_PENDING

        for _ in range(MAX_PENDING + 5):
            outbox.add([MAIL], DEGRADED, T0)
        assert len(outbox) == MAX_PENDING


class TestRecoveryMerging:

    def test_recovery_joins_an_undelivered_problem(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        outbox.flush(Sender(down=[MAIL]))
        outbox.add([MAIL], RECOVERED, T1)

        send = Sender()
        outbox.flush(send)
        assert send.delivered == [(MAIL, 'degraded', T1)]
        assert len(outbox) == 0

    def test_recovery_after_a_delivered_problem_is_its_own_alert(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        send = Sender()
        outbox.flush(send)
        outbox.add([MAIL], RECOVERED, T1)
        outbox.flush(send)

        assert send.delivered == [(MAIL, 'degraded', None),
                                  (MAIL, 'running', None)]

    def test_recovery_joins_only_the_latest_problem(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        outbox.add([MAIL], STOPPED, T0)
        outbox.add([MAIL], RECOVERED, T1)

        send = Sender()
        outbox.flush(send)
        assert send.delivered == [(MAIL, 'degraded', None),
                                  (MAIL, 'stopped', T1)]

    def test_second_recovery_does_not_rewrite_a_closed_episode(self, outbox):
        outbox.add([MAIL], DEGRADED, T0)
        outbox.add([MAIL], RECOVERED, T0)
        outbox.add([MAIL], RECOVERED, T1)

        send = Sender()
        outbox.flush(send)
        assert send.delivered == [(MAIL, 'degraded', T0),
                                  (MAIL, 'running', None)]


class TestPerUrlDelivery:

    def test_retry_reaches_only_the_url_that_missed_it(self, outbox, clock):
        outbox.add([MAIL, NTFY], DEGRADED, T0)
        first = Sender(down=[MAIL])
        outbox.flush(first)
        assert first.delivered == [(NTFY, 'degraded', None)]

        clock.advance(outbox.seconds_until_retry())
        retry = Sender()
        outbox.flush(retry)
        assert retry.delivered == [(MAIL, 'degraded', None)]

    def test_each_url_hears_about_the_recovery_in_its_own_terms(self, outbox):
        """The URL that missed the problem gets the whole episode; the one
        that already has it gets a plain recovery, not a repeat."""
        outbox.add([MAIL, NTFY], DEGRADED, T0)
        outbox.flush(Sender(down=[MAIL]))
        outbox.add([MAIL, NTFY], RECOVERED, T1)

        send = Sender()
        outbox.flush(send)
        assert sorted(send.delivered, key=lambda d: d[0]) == [
            (MAIL, 'degraded', T1),
            (NTFY, 'running', None),
        ]

    def test_later_alerts_for_a_failing_url_wait_their_turn(self, outbox, clock):
        outbox.add([MAIL], DEGRADED, T0)
        outbox.add([MAIL], STOPPED, T0)

        down = Sender(down=[MAIL])
        outbox.flush(down)
        assert down.attempts == 1  # the second is not tried out of order
        assert len(outbox) == 2

        clock.advance(outbox.seconds_until_retry())
        send = Sender()
        outbox.flush(send)
        assert [state for _url, state, _rec in send.delivered] == [
            'degraded', 'stopped']

    def test_one_failing_url_does_not_hold_back_another(self, outbox):
        outbox.add([MAIL, NTFY], DEGRADED, T0)
        outbox.add([MAIL, NTFY], STOPPED, T0)

        send = Sender(down=[MAIL])
        outbox.flush(send)
        assert send.delivered == [(NTFY, 'degraded', None),
                                  (NTFY, 'stopped', None)]
        assert len(outbox) == 2
