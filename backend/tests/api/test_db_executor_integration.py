import threading
import time
import uuid
from datetime import datetime
from unittest.mock import patch


class RecordingJob:
    def __init__(self, func, args, kwargs):
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def result(self, timeout=None):
        return self._func(*self._args, **self._kwargs)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def run(self, func, *args, **kwargs):
        self.calls.append(("run", func.__name__))
        return func(*args, **kwargs)

    def submit(self, func, *args, **kwargs):
        self.calls.append(("submit", func.__name__))
        return RecordingJob(func, args, kwargs)


class _BlockingJob:
    """Memoizes the function's return so concurrent .result() callers all
    see the same value — matches a real Future under single-flight."""

    def __init__(self, func, args, kwargs, release_event):
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._release = release_event
        self._lock = threading.Lock()
        self._computed = False
        self._result = None

    def result(self, timeout=None):
        self._release.wait(timeout=timeout)
        with self._lock:
            if not self._computed:
                self._result = self._func(*self._args, **self._kwargs)
                self._computed = True
        return self._result


class BlockingRecordingExecutor:
    """Like RecordingExecutor but submit() returns jobs whose .result()
    parks on self.release until the test sets it — lets tests stage
    concurrent in-flight requests deterministically."""

    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def run(self, func, *args, **kwargs):
        self.calls.append(("run", func.__name__))
        return func(*args, **kwargs)

    def submit(self, func, *args, **kwargs):
        self.calls.append(("submit", func.__name__))
        return _BlockingJob(func, args, kwargs, self.release)


class _FailingJob:
    def result(self, timeout=None):
        raise RuntimeError("simulated db failure")


class FailingExecutor:
    def __init__(self):
        self.calls = []

    def run(self, func, *args, **kwargs):
        self.calls.append(("run", func.__name__))
        return func(*args, **kwargs)

    def submit(self, func, *args, **kwargs):
        self.calls.append(("submit", func.__name__))
        return _FailingJob()


class _TimingOutJob:
    def result(self, timeout=None):
        # Mirrors what _GeventJob.result() must do when AsyncResult.get()
        # raises gevent.Timeout — translate to a TimeoutError so the
        # `except Exception` blocks downstream actually fire.
        raise TimeoutError("simulated db job timeout")


class TimingOutExecutor:
    def __init__(self):
        self.calls = []

    def run(self, func, *args, **kwargs):
        self.calls.append(("run", func.__name__))
        return func(*args, **kwargs)

    def submit(self, func, *args, **kwargs):
        self.calls.append(("submit", func.__name__))
        return _TimingOutJob()


def _insert_detection(db_manager, *, common_name='American Robin',
                      scientific_name='Turdus migratorius'):
    return db_manager.insert_detection({
        'timestamp': datetime.now().replace(microsecond=0).isoformat(),
        'group_timestamp': datetime.now().replace(microsecond=0).isoformat(),
        'common_name': common_name,
        'scientific_name': scientific_name,
        'confidence': 0.85,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25,
    })


def test_species_all_runs_db_call_through_executor(
    api_client, real_db_manager, monkeypatch
):
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()
    recorder = RecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', recorder)

    try:
        response = api_client.get('/api/species/all')

        assert response.status_code == 200
        assert ('submit', '_build_species_all_payload') in recorder.calls
    finally:
        api_module.invalidate_gallery_cache()


def test_dashboard_payload_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_dashboard_cache()
    recorder = RecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', recorder)

    try:
        response = api_client.get('/api/dashboard')

        assert response.status_code == 200
        assert ('submit', '_build_dashboard_payload') in recorder.calls
    finally:
        api_module.invalidate_dashboard_cache()


def test_dashboard_summary_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_dashboard_cache()
    recorder = RecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', recorder)

    try:
        response = api_client.get('/api/dashboard/summary?period=week')

        assert response.status_code == 200
        assert ('submit', '_build_summary_period_payload') in recorder.calls
    finally:
        api_module.invalidate_dashboard_cache()


# -----------------------------------------------------------------------------
# Dashboard cache invariant tests.
#
# The cache around /api/dashboard has subtle single-flight + invalidation
# logic that's hard to reason about by inspection. These tests pin the
# load-bearing properties so a refactor that breaks them fails loudly.
# -----------------------------------------------------------------------------

def _thread_get(app, path):
    """Make a request on a fresh test_client owned by the calling thread.
    Flask's test_client context manager pushes the app context on the
    thread that enters the `with` block; sharing a client across threads
    leaves the per-thread ContextVar in an inconsistent state and crashes
    teardown. A throwaway client per thread sidesteps that."""
    with app.test_client() as client:
        return client.get(path)


