"""A saved file from any version must load into a valid document.

Every value rule carries its repair. The first test breaks every rule at
once, so adding a rule without extending the document here fails the count,
and a repair that does not satisfy its own check fails validation.
"""
import copy

import pytest


def broken_everywhere():
    from config.settings import get_default_settings
    settings = get_default_settings()
    settings['location'].update(latitude=95, longitude=-200, timezone='Mars/Olympus')
    settings['detection'].update(sensitivity=5, cutoff=2, species_filter_threshold=-1)
    settings['storage'].update(trigger_percent=-5, target_percent=150, keep_per_species=-1,
                               keep_recent_per_species=2.5, retention_days=-3, media_budget_gb=-1,
                               check_interval_minutes=0)
    settings['spectrogram'].update(min_freq_khz=30, max_freq_khz=-1, min_dbfs=5, max_dbfs=-300)
    settings['audio'].update(recording_length=7, overlap=0.3, recording_chunk_length=4, next_source_id=-1,
                             sources=[{'id': 'mic', 'type': 'pulseaudio'},
                                      {'id': 'source_5', 'type': 'pulseaudio', 'device': 'usb'}])
    settings['model']['type'] = 'birdnet_v9'
    settings['updates']['channel'] = 'stable'
    settings['display'].update(time_format='auto', bird_name_language='tlh')
    settings['notifications'].update(rare_threshold=-1, rare_window_days=0, rate_limit_seconds=-5)
    settings['schedule'] = {'quiet_hours': {'enabled': True, 'start': '25:00', 'end': '06:00'}}
    return settings


def test_every_rule_repairs_its_own_violation():
    from core.settings_validation import (
        _RULES,
        repair_settings,
        validate_settings,
        validate_settings_shape,
    )
    settings = broken_everywhere()
    assert validate_settings_shape(settings) is None, 'the document must be readable, only its values wrong'
    repairs = repair_settings(settings)
    assert len(repairs) == len(_RULES), f'{len(_RULES)} rules but {len(repairs)} repairs: {repairs}'
    assert validate_settings(settings) is None
    assert repair_settings(settings) == []


def test_ordering_repairs_prefer_the_higher_side_the_user_set():
    from config.settings import get_default_settings
    from core.settings_validation import repair_settings
    settings = get_default_settings()
    settings['storage'].update(trigger_percent=70, target_percent=70)
    assert repair_settings(settings) == ['storage.target_percent must be less than trigger_percent']
    assert (settings['storage']['trigger_percent'], settings['storage']['target_percent']) == (70, 65)
    settings['storage'].update(trigger_percent=3, target_percent=3)
    repair_settings(settings)
    assert (settings['storage']['trigger_percent'], settings['storage']['target_percent']) == (3, 0)
    # With no room below the threshold at all, the pair resets to the defaults.
    settings['storage'].update(trigger_percent=0, target_percent=0)
    repair_settings(settings)
    assert (settings['storage']['trigger_percent'], settings['storage']['target_percent']) == (85, 80)
    # The shipped low default is preferred whenever it fits below the threshold.
    settings['spectrogram'].update(min_dbfs=-20, max_dbfs=-50)
    repair_settings(settings)
    assert (settings['spectrogram']['min_dbfs'], settings['spectrogram']['max_dbfs']) == (-100, -50)


def test_ranges_clamp_and_options_fall_back_to_defaults():
    from config.settings import get_default_settings
    from core.settings_validation import repair_settings
    settings = get_default_settings()
    settings['location'].update(latitude=95.5, longitude=-200)
    settings['updates']['channel'] = 'stable'
    settings['display']['time_format'] = 'auto'
    repair_settings(settings)
    assert (settings['location']['latitude'], settings['location']['longitude']) == (90, -180)
    assert settings['updates']['channel'] == 'release'
    assert settings['display']['time_format'] is None


def test_unusable_sources_are_dropped_and_usable_ones_kept_in_order():
    from config.settings import get_default_settings
    from core.settings_validation import MAX_SOURCES, repair_settings
    settings = get_default_settings()
    settings['audio']['next_source_id'] = 100
    settings['audio']['sources'] = [
        {'id': 'source_0', 'type': 'rtsp', 'url': 'http://not-rtsp'},
        {'id': 'source_1', 'type': 'pulseaudio', 'device': 'mic'},
        {'id': 'source_2', 'type': 'pulseaudio', 'device': 'second mic'},
        {'id': 'source_1', 'type': 'rtsp', 'url': 'rtsp://dup/id'},
        *({'id': f'source_{i}', 'type': 'rtsp', 'url': f'rtsp://cam/{i}'} for i in range(3, 3 + MAX_SOURCES)),
    ]
    repairs = repair_settings(settings)
    assert repairs == ['RTSP source source_0 must have a valid rtsp:// or rtsps:// URL']
    ids = [s['id'] for s in settings['audio']['sources']]
    assert ids == ['source_1'] + [f'source_{i}' for i in range(3, 2 + MAX_SOURCES)]
    assert len(ids) == MAX_SOURCES


@pytest.mark.parametrize('legacy', [
    {'storage': {'trigger_percent': 70, 'target_percent': 70}},
    {'updates': {'channel': 'stable'}, 'display': {'time_format': 'auto'}},
    {'location': {'latitude': 40.7, 'longitude': -74.0, 'timezone': 'Not/AZone'}},
    {'schedule': {'quiet_hours': {'enabled': True, 'start': '22:00', 'end': '22:00'}}},
    {'spectrogram': {'min_dbfs': -120, 'max_dbfs': -150}},
])
def test_legacy_documents_load_valid_through_the_runtime_reader(settings_file, legacy):
    import json

    from core.settings_validation import validate_settings
    path, runtime = settings_file
    path.write_text(json.dumps(legacy))
    loaded = runtime.read_saved_settings(force_reload=True)
    assert validate_settings(loaded) is None
    assert loaded == runtime.get_runtime_settings()
    assert json.loads(path.read_text()) == legacy, 'repairs are applied in memory, the next save persists them'


def test_invalid_timezone_is_derived_from_the_coordinates():
    from config.settings import get_default_settings
    from core.settings_validation import repair_settings
    settings = get_default_settings()
    settings['location'].update(latitude=40.7, longitude=-74.0, timezone='Not/AZone')
    assert repair_settings(settings) == ['Invalid location.timezone']
    assert settings['location']['timezone'] == 'America/New_York'


def test_next_source_id_moves_past_the_sources_that_remain():
    from config.settings import get_default_settings
    from core.settings_validation import repair_settings
    settings = get_default_settings()
    settings['audio'].update(sources=[{'id': 'source_3', 'type': 'rtsp', 'url': 'rtsp://cam/3'}], next_source_id=2)
    assert repair_settings(settings) == ['next_source_id must be greater than all existing source ids']
    assert settings['audio']['next_source_id'] == 4


def test_repairs_do_not_touch_a_valid_document():
    from config.settings import get_default_settings
    from core.settings_validation import repair_settings
    settings = get_default_settings()
    before = copy.deepcopy(settings)
    assert repair_settings(settings) == []
    assert settings == before
