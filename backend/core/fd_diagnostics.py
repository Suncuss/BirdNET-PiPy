"""Diagnostics for file descriptor exhaustion failures."""

import errno
import os
import resource
import threading
import time
from collections.abc import Iterable

FD_EXHAUSTION_ERRNOS = {errno.EMFILE, errno.ENFILE}
FD_DIAGNOSTIC_INTERVAL_SECONDS = 300
FD_SAMPLE_LIMIT = 40
CHILD_SAMPLE_LIMIT = 20

_last_log_at: dict[str, float] = {}
_last_log_lock = threading.Lock()


def find_fd_exhaustion_errno(error: BaseException) -> int | None:
    """Return EMFILE/ENFILE errno from an exception chain, if present."""
    seen: set[int] = set()
    stack: list[BaseException] = [error]

    while stack:
        current = stack.pop()
        obj_id = id(current)
        if obj_id in seen:
            continue
        seen.add(obj_id)

        err = getattr(current, 'errno', None)
        if isinstance(err, int) and err in FD_EXHAUSTION_ERRNOS:
            return err

        if isinstance(current, OSError):
            err = current.errno
            if err in FD_EXHAUSTION_ERRNOS:
                return err

        for linked in (current.__cause__, current.__context__):
            if isinstance(linked, BaseException):
                stack.append(linked)

        for arg in getattr(current, 'args', ()):
            if isinstance(arg, BaseException):
                stack.append(arg)

        # urllib3.MaxRetryError stores the underlying error on .reason,
        # not in args/__cause__/__context__ — walk it so EMFILE buried in
        # a requests.ConnectionError(MaxRetryError(...)) chain is detected.
        reason = getattr(current, 'reason', None)
        if isinstance(reason, BaseException):
            stack.append(reason)

    return None


def _sorted_fds(fd_names: Iterable[str]) -> list[str]:
    def sort_key(value: str):
        try:
            return (0, int(value))
        except ValueError:
            return (1, value)

    return sorted(fd_names, key=sort_key)


def collect_fd_diagnostics() -> dict:
    """Collect best-effort FD state without raising."""
    diagnostics: dict = {}

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        diagnostics['fd_limit_soft'] = soft
        diagnostics['fd_limit_hard'] = hard
    except Exception as e:
        diagnostics['fd_limit_error'] = str(e)

    try:
        fd_names = _sorted_fds(os.listdir('/proc/self/fd'))
        diagnostics['fd_count'] = len(fd_names)
        diagnostics['fd_sample'] = _collect_fd_sample(fd_names)
        if len(fd_names) > FD_SAMPLE_LIMIT:
            diagnostics['fd_sample_truncated'] = len(fd_names) - FD_SAMPLE_LIMIT
    except Exception as e:
        diagnostics['fd_scan_error'] = str(e)

    try:
        diagnostics['active_children'] = _collect_active_children()
    except Exception as e:
        diagnostics['active_children_error'] = str(e)

    return diagnostics


def _collect_fd_sample(fd_names: list[str]) -> list[str]:
    sample = []
    for fd in fd_names[:FD_SAMPLE_LIMIT]:
        try:
            target = os.readlink(f'/proc/self/fd/{fd}')
        except Exception as e:
            target = f'<unreadable: {e}>'
        sample.append(f'{fd}->{target}')
    return sample


def _collect_active_children() -> list[dict]:
    child_pids: set[str] = set()
    task_dir = '/proc/self/task'

    for tid in os.listdir(task_dir):
        children_path = os.path.join(task_dir, tid, 'children')
        try:
            with open(children_path, encoding='utf-8') as f:
                child_pids.update(pid for pid in f.read().split() if pid)
        except OSError:
            continue

    children = []
    for pid in sorted(child_pids, key=int)[:CHILD_SAMPLE_LIMIT]:
        children.append(_describe_process(pid))

    if len(child_pids) > CHILD_SAMPLE_LIMIT:
        children.append({'truncated': len(child_pids) - CHILD_SAMPLE_LIMIT})

    return children


def _describe_process(pid: str) -> dict:
    info = {'pid': int(pid)}
    try:
        with open(f'/proc/{pid}/comm', encoding='utf-8') as f:
            info['name'] = f.read().strip()
    except OSError as e:
        info['name_error'] = str(e)

    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
            info['cmdline'] = cmdline[:300]
    except OSError as e:
        info['cmdline_error'] = str(e)

    return info


def log_fd_exhaustion_if_needed(
    error: BaseException,
    logger,
    stage: str,
    extra: dict | None = None,
) -> bool:
    """Log FD diagnostics for EMFILE/ENFILE, rate-limited per stage."""
    fd_errno = find_fd_exhaustion_errno(error)
    if fd_errno is None:
        return False

    if not _should_log(stage):
        return False

    diagnostics = collect_fd_diagnostics()
    diagnostics.update({
        'stage': stage,
        'errno': fd_errno,
        'error': str(error),
    })
    if extra:
        diagnostics.update(extra)

    logger.error("FD exhaustion detected", extra=diagnostics)
    return True


def _should_log(stage: str) -> bool:
    now = time.monotonic()
    with _last_log_lock:
        last = _last_log_at.get(stage)
        if last is not None and now - last < FD_DIAGNOSTIC_INTERVAL_SECONDS:
            return False
        _last_log_at[stage] = now
        return True


def reset_fd_diagnostics_for_tests() -> None:
    """Clear diagnostic rate-limit state for tests."""
    with _last_log_lock:
        _last_log_at.clear()
