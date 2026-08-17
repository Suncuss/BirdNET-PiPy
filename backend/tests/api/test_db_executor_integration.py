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
        # Mirrors _LaneJob.result() hitting its deadline — it raises
        # TimeoutError (never gevent.Timeout) so the `except Exception`
        # blocks downstream actually fire.
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
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()
    recorder = RecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', recorder)

    try:
        response = api_client.get('/api/species/all')

        assert response.status_code == 200
        assert ('submit', '_build_species_all_payload') in recorder.calls
    finally:
        obs_module.invalidate_gallery_cache()


def test_dashboard_payload_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()
    recorder = RecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', recorder)

    try:
        response = api_client.get('/api/dashboard')

        assert response.status_code == 200
        assert ('submit', '_build_dashboard_payload') in recorder.calls
    finally:
        obs_module.invalidate_dashboard_cache()


def test_dashboard_summary_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()
    recorder = RecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', recorder)

    try:
        response = api_client.get('/api/dashboard/summary?period=week')

        assert response.status_code == 200
        # builder renamed: the versioned wrapper carries the rollup
        # revision captured inside the job (implementation review fix 4)
        assert ('submit', '_build_versioned_summary_payload') in recorder.calls
    finally:
        obs_module.invalidate_dashboard_cache()


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
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()

    executor = BlockingRecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', executor)

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
        obs_module.invalidate_dashboard_cache()


def _dashboard_get_with_midflight(api_client, monkeypatch, midflight_fn):
    """GET /api/dashboard on a worker thread, run `midflight_fn` while the
    compute is parked mid-flight, then release the compute and return the
    response. Shared harness for the invalidate-vs-expire mid-flight tests."""
    import core.api_infra as api_infra

    executor = BlockingRecordingExecutor()
    monkeypatch.setattr(api_infra, 'db_executor', executor)

    app = api_client.application
    responses = []

    def call():
        responses.append(_thread_get(app, '/api/dashboard'))

    try:
        worker = threading.Thread(target=call)
        worker.start()
        # Wait for the worker to reach the blocking .result() call.
        # 200ms is generous on any reasonable CI; raise if flaky.
        time.sleep(0.2)
        midflight_fn()
        # Let the parked compute complete.
        executor.release.set()
        worker.join(timeout=5)
    finally:
        executor.release.set()  # safety: don't leave threads parked on shutdown

    return responses[0]


def test_invalidation_during_compute_skips_cache_write(
    api_client, real_db_manager, monkeypatch
):
    """If invalidate_dashboard_cache() fires while a compute is in flight,
    the current caller still gets their result (we don't drop the request),
    but the result must NOT be written into the cache — otherwise a stale
    snapshot from before the invalidation would mask the new state."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()

    try:
        response = _dashboard_get_with_midflight(
            api_client, monkeypatch, obs_module.invalidate_dashboard_cache,
        )

        assert response.status_code == 200
        # Cache must be empty: the invalidation cleared 'inflight', so the
        # post-compute write block was skipped.
        assert obs_module._dashboard_cache['payload'] is None
        assert obs_module._dashboard_cache['expires_at'] == 0.0
    finally:
        obs_module.invalidate_dashboard_cache()


def test_soft_expiry_during_compute_serves_result_but_stays_expired(
    api_client, real_db_manager, monkeypatch
):
    """expire_dashboard_cache() — the per-detection freshness path — must
    NOT discard an in-flight rebuild: the job keeps its 'inflight' slot and
    its result is served to the callers already waiting (the old hard
    invalidation threw away a multi-second compute no client ever received).
    But the entry must stay expired: the job's DB snapshot may predate the
    detection that fired the expiry, so granting it a fresh TTL would serve
    a pre-detection payload for a full TTL. The next poll rebuilds instead."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()

    try:
        response = _dashboard_get_with_midflight(
            api_client, monkeypatch, obs_module.expire_dashboard_cache,
        )

        assert response.status_code == 200
        # The completed rebuild landed in the cache but earned no TTL.
        assert obs_module._dashboard_cache['payload'] is not None
        assert obs_module._dashboard_cache['expires_at'] == 0.0
        assert obs_module._dashboard_cache['inflight'] is None

        # Behavioral check: the next poll recomputes rather than being
        # served the possibly pre-detection snapshot.
        recorder = RecordingExecutor()
        import core.api_infra as api_infra
        monkeypatch.setattr(api_infra, 'db_executor', recorder)
        assert api_client.get('/api/dashboard').status_code == 200
        assert ('submit', '_build_dashboard_payload') in recorder.calls
    finally:
        obs_module.invalidate_dashboard_cache()


