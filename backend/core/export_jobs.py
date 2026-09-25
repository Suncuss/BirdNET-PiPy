"""Prepared detection exports: a background job writes a zipped CSV with
real progress, and the client downloads the finished file separately.

One export at a time. Job state lives in memory (the API runs a single
gunicorn worker) and the file in data/exports/; both are gone after a
restart, so startup wipes the directory. The job greenlet only fetches
batches (DB lane) and hands them to a writer lane — a native thread — for
CSV formatting, deflate and file writes, which on the gevent hub stalled
every other request for tens of ms per batch. The CSV row shape and the
keyset batch walk are shared with the streaming GET /api/detections/export.
"""
import csv
import io
import os
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta

import core.api_infra as infra
from config.settings import BASE_DIR
from core.db_executor import create_db_executor
from core.logging_config import get_logger
from core.storage_manager import cleanup_headroom_bytes
from core.timezone_service import local_now

logger = get_logger(__name__)

EXPORT_DIR = os.path.join(BASE_DIR, 'data', 'exports')

# A ready (or failed) job and its file are kept this long for (re-)download.
EXPORT_TTL_SECONDS = 3600

# Rows per DB batch: small enough that a batch is a quick lane job holding
# ~1MB, large enough that a million-row export stays a few thousand round
# trips rather than a million.
EXPORT_BATCH_ROWS = 1000

# Deflate level 1 shrinks this CSV ~14x at ~210MB/s on a Pi 5; higher levels
# buy ~20% smaller files for 2.5x the CPU.
_ZIP_LEVEL = 1

# Disk-headroom estimate: level-1 zips measured ~25 bytes/row; 2x margin.
_EST_ZIP_BYTES_PER_ROW = 50

# Column order of get_detections_for_export_batch rows, which are written as-is.
CSV_HEADER = [
    'id', 'timestamp', 'group_timestamp', 'scientific_name', 'common_name',
    'confidence', 'latitude', 'longitude', 'cutoff', 'sensitivity', 'overlap',
    'week', 'extra', 'audio_source',
]

RANGE_PRESET_DAYS = {'7d': 7, '30d': 30}


class ExportBusyError(Exception):
    """Another export is still preparing; carries its snapshot."""

    def __init__(self, job):
        super().__init__('An export is already being prepared')
        self.job = job


class ExportSpaceError(Exception):
    """The file could push the data disk past the storage cleanup trigger."""


def iter_export_batches(db_manager, *, start_date=None, end_date=None,
                        species=None, scientific_name=None):
    """Yield the export's rows newest-first in keyset batches (the last one
    possibly empty), each ready for csv.writer.writerows. Each batch is its
    own short DB-lane job, so a long export shares the lane with live
    requests instead of holding it (and every row in memory) throughout."""
    before_timestamp = before_id = None
    while True:
        batch = infra._run_db(
            db_manager.get_detections_for_export_batch,
            start_date=start_date,
            end_date=end_date,
            species=species,
            scientific_name=scientific_name,
            before_timestamp=before_timestamp,
            before_id=before_id,
            limit=EXPORT_BATCH_ROWS,
        )
        yield batch
        if len(batch) < EXPORT_BATCH_ROWS:
            return
        before_timestamp = batch[-1]['timestamp']
        before_id = batch[-1]['id']


def resolve_range(range_key, start_date=None, end_date=None, today=None):
    """Turn a range choice into (start_date, end_date) YYYY-MM-DD strings,
    None meaning unbounded. Presets resolve against the station's local
    date, not the browser's. Raises ValueError on a bad choice or date."""
    today = today or local_now().date()
    if range_key in (None, '', 'all'):
        return None, None
    if range_key in RANGE_PRESET_DAYS:
        start = today - timedelta(days=RANGE_PRESET_DAYS[range_key] - 1)
        return start.isoformat(), today.isoformat()
    if range_key == 'year':
        return date(today.year, 1, 1).isoformat(), today.isoformat()
    if range_key == 'custom':
        try:
            start = date.fromisoformat(start_date or '')
            end = date.fromisoformat(end_date or '')
        except ValueError:
            raise ValueError('Custom range needs start_date and end_date as YYYY-MM-DD') from None
        if start > end:
            raise ValueError('start_date must not be after end_date')
        return start.isoformat(), end.isoformat()
    raise ValueError(f'Unknown range: {range_key}')


@dataclass
class ExportJob:
    start_date: str | None
    end_date: str | None
    rows_total: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = 'preparing'  # preparing -> ready | failed
    rows_done: int = 0
    bytes: int = 0
    error: str | None = None
    finished_at: float | None = None
    basename: str = ''

    def __post_init__(self):
        if self.start_date:
            span = f'{self.start_date}_to_{self.end_date}'
        else:
            span = f"all_{local_now().strftime('%Y-%m-%d')}"
        self.basename = f'birdnet_detections_{span}'

    @property
    def path(self):
        return os.path.join(EXPORT_DIR, f'{self.id}.zip')

    @property
    def filename(self):
        return f'{self.basename}.zip'

    def snapshot(self):
        expires_at = (self.finished_at + EXPORT_TTL_SECONDS
                      if self.finished_at else None)
        return {
            'id': self.id,
            'state': self.state,
            'rows_done': self.rows_done,
            'rows_total': self.rows_total,
            'bytes': self.bytes,
            'filename': self.filename,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'error': self.error,
            'expires_at': expires_at,
        }


_lock = threading.Lock()  # hub-only: taken by request handlers and the export worker greenlet, never the DB lane
_job = None  # the single current job; a job dropped from this slot is cancelled
_writer_lane = None  # native worker for the export's CPU and file work; see _run_job


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to remove export file", extra={'path': path, 'error': str(e)})