def test_concurrent_dashboard_misses_share_one_job(
    api_client, real_db_manager, monkeypatch
):
    """Three concurrent cache-miss requests must result in exactly one
    submit() to the executor — not three. All callers receive the same
    payload from that single job."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_dashboard_cache()

    executor = BlockingRecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', executor)

    app = api_client.application
    statuses = []
    errors = []

    def call():
        try:
            resp = _thread_get(app, '/api/dashboard')
            statuses.append(resp.status_code)
        except Exception as exc:  # pragma: no cover - surfaces in assertion below
            errors.append(exc)

    try:
        threads = [threading.Thread(target=call) for _ in range(3)]
        for t in threads:
            t.start()
        # Give all threads time to reach the blocking .result() call.
        # 200ms is generous on any reasonable CI; raise if flaky.
        time.sleep(0.2)
        executor.release.set()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert statuses == [200, 200, 200]
        submits = [
            (verb, name) for (verb, name) in executor.calls
            if verb == 'submit' and name == '_build_dashboard_payload'
        ]
        assert len(submits) == 1, (
            f"expected single-flight, got {len(submits)} submits: {executor.calls}"
        )
    finally:
        executor.release.set()  # safety: don't leave threads parked on shutdown
        api_module.invalidate_dashboard_cache()


def test_invalidation_during_compute_skips_cache_write(
    api_client, real_db_manager, monkeypatch
):
    """If invalidate_dashboard_cache() fires while a compute is in flight,
    the current caller still gets their result (we don't drop the request),
    but the result must NOT be written into the cache — otherwise a stale
    snapshot from before the invalidation would mask the new state."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_dashboard_cache()

    executor = BlockingRecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', executor)

    app = api_client.application
    responses = []

    def call():
        responses.append(_thread_get(app, '/api/dashboard'))

    try:
        worker = threading.Thread(target=call)
        worker.start()
        # Wait for the worker to reach the blocking .result() call.
        time.sleep(0.2)
        # Bump version + clear inflight while the compute is parked.
        api_module.invalidate_dashboard_cache()
        # Let the (now stale-snapshot) compute complete.
        executor.release.set()
        worker.join(timeout=5)

        assert responses[0].status_code == 200
        # Cache must be empty: the version mismatch should have caused the
        # post-compute write block to be skipped.
        assert api_module._dashboard_cache['payload'] is None
        assert api_module._dashboard_cache['expires_at'] == 0.0
    finally:
        executor.release.set()
        api_module.invalidate_dashboard_cache()


def test_failed_compute_clears_inflight(api_client, monkeypatch):
    """A failed dashboard compute must clear the inflight slot so the next
    request retries from scratch — otherwise we'd be stuck returning the
    same exception (or waiting on a never-completing job) forever."""
    import core.api as api_module

    api_module.invalidate_dashboard_cache()
    monkeypatch.setattr(api_module, 'db_executor', FailingExecutor())

    try:
        resp = api_client.get('/api/dashboard')
        # handle_api_errors converts the unhandled exception into a 500.
        assert resp.status_code == 500
        # Critically: inflight is cleared, not stuck pointing at the
        # failed job. Otherwise the next caller would re-await the same
        # already-failed job forever.
        assert api_module._dashboard_cache['inflight'] is None
    finally:
        api_module.invalidate_dashboard_cache()


def test_db_job_timeout_clears_inflight_and_returns_500(api_client, monkeypatch):
    """gevent.Timeout used to slip past `except Exception`, leaving the
    dashboard inflight slot pointing at a dead job until the next
    invalidation. _GeventJob.result() now translates it to TimeoutError;
    confirm the dashboard handler treats that like any other failure."""
    import core.api as api_module

    api_module.invalidate_dashboard_cache()
    monkeypatch.setattr(api_module, 'db_executor', TimingOutExecutor())

    try:
        resp = api_client.get('/api/dashboard')
        assert resp.status_code == 500
        assert api_module._dashboard_cache['inflight'] is None
    finally:
        api_module.invalidate_dashboard_cache()


# -----------------------------------------------------------------------------
# Mutation paths must invalidate the dashboard cache.
#
# Without these calls the 10s TTL leaves a window where dashboard counters
# disagree with the source of truth — a freshly-deleted detection still
# shows up in "today's total" for up to 10s, settings changes don't take
# effect on the dashboard until the next miss, etc.
# -----------------------------------------------------------------------------

def _prime_dashboard_cache(api_client):
    """Fetch /api/dashboard once so a payload lives in the cache, then
    assert it actually got cached. Returns the response for caller checks."""
    import core.api as api_module

    resp = api_client.get('/api/dashboard')
    assert resp.status_code == 200
    assert api_module._dashboard_cache['payload'] is not None, (
        "precondition: cache should be primed after a successful fetch"
    )
    return resp


def test_broadcast_detection_invalidates_cache(api_client, real_db_manager):
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    resp = api_client.get('/api/dashboard/summary?period=week')
    assert resp.status_code == 200
    assert api_module._summary_cache['week']['payload'] is not None

    api_module.broadcast_detection({
        'common_name': 'Northern Cardinal',
        'scientific_name': 'Cardinalis cardinalis',
        'confidence': 0.92,
        'timestamp': '2026-05-19T10:00:00',
    })

    assert api_module._dashboard_cache['payload'] is None
    assert api_module._summary_cache['week']['payload'] is None


def test_delete_detection_invalidates_cache(api_client, real_db_manager):
    import core.api as api_module

    _insert_detection(real_db_manager)
    detection_id = _insert_detection(real_db_manager, common_name='Blue Jay',
                                     scientific_name='Cyanocitta cristata')
    _prime_dashboard_cache(api_client)

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(f'/api/detections/{detection_id}')

    assert resp.status_code == 200
    assert api_module._dashboard_cache['payload'] is None


def test_batch_delete_invalidates_cache_when_anything_deleted(
    api_client, real_db_manager
):
    import core.api as api_module

    ids = [
        _insert_detection(real_db_manager, common_name=f'Robin {i}')
        for i in range(3)
    ]
    _prime_dashboard_cache(api_client)

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(
            '/api/detections/batch',
            json={'ids': ids},
        )

    assert resp.status_code == 200
    assert resp.get_json()['deleted'] == 3
    assert api_module._dashboard_cache['payload'] is None


def test_batch_delete_with_no_successes_does_not_invalidate(
    api_client, real_db_manager
):
    """If every ID in the batch is missing, the dashboard data hasn't
    actually changed — preserve the cache so we don't pay an unnecessary
    4.5s recompute on the next poll."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = api_module._dashboard_cache['payload']

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(
            '/api/detections/batch',
            json={'ids': [99991, 99992, 99993]},
        )

    assert resp.status_code == 200
    assert resp.get_json()['deleted'] == 0
    assert api_module._dashboard_cache['payload'] is cached_payload


def test_update_settings_invalidates_cache_on_display_change(
    api_client, real_db_manager
):
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)

    # Unique value so the PUT genuinely differs from whatever
    # user_settings.json holds — without this, a previous run that
    # already wrote the same station_name would produce empty
    # changed_paths and the gated invalidation wouldn't fire.
    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'display': {'station_name': f'TestStation-{uuid.uuid4().hex[:8]}'}},
        )

    assert resp.status_code == 200
    assert api_module._dashboard_cache['payload'] is None


def test_update_settings_preserves_cache_on_non_display_change(
    api_client, real_db_manager
):
    """The cached dashboard payload depends only on display.* and
    location.* settings — display.* feeds _localize_*, location.* feeds
    local_now() which sets today/week/month boundaries. A change to any
    other section shouldn't drop the cache — that'd cost a 4.5s recompute
    on the next poll for no observable benefit."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = api_module._dashboard_cache['payload']

    # Unique rate_limit value (non-display, non-location) so changed_paths is non-empty.
    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'notifications': {
                'rate_limit_seconds': int(uuid.uuid4().int % 1000) + 100,
            }},
        )

    assert resp.status_code == 200
    assert api_module._dashboard_cache['payload'] is cached_payload


