"""Shared fixtures for notification service tests."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


DEFAULT_NOTIF_CONFIG = {
    'apprise_urls': ['tgram://bot/chat'],
    'every_detection': False,
    'rate_limit_seconds': 300,
    'first_of_day': False,
    'new_species': False,
    'rare_species': False,
    'rare_threshold': 3,
    'rare_window_days': 7,
}

DEFAULT_DISPLAY_CONFIG = {
    'bird_name_language': 'en',
}


def make_mock_settings(overrides=None, *, display=None):
    """Build a mock settings dict.

    ``overrides`` patches the notifications section (back-compat with existing
    tests). ``display`` patches the display section — used for bird-name
    localization tests.
    """
    notif = dict(DEFAULT_NOTIF_CONFIG)
    if overrides:
        notif.update(overrides)
    display_cfg = dict(DEFAULT_DISPLAY_CONFIG)
    if display:
        display_cfg.update(display)
    return {'notifications': notif, 'display': display_cfg}


@pytest.fixture
def notification_service():
    """Create a NotificationService with mocked settings.

    Yields (service, mock_settings_fn) where mock_settings_fn can be called
    to change the settings return value for hot-reload testing.
    """
    db = Mock()
    db.get_today_detection_count.return_value = 0
    db.get_species_total_count.return_value = 0
    db.get_recent_detection_count.return_value = 0

    settings_holder = [make_mock_settings()]

    with patch('core.notification_service.load_user_settings',
               side_effect=lambda: settings_holder[0]):
        from core.notification_service import NotificationService
        service = NotificationService(db)

        def set_settings(overrides=None, *, display=None):
            settings_holder[0] = make_mock_settings(overrides, display=display)
            # Refresh the service's stored settings so build methods called
            # outside _process_detection see the new language.
            service._load_config()

        yield service, set_settings
