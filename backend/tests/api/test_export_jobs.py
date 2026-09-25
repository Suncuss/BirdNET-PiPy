"""Tests for prepared exports: /api/detections/export/count and /export/jobs."""

import csv
import io
import os
import threading
import time
import zipfile
from datetime import date, datetime
from unittest.mock import patch

import pytest

from tests.api.conftest import auth_enabled_app, insert_detection


@pytest.fixture(autouse=True)
def export_env(tmp_path):
    """Exports land in a tempdir with ample disk headroom, and every test
    starts and ends with no current job (the job slot is module state)."""
    from core import export_jobs
    export_dir = tmp_path / 'exports'
    with patch('core.export_jobs.EXPORT_DIR', str(export_dir)), \
         patch('core.export_jobs.cleanup_headroom_bytes', return_value=10**12):
        export_jobs._job = None
        yield export_dir
        if export_jobs._job is not None:
            export_jobs.discard_job(export_jobs._job.id)


def _wait_finished(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f'/api/detections/export/jobs/{job_id}').get_json()['job']
        if job['state'] != 'preparing':
            return job
        time.sleep(0.02)
    raise AssertionError('export job did not finish')


def _start(client, **body):
    return client.post('/api/detections/export/jobs', json=body or {'range': 'all'})


def _prepare(client, **body):
    """Start an export and wait for it to finish; returns the final job."""
    return _wait_finished(client, _start(client, **body).get_json()['job']['id'])


def _download(client, job_id):
    return client.get(f'/api/detections/export/jobs/{job_id}/file')


