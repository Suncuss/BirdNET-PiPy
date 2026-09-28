"""Prepared detection exports: a background job writes a zipped CSV with
real progress, and the client downloads the finished file separately.

One export at a time. Job state lives in memory (the API runs a single
gunicorn worker) and the file in data/exports/; both are gone after a
restart, so startup wipes the directory. The job greenlet only fetches
batches (DB lane) and hands them to a writer lane — a native thread — for
CSV formatting, deflate and file writes, which on the gevent hub stalled
every other request for tens of ms per batch. The CSV row shape, the keyset
batch walk and the writer lane are shared with the streaming
GET /api/detections/export.
"""
import contextlib
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
    """Another export is still preparing, or took the slot while this start
    counted; carries its snapshot."""

    def __init__(self, job):
        super().__init__('An export is already being prepared')
        self.job = job


class ExportSpaceError(Exception):
    """The file could push the data disk past the storage cleanup trigger."""


class ExportEmptyError(Exception):
    """The range has no detections, so there is nothing to export."""


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


def _csv_text(rows):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()


def iter_csv_chunks(db_manager, **filters):
    """The streaming export's body: the header, then each batch as CSV text,
    formatted on the writer lane so it stays off the gevent hub like the
    job's writes. ``filters`` are iter_export_batches' keyword arguments."""
    yield _csv_text([CSV_HEADER])
    for batch in iter_export_batches(db_manager, **filters):
        yield _writer_lane.run(_csv_text, batch)


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
_writer_lane = None  # native worker for CSV formatting, deflate and file writes; see reset_writer_lane


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


def reset_writer_lane(async_mode):
    """Boot: start the writer lane in the app's async mode, next to
    api_infra.reset_db_executor and like it on the hub (the gevent executor
    binds to the calling hub). Under gevent its waits are cooperative, so a
    waiting greenlet parks while the native thread works."""
    global _writer_lane
    if _writer_lane is not None:
        _writer_lane.shutdown(wait=False)
    _writer_lane = create_db_executor(async_mode)


def start_export(db_manager, start_date=None, end_date=None):
    """Start preparing an export and return its snapshot. A finished
    previous job is replaced once the new one starts (a refused or failed
    start leaves it downloadable); a still-preparing one, or one another
    start put in the slot meanwhile, raises ExportBusyError."""
    global _job
    if _writer_lane is None:
        raise RuntimeError('Export writer lane not started (reset_writer_lane runs at boot)')
    with _lock:
        _expire_stale_locked()
        if _job is not None and _job.state == 'preparing':
            raise ExportBusyError(_job.snapshot())
        seen = _job

    rows_total = infra._run_db(
        db_manager.count_detections_for_export, start_date, end_date)
    if not rows_total:
        raise ExportEmptyError('No detections in this range.')
    os.makedirs(EXPORT_DIR, exist_ok=True)
    # The file lands on the disk the storage manager watches: crossing its
    # trigger would purge recordings to make room for a temporary export.
    # The export this start replaces is deleted once it starts, so its bytes
    # count as free.
    headroom = cleanup_headroom_bytes(EXPORT_DIR) + (seen.bytes if seen else 0)
    if rows_total * _EST_ZIP_BYTES_PER_ROW > headroom:
        raise ExportSpaceError(
            'Not enough free space to prepare this export without triggering '
            'storage cleanup. Choose a shorter time range or free up space.')

    job = ExportJob(start_date=start_date, end_date=end_date, rows_total=rows_total)
    with _lock:
        if _job is not None and _job is not seen:
            # Another start won the race while we counted; its export,
            # even if already finished, is not ours to replace.
            raise ExportBusyError(_job.snapshot())
        worker = threading.Thread(target=_run_job, name='export-job', daemon=True,
                                  args=(job, db_manager, _writer_lane))
        previous, _job = _job, job
    try:
        worker.start()
    except BaseException:
        with _lock:
            if _job is job:
                _job = previous  # no worker will ever finish this job
        raise
    if previous is not None:
        _remove(previous.path)
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
        try:
            self._text = io.TextIOWrapper(
                self._archive.open(csv_name, 'w', force_zip64=True),
                encoding='utf-8', newline='')
            self._csv = csv.writer(self._text)
            self._csv.writerow(CSV_HEADER)
        except BaseException:
            self._archive.close()
            raise

    def write(self, rows):
        self._csv.writerows(rows)

    def close(self):
        # The archive (and its file descriptor) is closed even when flushing
        # the CSV's last deflate block fails, e.g. on a full disk.
        try:
            self._text.close()
        finally:
            self._archive.close()


def _write_batches(job, db_manager, lane, out):
    """Fetch each batch (DB lane) and write it (writer lane), in turn.

    Taking turns is deliberate: overlapping them (submit the write, fetch
    the next batch, then wait on the write) was no faster under gevent
    (300k rows, interleaved runs: 6.75s vs 6.71s mean) and stalled the hub
    a little more (p99 4.5ms vs 3.6ms). Both lanes do GIL-bound Python
    work, so they barely run at once."""
    for batch in iter_export_batches(
            db_manager, start_date=job.start_date, end_date=job.end_date):
        if _job is not job:
            raise _Cancelled
        lane.run(out.write, batch)
        with _lock:
            job.rows_done += len(batch)
            # Rows inserted between the count and the first batch are
            # exported too; never report more done than total.
            job.rows_total = max(job.rows_total, job.rows_done)


def _run_job(job, db_manager, lane):
    part_path = f'{job.path}.part'
    try:
        out = lane.run(_ZippedCsv, part_path, f'{job.basename}.csv')
        try:
            _write_batches(job, db_manager, lane, out)
        except BaseException:
            # Abandoned (cancelled or failed): close only to release the
            # file, and never let a close error replace the reason.
            with contextlib.suppress(Exception):
                lane.run(out.close)
            raise
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
