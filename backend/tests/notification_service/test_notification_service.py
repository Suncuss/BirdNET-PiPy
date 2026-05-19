"""Tests for the notification service."""

import queue
from unittest.mock import Mock, patch

from tests.notification_service.conftest import make_mock_settings


def make_detection(common_name='American Robin', scientific_name='Turdus migratorius',
                   confidence=0.95, timestamp='2024-06-15T10:30:00'):
    return {
        'common_name': common_name,
        'scientific_name': scientific_name,
        'confidence': confidence,
        'timestamp': timestamp,
    }


def _create_service(notif_overrides=None, db_manager=None):
    """Create a NotificationService with mocked load_user_settings.

    Returns (service, patcher) — caller must use as context manager or call patcher.stop().
    """
    if db_manager is None:
        db_manager = Mock()
        db_manager.get_today_detection_count.return_value = 0
        db_manager.get_species_total_count.return_value = 0
        db_manager.get_recent_detection_count.return_value = 0

    mock_settings = make_mock_settings(notif_overrides)
    patcher = patch('core.notification_service.load_user_settings',
                    return_value=mock_settings)
    patcher.start()

    from core.notification_service import NotificationService
    service = NotificationService(db_manager)
    return service, patcher


class TestNotificationService:
    """Test NotificationService trigger logic and behavior."""

    def test_every_detection_trigger_fires(self):
        """Every detection trigger sends notification when enabled."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'every_detection': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_called_once()
        finally:
            patcher.stop()

    def test_every_detection_trigger_does_not_fire_when_disabled(self):
        """Every detection trigger does not fire when disabled."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'every_detection': False},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_first_of_day_trigger_fires_when_count_is_one(self):
        """First of day trigger fires when today's count is exactly 1."""
        db = Mock()
        db.get_today_detection_count.return_value = 1
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'first_of_day': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_called_once()
                title = mock_send.call_args[0][0]
                assert 'First sighting today' in title
        finally:
            patcher.stop()

    def test_first_of_day_trigger_does_not_fire_when_count_above_one(self):
        """First of day trigger does not fire when there are multiple detections today."""
        db = Mock()
        db.get_today_detection_count.return_value = 2
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'first_of_day': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_new_species_trigger_fires_when_total_is_one(self):
        """New species trigger fires when species total count is exactly 1."""
        db = Mock()
        db.get_today_detection_count.return_value = 1
        db.get_species_total_count.return_value = 1
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'new_species': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_called_once()
                title = mock_send.call_args[0][0]
                assert 'New species' in title
        finally:
            patcher.stop()

    def test_new_species_trigger_does_not_fire_when_seen_before(self):
        """New species trigger does not fire when species has been seen before."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_species_total_count.return_value = 10
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'new_species': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_rare_species_trigger_fires_when_below_threshold(self):
        """Rare species trigger fires when recent count is at or below threshold."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 2
        service, patcher = _create_service(
            notif_overrides={'rare_species': True, 'rare_threshold': 3, 'rare_window_days': 7},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_called_once()
                title = mock_send.call_args[0][0]
                assert 'Rare species' in title
        finally:
            patcher.stop()

    def test_rare_species_trigger_does_not_fire_above_threshold(self):
        """Rare species trigger does not fire when count exceeds threshold."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 10
        service, patcher = _create_service(
            notif_overrides={'rare_species': True, 'rare_threshold': 3, 'rare_window_days': 7},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_multiple_triggers_single_notification(self):
        """Multiple triggers firing results in a single notification."""
        db = Mock()
        db.get_today_detection_count.return_value = 1
        db.get_recent_detection_count.return_value = 1
        service, patcher = _create_service(
            notif_overrides={
                'every_detection': True,
                'first_of_day': True,
                'rare_species': True,
                'rare_threshold': 3,
                'rare_window_days': 7,
                'rate_limit_seconds': 0,
            },
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_called_once()
        finally:
            patcher.stop()

    def test_rate_limit_per_species(self):
        """Rate limit applies per species independently."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'every_detection': True, 'rate_limit_seconds': 300},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                # First detection of species A
                service._process_detection(make_detection(
                    common_name='Robin', scientific_name='Turdus migratorius',
                    timestamp='2024-06-15T10:00:00'))
                assert mock_send.call_count == 1

                # Second detection of species A within rate limit
                service._process_detection(make_detection(
                    common_name='Robin', scientific_name='Turdus migratorius',
                    timestamp='2024-06-15T10:01:00'))
                assert mock_send.call_count == 1  # Suppressed

                # Detection of species B (different species, should go through)
                service._process_detection(make_detection(
                    common_name='Blue Jay', scientific_name='Cyanocitta cristata',
                    timestamp='2024-06-15T10:01:00'))
                assert mock_send.call_count == 2
        finally:
            patcher.stop()

    def test_rate_limit_allows_after_window(self):
        """Rate limit allows notification after the rate limit window passes."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 100
        service, patcher = _create_service(
            notif_overrides={'every_detection': True, 'rate_limit_seconds': 300},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                # First detection
                service._process_detection(make_detection(timestamp='2024-06-15T10:00:00'))
                assert mock_send.call_count == 1

                # Detection after rate limit (6 min later > 5 min limit)
                service._process_detection(make_detection(timestamp='2024-06-15T10:06:00'))
                assert mock_send.call_count == 2
        finally:
            patcher.stop()

    def test_queue_full_drops_without_crash(self):
        """Queue full drops detection without crashing."""
        db = Mock()
        service, patcher = _create_service(db_manager=db)

        try:
            # Fill the queue
            for _i in range(100):
                try:
                    service._queue.put_nowait(make_detection())
                except queue.Full:
                    break

            # This should not raise
            service.notify(make_detection())
        finally:
            patcher.stop()

    def test_send_calls_apprise_with_all_urls(self):
        """Send method adds all URLs and calls notify."""
        urls = ['tgram://bot/chat', 'discord://webhook']
        service, patcher = _create_service(
            notif_overrides={'apprise_urls': urls})

        try:
            mock_apprise_instance = Mock()
            mock_apprise_instance.notify.return_value = True

            with patch('apprise.Apprise', return_value=mock_apprise_instance) as MockApprise:
                import apprise
                service._send("Test Title", "Test Body")
                MockApprise.assert_called_once()
                assert mock_apprise_instance.add.call_count == 2
                mock_apprise_instance.add.assert_any_call('tgram://bot/chat')
                mock_apprise_instance.add.assert_any_call('discord://webhook')
                mock_apprise_instance.notify.assert_called_once_with(
                    title="Test Title",
                    body="Test Body",
                    body_format=apprise.NotifyFormat.HTML)
        finally:
            patcher.stop()

    def test_build_title_new_species(self, notification_service):
        """Title shows 'New species' for new_species trigger (highest priority)."""
        service, _ = notification_service
        # Empty scientific_name pins the test to common_name formatting only;
        # localization is exercised separately below.
        detection = make_detection(common_name='Snowy Owl', scientific_name='')
        title = service._build_title(detection, ['new_species', 'first_of_day'])
        assert 'New species' in title
        assert 'Snowy Owl' in title

    def test_build_title_first_of_day(self, notification_service):
        """Title shows 'First sighting today' for first_of_day trigger."""
        service, _ = notification_service
        detection = make_detection(common_name='Robin', scientific_name='')
        title = service._build_title(detection, ['first_of_day', 'every_detection'])
        assert 'First sighting today' in title
        assert 'Robin' in title

    def test_build_title_rare_species(self, notification_service):
        """Title shows 'Rare species' for rare_species trigger."""
        service, _ = notification_service
        detection = make_detection(common_name='Warbler', scientific_name='')
        title = service._build_title(detection, ['rare_species'])
        assert 'Rare species' in title
        assert 'Warbler' in title

    def test_build_title_every_detection(self, notification_service):
        """Title shows 'Bird detected' for every_detection trigger only."""
        service, _ = notification_service
        detection = make_detection(common_name='Sparrow', scientific_name='')
        title = service._build_title(detection, ['every_detection'])
        assert 'Bird detected' in title
        assert 'Sparrow' in title

    def test_build_message_contains_species_info(self, notification_service):
        """Message contains species name, confidence, and time."""
        service, _ = notification_service
        detection = make_detection(
            common_name='Robin',
            scientific_name='Turdus migratorius',
            confidence=0.92,
            timestamp='2024-06-15T14:30:00'
        )
        message = service._build_message(detection, ['every_detection'])
        assert 'Robin' in message
        assert 'Turdus migratorius' in message
        assert '92%' in message
        assert '2024-06-15 14:30:00' in message  # defaults to 24h

    def test_build_message_respects_12h_time_format(self, notification_service):
        """Message time follows display.time_format = '12h'."""
        service, set_settings = notification_service
        set_settings(display={'time_format': '12h'})
        detection = make_detection(timestamp='2024-06-15T14:30:05')
        message = service._build_message(detection, ['every_detection'])
        assert '2024-06-15 2:30:05 PM' in message

    def test_build_message_respects_24h_time_format(self, notification_service):
        """Message time follows display.time_format = '24h'."""
        service, set_settings = notification_service
        set_settings(display={'time_format': '24h'})
        detection = make_detection(timestamp='2024-06-15T14:30:05')
        message = service._build_message(detection, ['every_detection'])
        assert '2024-06-15 14:30:05' in message

    def test_process_detection_returns_early_when_no_urls(self):
        """_process_detection returns early when apprise_urls is empty."""
        db = Mock()
        service, patcher = _create_service(
            notif_overrides={'apprise_urls': [], 'every_detection': True},
            db_manager=db)

        try:
            with patch.object(service, '_send') as mock_send:
                service._process_detection(make_detection())
                mock_send.assert_not_called()
                # DB should not be queried either
                db.get_today_detection_count.assert_not_called()
        finally:
            patcher.stop()

    def test_config_hot_reload(self):
        """Changing mock return value between calls simulates config hot-reload."""
        db = Mock()
        db.get_today_detection_count.return_value = 5
        db.get_recent_detection_count.return_value = 100

        settings_holder = [make_mock_settings({'every_detection': False})]
        patcher = patch('core.notification_service.load_user_settings',
                        side_effect=lambda: settings_holder[0])
        patcher.start()

        try:
            from core.notification_service import NotificationService
            service = NotificationService(db)

            with patch.object(service, '_send') as mock_send:
                # With every_detection=False, no notification
                service._process_detection(make_detection())
                mock_send.assert_not_called()

                # Simulate config change: enable every_detection
                settings_holder[0] = make_mock_settings({
                    'every_detection': True,
                    'rate_limit_seconds': 0,
                })

                service._process_detection(make_detection(timestamp='2024-06-15T11:00:00'))
                mock_send.assert_called_once()
        finally:
            patcher.stop()


class TestNotificationServiceFactory:
    """Test the singleton factory and test notification function."""

    def test_get_notification_service_creates_with_db_manager(self):
        """Factory creates instance when db_manager is provided."""
        import core.notification_service as ns
        ns._notification_service = None

        with patch('core.notification_service.load_user_settings',
                   return_value=make_mock_settings()):
            result = ns.get_notification_service(Mock())
            assert result is not None

        # Cleanup
        ns._notification_service = None

    def test_get_notification_service_returns_none_without_db_manager(self):
        """Factory returns None when no db_manager provided and no existing instance."""
        import core.notification_service as ns
        ns._notification_service = None

        result = ns.get_notification_service()
        assert result is None

    def test_get_notification_service_returns_same_instance(self):
        """Factory returns the same singleton instance on repeated calls."""
        import core.notification_service as ns
        ns._notification_service = None

        with patch('core.notification_service.load_user_settings',
                   return_value=make_mock_settings()):
            first = ns.get_notification_service(Mock())
            second = ns.get_notification_service(Mock())
            assert first is second

        # Cleanup
        ns._notification_service = None

    def test_get_notification_service_skips_when_no_urls(self):
        """Factory returns None when apprise_urls is empty."""
        import core.notification_service as ns
        ns._notification_service = None

        with patch('core.notification_service.load_user_settings',
                   return_value=make_mock_settings({'apprise_urls': []})):
            result = ns.get_notification_service(Mock())
            assert result is None

        # Cleanup
        ns._notification_service = None

    def test_send_test_notification_calls_apprise(self):
        """send_test_notification creates Apprise and sends."""
        mock_apprise_instance = Mock()
        mock_apprise_instance.notify.return_value = True

        with patch('apprise.Apprise', return_value=mock_apprise_instance):
            from core.notification_service import send_test_notification
            success, message = send_test_notification('tgram://bot/chat')
            assert success is True
            assert 'success' in message.lower()
            mock_apprise_instance.add.assert_called_once_with('tgram://bot/chat')
            mock_apprise_instance.notify.assert_called_once()

    def test_send_test_notification_returns_error_on_failure(self):
        """send_test_notification returns (False, error_detail) when Apprise fails."""
        mock_apprise_instance = Mock()
        mock_apprise_instance.notify.return_value = False

        with patch('apprise.Apprise', return_value=mock_apprise_instance):
            from core.notification_service import send_test_notification
            success, message = send_test_notification('invalid://url')
            assert success is False
            assert isinstance(message, str)
            assert len(message) > 0

    def test_extract_apprise_error_friendly_messages(self):
        """_extract_apprise_error maps known errors to friendly messages."""
        from core.notification_service import _extract_apprise_error

        assert 'resolve hostname' in _extract_apprise_error('socket.gaierror: Name or service not known')
        assert 'Connection refused' in _extract_apprise_error('ConnectionRefusedError: Connection refused')
        assert 'timed out' in _extract_apprise_error('socket.timeout: timed out')
        assert 'Check your configuration' in _extract_apprise_error('')
        assert 'Check your configuration' in _extract_apprise_error('   ')

    def test_extract_apprise_error_raw_message(self):
        """_extract_apprise_error returns raw message for unknown errors."""
        from core.notification_service import _extract_apprise_error

        result = _extract_apprise_error('MQTT Connection Error received from 127.0.0.1:9999')
        assert result == 'MQTT Connection Error received from 127.0.0.1:9999'


class TestNotificationStationName:
    """Title prefix and body line include display.station_name when set."""

    def test_title_has_station_prefix_when_set(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'station_name': 'Backyard'})

        detection = make_detection(common_name='Robin', scientific_name='')
        title = service._build_title(detection, ['new_species'])
        assert title.startswith('[Backyard] ')
        assert 'New species' in title

    def test_title_has_no_prefix_when_station_name_empty(self, notification_service):
        service, _set_settings = notification_service
        # Default fixture leaves station_name unset.
        detection = make_detection(common_name='Robin', scientific_name='')
        title = service._build_title(detection, ['new_species'])
        assert not title.startswith('[')

    def test_title_ignores_whitespace_only_station_name(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'station_name': '   '})

        detection = make_detection(common_name='Robin', scientific_name='')
        title = service._build_title(detection, ['every_detection'])
        assert not title.startswith('[')

    def test_message_includes_station_line_when_set(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'station_name': 'Backyard'})

        detection = make_detection()
        message = service._build_message(detection, ['every_detection'])
        assert 'Station: Backyard' in message

    def test_message_omits_station_line_when_empty(self, notification_service):
        service, _set_settings = notification_service
        detection = make_detection()
        message = service._build_message(detection, ['every_detection'])
        assert 'Station:' not in message


class TestNotificationHtmlSafety:
    """The HTML body must escape user-controllable fields so a stray
    ``&`` or ``<`` in a station/species name can't break the markup
    (regression guard for the plain-text -> HTML body switch).
    """

    def test_station_name_is_html_escaped(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'station_name': "Tom & Jerry's <Yard>"})
        detection = make_detection()
        message = service._build_message(detection, ['every_detection'])
        assert 'Tom &amp; Jerry&#x27;s &lt;Yard&gt;' in message
        assert '<Yard>' not in message

    def test_species_name_is_html_escaped(self, notification_service):
        service, _set_settings = notification_service
        detection = make_detection(
            common_name='Fish & Chips <bird>', scientific_name='A & B')
        message = service._build_message(detection, ['every_detection'])
        assert 'Fish &amp; Chips &lt;bird&gt;' in message
        assert 'A &amp; B' in message

    def test_malformed_timestamp_falls_back_gracefully(self, notification_service):
        service, _set_settings = notification_service
        detection = make_detection(timestamp='not-a-timestamp')
        message = service._build_message(detection, ['every_detection'])
        # Best-effort fallback: no crash, raw value passed through.
        assert 'not-a-timestamp' in message


class TestNotificationLanguageLocalization:
    """Notification body honors display.bird_name_language (regression for #47).

    The notification path used to pull common_name straight off the detection
    dict, ignoring the user's language preference. These tests pin the
    localized behavior so that regression cannot recur.
    """

    def test_german_setting_localizes_title(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'bird_name_language': 'de'})

        # Simulate a V2-emitted detection: common_name is the V2 English
        # variant, scientific_name is the stable key.
        detection = make_detection(
            common_name='Eurasian Blackbird',
            scientific_name='Turdus merula',
        )
        title = service._build_title(detection, ['new_species'])
        assert 'Amsel' in title
        assert 'Eurasian Blackbird' not in title

    def test_german_setting_localizes_message_body(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'bird_name_language': 'de'})

        detection = make_detection(
            common_name='Eurasian Blackbird',
            scientific_name='Turdus merula',
            confidence=0.92,
            timestamp='2024-06-15T14:30:00',
        )
        message = service._build_message(detection, ['every_detection'])
        assert 'Amsel' in message
        assert 'Turdus merula' in message  # scientific name still shown in parens

    def test_english_setting_keeps_english_name(self, notification_service):
        service, _set_settings = notification_service
        # Default fixture is English; no override needed.
        detection = make_detection(
            common_name='Eurasian Blackbird',
            scientific_name='Turdus merula',
        )
        title = service._build_title(detection, ['every_detection'])
        # Under English we render the species table's canonical English
        # ('Common Blackbird' for Turdus merula), not the V2 variant.
        assert 'Common Blackbird' in title or 'Eurasian Blackbird' in title
        assert 'Amsel' not in title

    def test_unknown_species_falls_back_to_common_name(self, notification_service):
        service, set_settings = notification_service
        set_settings(display={'bird_name_language': 'de'})

        detection = make_detection(
            common_name='Some Custom Migrated Name',
            scientific_name='Fakeus birdus',
        )
        title = service._build_title(detection, ['rare_species'])
        # Resolver can't find this species; helper returns the input
        # common_name. The notification still works.
        assert 'Some Custom Migrated Name' in title


class TestAudioStatusNotifications:
    """Tests for the audio-pipeline status notification path."""

    def test_audio_status_disabled_does_not_send(self):
        service, patcher = _create_service(
            notif_overrides={'audio_status': False})
        try:
            with patch.object(service, '_send') as mock_send:
                service._process_audio_status({
                    'state': 'degraded', 'previous_state': 'running',
                    'problem_sources': [{'label': 'Cam', 'state': 'degraded',
                                         'error': 'boom'}],
                })
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_audio_status_enabled_sends_degraded(self):
        service, patcher = _create_service(
            notif_overrides={'audio_status': True})
        try:
            with patch.object(service, '_send') as mock_send:
                service._process_audio_status({
                    'state': 'degraded', 'previous_state': 'running',
                    'problem_sources': [{'label': 'Backyard Cam',
                                         'state': 'degraded',
                                         'error': 'RTSP recording failed: timeout'}],
                })
                mock_send.assert_called_once()
                title, body = mock_send.call_args.args
                assert 'degraded' in title.lower()
                assert 'Backyard Cam' in body
                assert 'timeout' in body
        finally:
            patcher.stop()

    def test_audio_status_recovery_message(self):
        service, patcher = _create_service(
            notif_overrides={'audio_status': True})
        try:
            with patch.object(service, '_send') as mock_send:
                service._process_audio_status({
                    'state': 'running', 'previous_state': 'degraded',
                    'problem_sources': [],
                })
                title, body = mock_send.call_args.args
                assert 'recovered' in title.lower()
                assert 'recovered' in body.lower()
        finally:
            patcher.stop()

    def test_audio_status_no_urls_does_not_send(self):
        service, patcher = _create_service(
            notif_overrides={'audio_status': True, 'apprise_urls': []})
        try:
            with patch.object(service, '_send') as mock_send:
                service._process_audio_status({
                    'state': 'stopped', 'previous_state': 'running',
                    'problem_sources': [],
                })
                mock_send.assert_not_called()
        finally:
            patcher.stop()

    def test_audio_status_envelope_is_distinct_from_detection(self):
        from core.notification_service import _AudioStatusEvent
        payload = {'state': 'stopped'}
        ev = _AudioStatusEvent(payload)
        assert ev.payload is payload
        assert not isinstance(ev, dict)

    def test_notify_audio_status_enqueues_and_worker_dispatches(self):
        import time

        service, patcher = _create_service(
            notif_overrides={'audio_status': True})
        try:
            with patch.object(service, '_process_audio_status') as mock_proc:
                payload = {'state': 'stopped', 'previous_state': 'running',
                           'problem_sources': []}
                service.notify_audio_status(payload)

                # Background worker thread routes the envelope.
                deadline = time.time() + 2
                while time.time() < deadline and not mock_proc.called:
                    time.sleep(0.01)

                mock_proc.assert_called_once_with(payload)
        finally:
            patcher.stop()