def test_update_settings_invalidates_cache_on_location_change(
    api_client, real_db_manager
):
    """A location.* change (lat/lon/timezone) shifts the day boundaries
    that _build_dashboard_payload() derives from local_now(), so the
    cached payload becomes stale. Without invalidation, the dashboard
    would keep returning data computed in the old timezone for up to the
    cache TTL after the user moves the station or fixes the timezone."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)

    # Pick whichever timezone the current settings aren't using so the
    # PUT genuinely changes location.timezone — without that, changed_paths
    # is empty and the gated invalidation wouldn't fire.
    current_tz = (
        api_module.load_user_settings()
        .get('location', {})
        .get('timezone')
    )
    new_tz = 'America/Los_Angeles' if current_tz != 'America/Los_Angeles' else 'America/New_York'

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'location': {'timezone': new_tz}},
        )

    assert resp.status_code == 200
    assert api_module._dashboard_cache['payload'] is None


def test_migration_import_invalidates_cache_when_records_imported(
    api_client, real_db_manager, tmp_path
):
    """A successful migration imports historical detections that change
    every dashboard counter (totals, unique species, per-period picks).
    Without invalidation, the dashboard reports pre-import counts for up
    to TTL after the import completes."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)

    temp_path = str(tmp_path / 'migration.db')
    open(temp_path, 'w').close()  # finally-block cleanup removes it

    with patch('core.api.BirdNETPiMigrator') as MockMigrator:
        MockMigrator.return_value.migrate.return_value = {
            'imported': 5, 'skipped': 0, 'errors': 0
        }
        api_module._run_migration_background(
            temp_path, total_records=5, skip_duplicates=True
        )

    assert api_module._dashboard_cache['payload'] is None


