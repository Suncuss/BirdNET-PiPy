"""Move media while the recording process has its workers stopped.

Requests and progress live with the existing control flags. The API queues a
validated settings change; main performs the move, so it can pause and resume
its own recording, analysis and cleanup workers without restarting the API.
"""
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import core.maintenance_lease as maintenance_lease
from config.settings import BASE_DIR
from core.logging_config import get_logger
from core.media_storage import (
    _INTERNAL_MEDIA_ROOT,
    EXTERNAL_MEDIA_APP_DIR,
    MEDIA_TARGET_INTERNAL,
    get_available_media_targets,
    get_effective_media_root,
    get_media_storage_status,
)
from core.secure_file import atomic_write_private_json

logger = get_logger(__name__)
REQUEST_PATH = os.path.join(BASE_DIR, 'data/flags/media-transfer-request.json')
STATUS_PATH = os.path.join(BASE_DIR, 'data/flags/media-transfer-status.json')
MEDIA_SUBDIRS = ('audio/recordings', 'audio/extracted_songs', 'spectrograms')
_CHUNK = 1024 * 1024


def _read(path):
    try:
        with open(path) as stream:
            return json.load(stream)
    except FileNotFoundError:
        return None


def transfer_pending():
    return os.path.isfile(REQUEST_PATH)


def transfer_status():
    return _read(STATUS_PATH) or {'state': 'idle'}


def queue_transfer(settings, changes):
    if transfer_pending():
        raise ValueError('A media move is already in progress.')
    target = settings['storage']['media_target']
    status = get_media_storage_status(settings)
    if status['effective_target_id'] != target:
        raise ValueError('The selected storage is unavailable or not writable.')
    job = uuid.uuid4().hex
    # Publish the request last, after its initial progress is available.
    atomic_write_private_json(STATUS_PATH, {
        'id': job, 'state': 'waiting', 'message': 'Waiting to pause recording',
        'files_done': 0, 'files_total': 0, 'bytes_done': 0, 'bytes_total': 0,
        'requested_at': time.time(),
    })
    atomic_write_private_json(REQUEST_PATH, {
        'id': job, 'settings': settings, 'changes': changes,
    })
    return transfer_status()


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b''):
            digest.update(chunk)
    return digest.digest()


def move_media(settings, report, checkpoint=lambda: None):
    """Copy and verify all visible media; return originals for later removal.

    No source is removed here. The caller must save the selected location
    successfully before removing originals. Database/settings paths are never
    included in the file plan.
    """
    status = get_media_storage_status(settings)
    if status['effective_target_id'] != settings['storage']['media_target']:
        raise ValueError('The selected storage is unavailable or not writable.')
    destination = Path(get_effective_media_root(settings)).resolve()
    roots = [Path(_INTERNAL_MEDIA_ROOT)]
    for target in get_available_media_targets():
        if target['id'] != MEDIA_TARGET_INTERNAL:
            roots.append(Path(target['mount_path']) / EXTERNAL_MEDIA_APP_DIR)
    plan = []
    seen = set()
    for root in roots:
        for subdir in MEDIA_SUBDIRS:
            directory = root / subdir
            if not directory.is_dir() or directory.resolve() == destination / subdir:
                continue
            for parent, dirs, files in os.walk(directory, followlinks=False):
                if any((Path(parent) / name).is_symlink() for name in dirs):
                    raise ValueError('Media folders contain symbolic links. No files have been moved.')
                for name in files:
                    if name.endswith('.part'):
                        continue  # Unfinished recordings/clips are not published media.
                    src = Path(parent) / name
                    if src.is_symlink():
                        raise ValueError('Media files contain symbolic links. No files have been moved.')
                    if src.resolve() in seen:
                        continue
                    seen.add(src.resolve())
                    dst = destination / subdir / src.relative_to(directory)
                    plan.append((src, dst, src.stat().st_size))
    total = sum(size for _, _, size in plan)
    needed = sum(size for _, dst, size in plan if not dst.exists())
    if needed > shutil.disk_usage(status['effective_target']['mount_path']).free:
        raise ValueError('Not enough free space on the selected storage. Original files are unchanged.')
    report(state='copying', message='Recording paused · Copying media',
           files_total=len(plan), bytes_total=total, files_done=0, bytes_done=0)
    done = 0
    originals = []
    for index, (src, dst, size) in enumerate(plan):
        checkpoint()
        dst.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        if dst.exists():
            if _hash_file(src) != _hash_file(dst):
                raise ValueError(f'A different file already exists at the destination: {src.name}. Originals are unchanged.')
            done += size
        else:
            temp = dst.with_name('.' + dst.name + '.media-transfer.part')
            try:
                with open(src, 'rb') as source, open(temp, 'wb') as output:
                    for chunk in iter(lambda: source.read(_CHUNK), b''):
                        checkpoint()
                        output.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        report(bytes_done=done)
                    output.flush()
                    os.fsync(output.fileno())
                report(message='Recording paused · Verifying copied media')
                if _hash_file(temp) != digest.digest():
                    raise OSError('Copied media verification failed. Originals are unchanged.')
                os.replace(temp, dst)
            finally:
                temp.unlink(missing_ok=True)
        originals.append(src)
        report(files_done=index + 1, bytes_done=done,
               message='Recording paused · Copying media')
    return originals