def test_soft_expiry_before_compute_does_not_stick(api_client, real_db_manager):
    """A soft expiry with nothing in flight must not linger: the next rebuild
    is submitted after the expiry, so its snapshot already includes the
    detection and earns a normal TTL. If the dirty mark stuck, every rebuild
    after a quiet-period detection would come out pre-expired — degrading the
    dashboard to a rebuild on every poll."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_dashboard_cache()

    try:
        obs_module.expire_dashboard_cache()  # detection with no rebuild running
        _prime_dashboard_cache(api_client)

        assert obs_module._dashboard_cache['expires_at'] > time.time()
    finally:
        obs_module.invalidate_dashboard_cache()


def test_failed_compute_clears_inflight(api_client, monkeypatch):
    """A failed dashboard compute must clear the inflight slot so the next
    request retries from scratch — otherwise we'd be stuck returning the
    same exception (or waiting on a never-completing job) forever."""
    from core.routes import observations as obs_module

    obs_module.invalidate_dashboard_cache()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', FailingExecutor())

    try:
        resp = api_client.get('/api/dashboard')
        # handle_api_errors converts the unhandled exception into a 500.
        assert resp.status_code == 500
        # Critically: inflight is cleared, not stuck pointing at the
        # failed job. Otherwise the next caller would re-await the same
        # already-failed job forever.
        assert obs_module._dashboard_cache['inflight'] is None
    finally:
        obs_module.invalidate_dashboard_cache()


def test_db_job_timeout_clears_inflight_and_returns_500(api_client, monkeypatch):
    """gevent.Timeout used to slip past `except Exception`, leaving the
    dashboard inflight slot pointing at a dead job until the next
    invalidation. _LaneJob.result() raises TimeoutError instead;
    confirm the dashboard handler treats that like any other failure."""
    from core.routes import observations as obs_module

    obs_module.invalidate_dashboard_cache()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', TimingOutExecutor())

    try:
        resp = api_client.get('/api/dashboard')
        assert resp.status_code == 500
        assert obs_module._dashboard_cache['inflight'] is None
    finally:
        obs_module.invalidate_dashboard_cache()


# -----------------------------------------------------------------------------
# Mutation paths must invalidate the dashboard cache.
#
# Without these calls the 10s TTL leaves a window where dashboard counters
# disagree with the source of truth — a freshly-deleted detection still
# shows up in "today's total" for up to 10s, settings changes don't take
# effect on the dashboard until the next miss, etc.
#
# New detections are deliberately NOT one of these paths: they soft-expire
# only the dashboard/today entries (freshness, not correctness), leaving
# week/month/allTime warm — see the broadcast_detection tests.
# -----------------------------------------------------------------------------

def _prime_dashboard_cache(api_client):
    """Fetch /api/dashboard once so a payload lives in the cache, then
    assert it actually got cached. Returns the response for caller checks."""
    from core.routes import observations as obs_module

    resp = api_client.get('/api/dashboard')
    assert resp.status_code == 200
    assert obs_module._dashboard_cache['payload'] is not None, (
        "precondition: cache should be primed after a successful fetch"
    )
    return resp


def test_broadcast_detection_expires_dashboard_and_today_only(
    api_client, real_db_manager, monkeypatch
):
    """A new detection is a freshness event, not a correctness event: the
    dashboard payload and 'today' summary get expired (recomputed on the next
    poll) but keep their payloads, while week/month/allTime — which one
    detection only nudges by +1 — keep payload AND TTL. Hard-invalidating
    everything per detection kept every summary permanently cold on active
    stations (detections arrive faster than the 10s TTL)."""
    import core.api as api_module
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    dashboard_payload = obs_module._dashboard_cache['payload']
    for period in ('today', 'week'):
        resp = api_client.get(f'/api/dashboard/summary?period={period}')
        assert resp.status_code == 200
    week_expiry = obs_module._summary_cache['week']['expires_at']

    try:
        api_module.broadcast_detection({
            'common_name': 'Northern Cardinal',
            'scientific_name': 'Cardinalis cardinalis',
            'confidence': 0.92,
            'timestamp': '2026-05-19T10:00:00',
        })

        # Dashboard + today: expired but not discarded.
        assert obs_module._dashboard_cache['payload'] is dashboard_payload
        assert obs_module._dashboard_cache['expires_at'] == 0.0
        assert obs_module._summary_cache['today']['payload'] is not None
        assert obs_module._summary_cache['today']['expires_at'] == 0.0
        # week: untouched — payload and TTL survive.
        assert obs_module._summary_cache['week']['payload'] is not None
        assert obs_module._summary_cache['week']['expires_at'] == week_expiry

        # Behavioral check: the next week fetch is a warm hit (no executor
        # call), the next dashboard fetch recomputes.
        recorder = RecordingExecutor()
        import core.api_infra as api_infra
        monkeypatch.setattr(api_infra, 'db_executor', recorder)
        assert api_client.get('/api/dashboard/summary?period=week').status_code == 200
        # Warm hit: no summary recompute. The single get_rollup_revision
        # read is the designed cross-process cache validation (a rollup
        # revision bump in EITHER container must invalidate cached
        # payloads regardless of remaining TTL).
        assert [c for c in recorder.calls
                if c[1] != 'get_rollup_revision'] == []
        assert api_client.get('/api/dashboard').status_code == 200
        assert ('submit', '_build_dashboard_payload') in recorder.calls
    finally:
        obs_module.invalidate_dashboard_cache()


def test_delete_detection_invalidates_cache(api_client, real_db_manager):
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    detection_id = _insert_detection(real_db_manager, common_name='Blue Jay',
                                     scientific_name='Cyanocitta cristata')
    _prime_dashboard_cache(api_client)

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(f'/api/detections/{detection_id}')

    assert resp.status_code == 200
    assert obs_module._dashboard_cache['payload'] is None


def test_batch_delete_invalidates_cache_when_anything_deleted(
    api_client, real_db_manager
):
    from core.routes import observations as obs_module

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
    assert obs_module._dashboard_cache['payload'] is None


def test_batch_delete_with_no_successes_does_not_invalidate(
    api_client, real_db_manager
):
    """If every ID in the batch is missing, the dashboard data hasn't
    actually changed — preserve the cache so we don't pay an unnecessary
    4.5s recompute on the next poll."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = obs_module._dashboard_cache['payload']

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(
            '/api/detections/batch',
            json={'ids': [99991, 99992, 99993]},
        )

    assert resp.status_code == 200
    assert resp.get_json()['deleted'] == 0
    assert obs_module._dashboard_cache['payload'] is cached_payload