def test_migration_import_preserves_cache_when_nothing_imported(
    api_client, real_db_manager, tmp_path
):
    """If every source row was a duplicate (skipped) and nothing was
    actually imported, dashboard data hasn't changed — preserve the cache
    so we don't pay an unnecessary recompute on the next poll. Mirrors
    the batch-delete-with-no-successes semantic."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = api_module._dashboard_cache['payload']

    temp_path = str(tmp_path / 'migration.db')
    open(temp_path, 'w').close()

    with patch('core.api.BirdNETPiMigrator') as MockMigrator:
        MockMigrator.return_value.migrate.return_value = {
            'imported': 0, 'skipped': 3, 'errors': 0
        }
        api_module._run_migration_background(
            temp_path, total_records=3, skip_duplicates=True
        )

    assert api_module._dashboard_cache['payload'] is cached_payload


# -----------------------------------------------------------------------------
# Bird Gallery cache: /api/sightings + /api/species/all, separate from the
# dashboard cache and — critically — not cleared by broadcast_detection().
# -----------------------------------------------------------------------------

def test_sightings_payload_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()
    recorder = RecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', recorder)

    try:
        response = api_client.get('/api/sightings?type=frequent')

        assert response.status_code == 200
        assert ('submit', '_build_sightings_payload') in recorder.calls
    finally:
        api_module.invalidate_gallery_cache()


def test_gallery_cache_serves_repeat_request(
    api_client, real_db_manager, monkeypatch
):
    """A second request within the TTL is served from the gallery cache —
    no second executor submit."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()

    # First request populates the cache through the real executor.
    first = api_client.get('/api/species/all')
    assert first.status_code == 200
    assert api_module._gallery_cache['species:all']['payload'] is not None

    # Second request must not touch the executor at all.
    recorder = RecordingExecutor()
    monkeypatch.setattr(api_module, 'db_executor', recorder)
    try:
        second = api_client.get('/api/species/all')
        assert second.status_code == 200
        assert second.get_json() == first.get_json()
        assert recorder.calls == []
    finally:
        api_module.invalidate_gallery_cache()


def test_broadcast_detection_preserves_gallery_cache(api_client, real_db_manager):
    """broadcast_detection() fires on every new detection and clears the
    dashboard cache — but must leave the gallery cache intact, or the gallery
    (opened on demand, not polled) would never get a warm cache."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()
    api_module.invalidate_dashboard_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert api_client.get('/api/dashboard').status_code == 200
    gallery_payload = api_module._gallery_cache['species:all']['payload']
    assert gallery_payload is not None
    assert api_module._dashboard_cache['payload'] is not None

    api_module.broadcast_detection({
        'common_name': 'Northern Cardinal',
        'scientific_name': 'Cardinalis cardinalis',
        'confidence': 0.92,
        'timestamp': '2026-05-19T10:00:00',
    })

    # Dashboard cache cleared; gallery cache untouched.
    assert api_module._dashboard_cache['payload'] is None
    assert api_module._gallery_cache['species:all']['payload'] is gallery_payload


def test_delete_detection_invalidates_gallery_cache(api_client, real_db_manager):
    import core.api as api_module

    detection_id = _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert api_module._gallery_cache['species:all']['payload'] is not None

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(f'/api/detections/{detection_id}')

    assert resp.status_code == 200
    assert api_module._gallery_cache['species:all']['payload'] is None


def test_update_settings_invalidates_gallery_cache_on_display_change(
    api_client, real_db_manager
):
    """A display.* change alters the localized names baked into the cached
    gallery payload, so the cache must be dropped."""
    import core.api as api_module

    _insert_detection(real_db_manager)
    api_module.invalidate_gallery_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert api_module._gallery_cache['species:all']['payload'] is not None

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'display': {'station_name': f'TestStation-{uuid.uuid4().hex[:8]}'}},
        )

    assert resp.status_code == 200
    assert api_module._gallery_cache['species:all']['payload'] is None