def _zip_rows(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        (name,) = archive.namelist()
        return name, list(csv.reader(io.StringIO(archive.read(name).decode('utf-8'))))


@pytest.fixture
def gated_batches():
    """Replace the batch walk with one that yields a batch, then blocks until
    released — holds a job in 'preparing' for busy/cancel tests."""
    release = threading.Event()
    row = (1, '2024-01-15T10:00:00')

    def batches(*args, **kwargs):
        yield [row]
        release.wait(10)
        yield [row]

    with patch('core.export_jobs.iter_export_batches', batches):
        yield release
    release.set()


class TestPreparedExport:

    def test_zip_matches_streaming_export(self, api_client, real_db_manager):
        """The prepared file carries exactly the rows the streaming CSV does."""
        for minute in range(5):
            insert_detection(real_db_manager, timestamp=f'2024-01-15T10:{minute:02d}:00')

        job = _prepare(api_client)
        assert job['state'] == 'ready'
        assert job['rows_done'] == job['rows_total'] == 5
        assert job['bytes'] > 0 and job['expires_at']

        download = _download(api_client, job['id'])
        assert download.status_code == 200
        assert download.mimetype == 'application/zip'
        assert job['filename'] in download.headers['Content-Disposition']
        name, rows = _zip_rows(download.data)
        assert name == job['filename'].replace('.zip', '.csv')

        streamed = list(csv.reader(io.StringIO(
            api_client.get('/api/detections/export').data.decode('utf-8'))))
        assert rows == streamed
        assert len(rows) == 6  # header + 5

    def test_custom_range_exports_only_that_range(self, api_client, real_db_manager):
        for day in range(10, 20):
            insert_detection(real_db_manager, timestamp=f'2024-01-{day}T10:00:00')

        job = _prepare(api_client, range='custom',
                       start_date='2024-01-12', end_date='2024-01-14')
        assert job['rows_total'] == job['rows_done'] == 3
        assert job['filename'] == 'birdnet_detections_2024-01-12_to_2024-01-14.zip'

        _, rows = _zip_rows(_download(api_client, job['id']).data)
        assert sorted(r[1][:10] for r in rows[1:]) == [
            '2024-01-12', '2024-01-13', '2024-01-14']

    def test_empty_export_is_header_only(self, api_client):
        job = _prepare(api_client)
        assert job['state'] == 'ready' and job['rows_total'] == 0
        _, rows = _zip_rows(_download(api_client, job['id']).data)
        assert len(rows) == 1

    def test_current_job_resumes(self, api_client, real_db_manager):
        assert api_client.get('/api/detections/export/jobs/current').get_json()['job'] is None
        job_id = _prepare(api_client)['id']
        current = api_client.get('/api/detections/export/jobs/current').get_json()['job']
        assert current['id'] == job_id and current['state'] == 'ready'

    def test_start_replaces_finished_job(self, api_client, real_db_manager, export_env):
        first = _prepare(api_client)
        second = _prepare(api_client)
        assert first['id'] != second['id']
        assert api_client.get(f"/api/detections/export/jobs/{first['id']}").status_code == 404
        assert _download(api_client, first['id']).status_code == 404
        assert os.listdir(export_env) == [f"{second['id']}.zip"]

    def test_refused_start_keeps_the_ready_export(self, api_client, real_db_manager, export_env):
        """A start that fails its space check must not cost the user the
        export they already have."""
        insert_detection(real_db_manager)
        ready = _prepare(api_client)
        with patch('core.export_jobs.cleanup_headroom_bytes', return_value=0):
            assert _start(api_client).status_code == 507
        assert api_client.get('/api/detections/export/jobs/current').get_json()['job']['id'] == ready['id']
        assert _download(api_client, ready['id']).status_code == 200

    def test_rows_total_matches_the_file(self, api_client, real_db_manager):
        """Rows landing between the count and the first batch are exported,
        so progress and the ready card follow the rows actually written."""
        for minute in range(3):
            insert_detection(real_db_manager, timestamp=f'2024-01-15T10:{minute:02d}:00')
        with patch.object(real_db_manager, 'count_detections_for_export', return_value=1):
            job = _prepare(api_client)
        assert job['rows_total'] == job['rows_done'] == 3
        _, rows = _zip_rows(_download(api_client, job['id']).data)
        assert len(rows) == 4

    def test_second_start_while_preparing_conflicts(self, api_client, gated_batches):
        running = _start(api_client).get_json()['job']
        response = _start(api_client)
        assert response.status_code == 409
        assert response.get_json()['job']['id'] == running['id']

    def test_cancel_stops_job_and_removes_partial_file(
            self, api_client, gated_batches, export_env):
        from core import export_jobs
        job_id = _start(api_client).get_json()['job']['id']
        assert api_client.delete(f'/api/detections/export/jobs/{job_id}').status_code == 200
        assert api_client.get('/api/detections/export/jobs/current').get_json()['job'] is None

        gated_batches.set()
        deadline = time.time() + 5
        while os.listdir(export_env) and time.time() < deadline:
            time.sleep(0.02)
        assert os.listdir(export_env) == []
        assert export_jobs._job is None
        # The slot is free again.
        assert _start(api_client).status_code == 202

    def test_discard_ready_job_deletes_file(self, api_client, export_env):
        job = _prepare(api_client)
        assert api_client.delete(f"/api/detections/export/jobs/{job['id']}").status_code == 200
        assert os.listdir(export_env) == []
        assert api_client.delete(f"/api/detections/export/jobs/{job['id']}").status_code == 404

    def test_finished_job_expires_after_ttl(self, api_client, export_env):
        job = _prepare(api_client)
        with patch('core.export_jobs.EXPORT_TTL_SECONDS', 0):
            assert api_client.get('/api/detections/export/jobs/current').get_json()['job'] is None
        assert os.listdir(export_env) == []
        assert _download(api_client, job['id']).status_code == 404

    def test_failed_job_reports_error_and_leaves_no_file(
            self, api_client, real_db_manager, export_env):
        insert_detection(real_db_manager)
        with patch.object(real_db_manager, 'get_detections_for_export_batch',
                          side_effect=RuntimeError('disk on fire')):
            job = _prepare(api_client)
        assert job['state'] == 'failed'
        assert job['error'] and 'disk on fire' not in job['error']
        assert os.listdir(export_env) == []
        assert _download(api_client, job['id']).status_code == 404

    def test_refuses_when_file_would_cross_cleanup_trigger(
            self, api_client, real_db_manager, export_env):
        insert_detection(real_db_manager)
        with patch('core.export_jobs.cleanup_headroom_bytes', return_value=0):
            response = _start(api_client)
        assert response.status_code == 507
        assert 'space' in response.get_json()['error']
        assert api_client.get('/api/detections/export/jobs/current').get_json()['job'] is None

    @pytest.mark.parametrize('body', [[1], 'all', 5])
    def test_non_object_body_rejected(self, api_client, body):
        assert api_client.post('/api/detections/export/jobs', json=body).status_code == 400

    def test_current_reports_station_today(self, api_client):
        with patch('core.routes.detections.local_now',
                   return_value=datetime(2026, 9, 25, 1, 30)):
            body = api_client.get('/api/detections/export/jobs/current').get_json()
        assert body == {'job': None, 'today': '2026-09-25'}

    def test_bad_range_rejected(self, api_client):
        assert _start(api_client, range='fortnight').status_code == 400
        assert _start(api_client, range='custom', start_date='2024-02-01',
                      end_date='2024-01-01').status_code == 400
        assert _start(api_client, range='custom', start_date='2024-02-01').status_code == 400

    def test_count_endpoint(self, api_client, real_db_manager):
        for day in range(10, 20):
            insert_detection(real_db_manager, timestamp=f'2024-01-{day}T10:00:00')
        response = api_client.get('/api/detections/export/count?range=all')
        assert response.get_json() == {'count': 10, 'start_date': None, 'end_date': None}
        response = api_client.get(
            '/api/detections/export/count?range=custom&start_date=2024-01-15&end_date=2024-01-30')
        assert response.get_json()['count'] == 5
        assert api_client.get('/api/detections/export/count?range=bogus').status_code == 400

    def test_every_endpoint_requires_auth(self, real_db_manager):
        with auth_enabled_app(real_db_manager) as (client, _):
            assert client.get('/api/detections/export/count').status_code == 401
            assert client.post('/api/detections/export/jobs', json={}).status_code == 401
            assert client.get('/api/detections/export/jobs/current').status_code == 401
            assert client.get('/api/detections/export/jobs/abc').status_code == 401
            assert client.delete('/api/detections/export/jobs/abc').status_code == 401
            assert client.get('/api/detections/export/jobs/abc/file').status_code == 401


class TestResolveRange:

    TODAY = date(2026, 9, 24)

    @pytest.mark.parametrize('range_key, expected', [
        ('all', (None, None)),
        (None, (None, None)),
        ('7d', ('2026-09-18', '2026-09-24')),
        ('30d', ('2026-08-26', '2026-09-24')),
        ('year', ('2026-01-01', '2026-09-24')),
    ])
    def test_presets(self, range_key, expected):
        from core.export_jobs import resolve_range
        assert resolve_range(range_key, today=self.TODAY) == expected

    def test_custom(self):
        from core.export_jobs import resolve_range
        assert resolve_range('custom', '2024-01-01', '2024-01-01', today=self.TODAY) == (
            '2024-01-01', '2024-01-01')

    @pytest.mark.parametrize('args', [
        ('custom', '2024-01-02', '2024-01-01'),
        ('custom', 'yesterday', '2024-01-01'),
        ('custom', None, None),
        ('forever', None, None),
    ])
    def test_rejects(self, args):
        from core.export_jobs import resolve_range
        with pytest.raises(ValueError):
            resolve_range(*args, today=self.TODAY)


def test_startup_cleanup_removes_only_export_files(export_env):
    from core.export_jobs import cleanup_export_dir
    export_env.mkdir()
    for name in ('a.zip', 'b.zip.part', 'keep.txt'):
        (export_env / name).write_text('x')
    assert cleanup_export_dir() == 2
    assert os.listdir(export_env) == ['keep.txt']


@pytest.mark.parametrize('auto_cleanup, used_bytes, expected', [
    (True, 700, 150),   # bytes left before the 85% trigger
    (True, 900, 0),     # past the trigger: never negative
    (False, 900, 100),  # nothing is ever purged: plain free space
])
def test_cleanup_headroom_bytes(auto_cleanup, used_bytes, expected):
    from core.storage_manager import cleanup_headroom_bytes
    usage = {'total_bytes': 1000, 'used_bytes': used_bytes, 'free_bytes': 1000 - used_bytes}
    config = {'trigger_percent': 85, 'auto_cleanup_enabled': auto_cleanup}
    with patch('core.storage_manager.get_disk_usage', return_value=usage), \
         patch('core.storage_manager._get_storage_config', return_value=config):
        assert cleanup_headroom_bytes() == expected