def test_update_settings_invalidates_cache_on_display_change(
    api_client, real_db_manager
):
    from core.routes import observations as obs_module

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
    assert obs_module._dashboard_cache['payload'] is None


def test_update_settings_preserves_cache_on_non_display_change(
    api_client, real_db_manager
):
    """The cached dashboard payload depends only on display.* and
    location.* settings — display.* feeds _localize_*, location.* feeds
    local_now() which sets today/week/month boundaries. A change to any
    other section shouldn't drop the cache — that'd cost a 4.5s recompute
    on the next poll for no observable benefit."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = obs_module._dashboard_cache['payload']

    # Unique rate_limit value (non-display, non-location) so changed_paths is non-empty.
    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'notifications': {
                'rate_limit_seconds': int(uuid.uuid4().int % 1000) + 100,
            }},
        )

    assert resp.status_code == 200
    assert obs_module._dashboard_cache['payload'] is cached_payload


def test_update_settings_invalidates_cache_on_location_change(
    api_client, real_db_manager
):
    """A location.* change (lat/lon/timezone) shifts the day boundaries
    that _build_dashboard_payload() derives from local_now(), so the
    cached payload becomes stale. Without invalidation, the dashboard
    would keep returning data computed in the old timezone for up to the
    cache TTL after the user moves the station or fixes the timezone."""
    import core.api as api_module
    from core.routes import observations as obs_module

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
    assert obs_module._dashboard_cache['payload'] is None


def test_migration_import_invalidates_cache_when_records_imported(
    api_client, real_db_manager, tmp_path
):
    """A successful migration imports historical detections that change
    every dashboard counter (totals, unique species, per-period picks).
    Without invalidation, the dashboard reports pre-import counts for up
    to TTL after the import completes."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)

    temp_path = str(tmp_path / 'migration.db')
    open(temp_path, 'w').close()  # finally-block cleanup removes it

    from core.routes import migration as migration_routes
    with patch('core.routes.migration.BirdNETPiMigrator') as MockMigrator:
        MockMigrator.return_value.migrate.return_value = {
            'imported': 5, 'skipped': 0, 'errors': 0
        }
        migration_routes._run_migration_background(
            temp_path, total_records=5, skip_duplicates=True
        )

    assert obs_module._dashboard_cache['payload'] is None


