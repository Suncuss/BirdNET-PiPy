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
                service._send("Test Title", "Test Body")
                MockApprise.assert_called_once()
                assert mock_apprise_instance.add.call_count == 2
                mock_apprise_instance.add.assert_any_call('tgram://bot/chat')
                mock_apprise_instance.add.assert_any_call('discord://webhook')
                mock_apprise_instance.notify.assert_called_once_with(
                    title="Test Title", body="Test Body")
        finally:
            patcher.stop()

    def test_build_title_first_of_day(self, notification_service):
        """Title shows 'First sighting today' for first_of_day trigger."""
        service, _ = notification_service
        detection = make_detection(common_name='Robin')
        title = service._build_title(detection, ['first_of_day', 'every_detection'])
        assert 'First sighting today' in title
        assert 'Robin' in title

    def test_build_title_rare_species(self, notification_service):
        """Title shows 'Rare species' for rare_species trigger."""
        service, _ = notification_service
        detection = make_detection(common_name='Warbler')
        title = service._build_title(detection, ['rare_species'])
        assert 'Rare species' in title
        assert 'Warbler' in title

    def test_build_title_every_detection(self, notification_service):
        """Title shows 'Bird detected' for every_detection trigger only."""
        service, _ = notification_service
        detection = make_detection(common_name='Sparrow')
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
        assert '14:30:00' in message

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
            result = send_test_notification('tgram://bot/chat')
            assert result is True
            mock_apprise_instance.add.assert_called_once_with('tgram://bot/chat')
            mock_apprise_instance.notify.assert_called_once()

    def test_send_test_notification_returns_false_on_failure(self):
        """send_test_notification returns False when Apprise fails."""
        mock_apprise_instance = Mock()
        mock_apprise_instance.notify.return_value = False

        with patch('apprise.Apprise', return_value=mock_apprise_instance):
            from core.notification_service import send_test_notification
            result = send_test_notification('invalid://url')
            assert result is False