def _expire_stale_locked():
    """Drop the current job once a finished one outlives its TTL. Caller holds _lock."""
    global _job
    if (_job is not None and _job.finished_at is not None
            and time.time() >= _job.finished_at + EXPORT_TTL_SECONDS):
        _remove(_job.path)
        _job = None


def expire_stale():
    with _lock:
        _expire_stale_locked()


def current_job():
    """Snapshot of the current job (any state), or None."""
    with _lock:
        _expire_stale_locked()
        return _job.snapshot() if _job else None


def get_job(job_id):
    with _lock:
        _expire_stale_locked()
        return _job.snapshot() if _job and _job.id == job_id else None


def ready_file(job_id):
    """(path, download filename) of a ready job's file, or None."""
    with _lock:
        _expire_stale_locked()
        if _job and _job.id == job_id and _job.state == 'ready':
            return _job.path, _job.filename
        return None


def discard_job(job_id):
    """Cancel a preparing job or delete a finished one. Returns whether it existed."""
    global _job
    with _lock:
        if _job is None or _job.id != job_id:
            return False
        _remove(_job.path)
        _job = None
        return True


def _get_writer_lane():
    """The writer lane, in the API's async mode: under gevent its waits are
    cooperative, so the job greenlet parks while the native thread works.
    Created on the hub (the gevent executor binds to the calling hub)."""
    global _writer_lane
    mode = infra.db_executor.mode
    if _writer_lane is None or _writer_lane.mode != mode:
        _writer_lane = create_db_executor(mode)
    return _writer_lane


def start_export(db_manager, start_date=None, end_date=None):
    """Start preparing an export and return its snapshot. A finished
    previous job is replaced once the new one starts (a refused start leaves
    it downloadable); a still-preparing one raises ExportBusyError."""
    global _job
    with _lock:
        _expire_stale_locked()
        if _job is not None and _job.state == 'preparing':
            raise ExportBusyError(_job.snapshot())

    rows_total = infra._run_db(
        db_manager.count_detections_for_export, start_date, end_date)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    # The file lands on the disk the storage manager watches: crossing its
    # trigger would purge recordings to make room for a temporary export.
    if rows_total * _EST_ZIP_BYTES_PER_ROW > cleanup_headroom_bytes(EXPORT_DIR):
        raise ExportSpaceError(
            'Not enough free space to prepare this export without triggering '
            'storage cleanup. Choose a shorter time range or free up space.')

    job = ExportJob(start_date=start_date, end_date=end_date, rows_total=rows_total)
    with _lock:
        if _job is not None and _job.state == 'preparing':
            raise ExportBusyError(_job.snapshot())  # another start won the race
        if _job is not None:
            _remove(_job.path)
        _job = job
        lane = _get_writer_lane()
    threading.Thread(target=_run_job, args=(job, db_manager, lane), daemon=True).start()
    logger.info("Export started", extra={
        'job_id': job.id, 'rows_total': rows_total,
        'start_date': start_date, 'end_date': end_date,
    })
    return job.snapshot()


class _Cancelled(Exception):
    pass


class _ZippedCsv:
    """The export file being written. Every method runs on the writer lane."""

    def __init__(self, path, csv_name):
        self._archive = zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED,
                                        compresslevel=_ZIP_LEVEL)
        self._text = io.TextIOWrapper(
            self._archive.open(csv_name, 'w', force_zip64=True),
            encoding='utf-8', newline='')
        self._csv = csv.writer(self._text)
        self._csv.writerow(CSV_HEADER)

    def write(self, rows):
        self._csv.writerows(rows)

    def close(self):
        self._text.close()
        self._archive.close()


def _run_job(job, db_manager, lane):
    part_path = f'{job.path}.part'
    try:
        out = lane.run(_ZippedCsv, part_path, f'{job.basename}.csv')
        try:
            for batch in iter_export_batches(
                    db_manager, start_date=job.start_date, end_date=job.end_date):
                if _job is not job:
                    raise _Cancelled
                lane.run(out.write, batch)
                with _lock:
                    job.rows_done += len(batch)
                    # Rows inserted between the count and the first batch
                    # are exported too; never report more done than total.
                    job.rows_total = max(job.rows_total, job.rows_done)
        finally:
            lane.run(out.close)
        with _lock:
            if _job is not job:
                raise _Cancelled
            os.replace(part_path, job.path)
            job.bytes = os.path.getsize(job.path)
            job.rows_total = job.rows_done  # the file's actual row count
            job.state = 'ready'
            job.finished_at = time.time()
        logger.info("Export ready", extra={
            'job_id': job.id, 'rows': job.rows_done, 'bytes': job.bytes})
    except _Cancelled:
        _remove(part_path)
        logger.info("Export cancelled", extra={'job_id': job.id})
        return
    except Exception:
        logger.exception("Export failed", extra={'job_id': job.id})
        _remove(part_path)
        with _lock:
            job.state = 'failed'
            job.error = 'The export failed. Check the logs for details.'
            job.finished_at = time.time()
    # Expire the file on time even if nobody polls again.
    timer = threading.Timer(EXPORT_TTL_SECONDS + 1, expire_stale)
    timer.daemon = True
    timer.start()


def cleanup_export_dir():
    """Startup: remove files left by a previous process (its jobs are gone)."""
    if not os.path.isdir(EXPORT_DIR):
        return 0
    removed = 0
    for name in os.listdir(EXPORT_DIR):
        if name.endswith(('.zip', '.zip.part')):
            _remove(os.path.join(EXPORT_DIR, name))
            removed += 1
    if removed:
        logger.info("Removed leftover export files", extra={'removed': removed})
    return removed