def test_migration_import_preserves_cache_when_nothing_imported(
    api_client, real_db_manager, tmp_path
):
    """If every source row was a duplicate (skipped) and nothing was
    actually imported, dashboard data hasn't changed — preserve the cache
    so we don't pay an unnecessary recompute on the next poll. Mirrors
    the batch-delete-with-no-successes semantic."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    _prime_dashboard_cache(api_client)
    cached_payload = obs_module._dashboard_cache['payload']

    temp_path = str(tmp_path / 'migration.db')
    open(temp_path, 'w').close()

    from core.routes import migration as migration_routes
    with patch('core.routes.migration.BirdNETPiMigrator') as MockMigrator:
        MockMigrator.return_value.migrate.return_value = {
            'imported': 0, 'skipped': 3, 'errors': 0
        }
        migration_routes._run_migration_background(
            temp_path, total_records=3, skip_duplicates=True
        )

    assert obs_module._dashboard_cache['payload'] is cached_payload


# -----------------------------------------------------------------------------
# Bird Gallery cache: /api/sightings + /api/species/all, separate from the
# dashboard cache and — critically — not cleared by broadcast_detection().
# -----------------------------------------------------------------------------

def test_sightings_payload_is_submitted_to_executor(
    api_client, real_db_manager, monkeypatch
):
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()
    recorder = RecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', recorder)

    try:
        response = api_client.get('/api/sightings?type=frequent')

        assert response.status_code == 200
        assert ('submit', '_build_sightings_payload') in recorder.calls
    finally:
        obs_module.invalidate_gallery_cache()


def test_gallery_cache_serves_repeat_request(
    api_client, real_db_manager, monkeypatch
):
    """A second request within the TTL is served from the gallery cache —
    no second executor submit."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()

    # First request populates the cache through the real executor.
    first = api_client.get('/api/species/all')
    assert first.status_code == 200
    assert obs_module._gallery_cache['species:all']['payload'] is not None

    # Second request must not touch the executor at all.
    recorder = RecordingExecutor()
    import core.api_infra as api_infra
    monkeypatch.setattr(api_infra, 'db_executor', recorder)
    try:
        second = api_client.get('/api/species/all')
        assert second.status_code == 200
        assert second.get_json() == first.get_json()
        assert recorder.calls == []
    finally:
        obs_module.invalidate_gallery_cache()


def test_broadcast_detection_preserves_gallery_cache(api_client, real_db_manager):
    """broadcast_detection() fires on every new detection and expires the
    dashboard cache — but must leave the gallery cache intact, or the gallery
    (opened on demand, not polled) would never get a warm cache."""
    import core.api as api_module
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()
    obs_module.invalidate_dashboard_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert api_client.get('/api/dashboard').status_code == 200
    gallery_payload = obs_module._gallery_cache['species:all']['payload']
    assert gallery_payload is not None
    assert obs_module._dashboard_cache['payload'] is not None
    gallery_expiry = obs_module._gallery_cache['species:all']['expires_at']

    api_module.broadcast_detection({
        'common_name': 'Northern Cardinal',
        'scientific_name': 'Cardinalis cardinalis',
        'confidence': 0.92,
        'timestamp': '2026-05-19T10:00:00',
    })

    # Dashboard cache expired; gallery cache untouched.
    assert obs_module._dashboard_cache['expires_at'] == 0.0
    assert obs_module._gallery_cache['species:all']['payload'] is gallery_payload
    assert obs_module._gallery_cache['species:all']['expires_at'] == gallery_expiry


def test_delete_detection_invalidates_gallery_cache(api_client, real_db_manager):
    from core.routes import observations as obs_module

    detection_id = _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert obs_module._gallery_cache['species:all']['payload'] is not None

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.delete(f'/api/detections/{detection_id}')

    assert resp.status_code == 200
    assert obs_module._gallery_cache['species:all']['payload'] is None


def test_update_settings_invalidates_gallery_cache_on_display_change(
    api_client, real_db_manager
):
    """A display.* change alters the localized names baked into the cached
    gallery payload, so the cache must be dropped."""
    from core.routes import observations as obs_module

    _insert_detection(real_db_manager)
    obs_module.invalidate_gallery_cache()

    assert api_client.get('/api/species/all').status_code == 200
    assert obs_module._gallery_cache['species:all']['payload'] is not None

    with patch('core.auth.is_authenticated', return_value=True):
        resp = api_client.put(
            '/api/settings',
            json={'display': {'station_name': f'TestStation-{uuid.uuid4().hex[:8]}'}},
        )

    assert resp.status_code == 200
    assert obs_module._gallery_cache['species:all']['payload'] is None