def handle_pending_transfer(pause_workers, resume_workers, db_manager, cancelled=lambda: False):
    """Run one queued move on main's supervisor thread, then resume workers."""
    request = _read(REQUEST_PATH)
    if request is None:
        return False
    progress = transfer_status()
    owner = maintenance_lease.mint_owner_token()
    acquired = False
    saved = False
    last_report = 0
    last_renewal = time.monotonic()

    def report(**values):
        nonlocal last_report
        changed = any(progress.get(key) != value for key, value in values.items() if key != 'bytes_done')
        progress.update(values)
        if changed or time.monotonic() - last_report >= .25:
            atomic_write_private_json(STATUS_PATH, progress)
            last_report = time.monotonic()

    def checkpoint():
        nonlocal last_renewal
        if cancelled():
            raise InterruptedError('Media move interrupted by shutdown.')
        if time.monotonic() - last_renewal > 30:
            if not maintenance_lease.renew(db_manager, owner, 120):
                raise RuntimeError('Media move lost its maintenance lock. Originals are unchanged.')
            last_renewal = time.monotonic()

    try:
        report(state='pausing', message='Pausing recording, analysis and cleanup')
        pause_workers()
        acquired = maintenance_lease.acquire(db_manager, 'media_transfer', owner, 120)
        if not acquired:
            raise ValueError('Another import or maintenance task is running. Retry after it finishes.')
        report(state='checking', message='Recording paused · Checking media and free space')
        originals = move_media(request['settings'], report, checkpoint)
        from core.settings_store import save_user_settings
        report(state='saving', message='Recording paused · Saving storage location')
        save_user_settings(request['settings'])
        saved = True
        report(state='removing', message='Recording paused · Removing verified originals')
        remaining = 0
        for src in originals:
            checkpoint()
            try:
                src.unlink()
            except OSError:
                remaining += 1
                logger.warning('Verified media copied, but original could not be removed', extra={'file': src.name})
        # Resuming these workers applies the storage change. A simultaneous
        # model change still follows the existing full service restart flow.
        changes = request['changes']
        changes['full_restart_paths'] = [p for p in changes['full_restart_paths'] if p != 'storage.media_target']
        changes['full_restart_required'] = bool(changes['full_restart_paths'])
        report(state='resuming', message='Resuming recording', changes=changes)
        if remaining:
            progress['warning'] = f'{remaining} original files could not be removed; verified copies are at the new location.'
    except Exception as exc:
        logger.exception('Media move failed')
        progress.update(state='failed', message=str(exc), location_saved=saved)
    finally:
        if acquired:
            try:
                maintenance_lease.release(db_manager, owner)
            except Exception as exc:
                logger.exception('Could not release media maintenance lock')
                progress.update(state='failed', message=f'Media move ended, but maintenance could not finish: {exc}')
        try:
            resume_workers()
        except Exception as exc:
            logger.exception('Could not resume recording after media move')
            progress.update(state='failed', message=f'Media move ended, but recording could not resume: {exc}')
        Path(REQUEST_PATH).unlink(missing_ok=True)
        progress['location_saved'] = saved
        if progress['state'] != 'failed':
            progress.update(state='complete', message='Media moved · Recording resumed')
        atomic_write_private_json(STATUS_PATH, progress)
    return True
