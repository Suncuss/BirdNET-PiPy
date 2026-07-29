"""Tests for detection_presenter's derived ``extra.weather.is_day`` fill.

The flag is computed at payload-shaping time from the detection timestamp and
the station coordinates (core.solar), never stored — so historical rows gain
it retroactively with no migration, and rows that already carry a flag (a
future write-time stamp) are left alone. The station context is resolved once
per request (``_solar_context``) and threaded into the per-row fill.
"""
from contextlib import contextmanager
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

# At the default station coordinates (42.47, -76.45) in late July, sunset is
# ~20:30 EDT — 21:42 is well after dark, noon is well before.
NIGHT_TS = '2026-07-25T21:42:00'
NOON_TS = '2026-07-25T12:00:00'


def _weather(**overrides):
    base = {'temp': 20.0, 'humidity': 50, 'precip': 0.0, 'wind': 5.0,
            'code': 0, 'cloud_cover': 10, 'pressure': 1015.0}
    base.update(overrides)
    return base


@contextmanager
def station(lat=42.47, lon=-76.45, tz='America/New_York', configured=True):
    """Patch the station location + timezone the presenter reads."""
    from core import detection_presenter as dp
    location = {'latitude': lat, 'longitude': lon,
                'configured': configured, 'timezone': tz}

    def fake_setting(path, default=None):
        return location if path == 'location' else default

    with patch.object(dp, 'get_runtime_setting', side_effect=fake_setting), \
         patch.object(dp, 'get_timezone', return_value=ZoneInfo(tz)):
        yield dp


class TestSolarContext:
    def test_configured_station_yields_coords_and_tz(self):
        with station() as dp:
            assert dp._solar_context() == (42.47, -76.45, ZoneInfo('America/New_York'))

    def test_unconfigured_location_yields_none(self):
        with station(configured=False) as dp:
            assert dp._solar_context() is None

    def test_missing_coordinate_yields_none(self):
        with station(lat=None) as dp:
            assert dp._solar_context() is None


class TestAttachIsDay:
    def _attach(self, dp, det):
        return dp._attach_is_day(det, dp._solar_context())

    def test_night_detection_gets_is_day_0(self):
        with station() as dp:
            det = {'timestamp': NIGHT_TS, 'extra': {'weather': _weather()}}
            self._attach(dp, det)
            assert det['extra']['weather']['is_day'] == 0

    def test_noon_detection_gets_is_day_1(self):
        with station() as dp:
            det = {'timestamp': NOON_TS, 'extra': {'weather': _weather()}}
            self._attach(dp, det)
            assert det['extra']['weather']['is_day'] == 1

    def test_existing_flag_is_never_overwritten(self):
        # A write-time stamp (or any pre-existing value) wins over derivation.
        with station() as dp:
            det = {'timestamp': NIGHT_TS, 'extra': {'weather': _weather(is_day=1)}}
            self._attach(dp, det)
            assert det['extra']['weather']['is_day'] == 1

    def test_case_insensitive_weather_key(self):
        with station() as dp:
            det = {'timestamp': NIGHT_TS, 'extra': {'Weather': _weather()}}
            self._attach(dp, det)
            assert det['extra']['Weather']['is_day'] == 0

    def test_no_solar_context_no_fill(self):
        from core import detection_presenter as dp
        det = {'timestamp': NIGHT_TS, 'extra': {'weather': _weather()}}
        dp._attach_is_day(det, None)
        assert 'is_day' not in det['extra']['weather']

    @pytest.mark.parametrize('det', [
        {'timestamp': 'not-a-date', 'extra': {'weather': _weather()}},
        {'extra': {'weather': _weather()}},  # missing timestamp
    ])
    def test_unusable_timestamp_no_fill(self, det):
        with station() as dp:
            self._attach(dp, det)
            assert 'is_day' not in det['extra']['weather']

    @pytest.mark.parametrize('det', [
        {'timestamp': NIGHT_TS, 'extra': {'source_label': 'yard'}},
        {'timestamp': NIGHT_TS},  # no extra at all
        # extra is always dict-or-absent at the presenter; anything else
        # (e.g. a stray raw JSON string) is left untouched, not normalized.
        {'timestamp': NIGHT_TS, 'extra': '{"weather": {}}'},
    ])
    def test_rows_without_weather_dict_are_untouched(self, det):
        with station() as dp:
            before = dict(det)
            self._attach(dp, det)
            assert det == before


class TestLocalizeDetectionWiring:
    def test_localize_fills_flag_without_mutating_source_row(self):
        # add_display_common_name returns a SHALLOW copy, so the fill must
        # rebuild extra/weather rather than write into the nested dicts —
        # cached payload builders share their source rows across requests.
        with station() as dp:
            row = {'common_name': 'Killdeer',
                   'scientific_name': 'Charadrius vociferus',
                   'timestamp': NIGHT_TS, 'extra': {'weather': _weather()}}
            out = dp._localize_detection(row, is_public=False)
            assert out['extra']['weather']['is_day'] == 0
            assert 'is_day' not in row['extra']['weather']

    def test_public_variant_keeps_the_flag(self):
        # weather stays in anonymous payloads (_PUBLIC_EXTRA_KEYS), and the
        # flag rides along inside it.
        with station() as dp:
            row = {'common_name': 'Killdeer',
                   'scientific_name': 'Charadrius vociferus',
                   'timestamp': NIGHT_TS, 'extra': {'weather': _weather()}}
            out = dp._localize_detection(row, is_public=True)
            assert out['extra']['weather']['is_day'] == 0

    def test_list_path_resolves_context_once(self):
        # The list serializer hoists _solar_context() per request, like cutoff.
        with station() as dp:
            rows = [{'common_name': 'Killdeer',
                     'scientific_name': 'Charadrius vociferus',
                     'timestamp': NIGHT_TS, 'extra': {'weather': _weather()}}
                    for _ in range(3)]
            with patch.object(dp, '_solar_context',
                              wraps=dp._solar_context) as ctx_spy:
                out = dp._localize_detection_list(rows, public_only=True)
            assert ctx_spy.call_count == 1
            assert all(d['extra']['weather']['is_day'] == 0 for d in out)
