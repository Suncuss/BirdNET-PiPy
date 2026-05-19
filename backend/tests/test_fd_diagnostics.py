import errno
from unittest.mock import Mock, patch

from core import fd_diagnostics


def setup_function():
    fd_diagnostics.reset_fd_diagnostics_for_tests()


def test_find_fd_exhaustion_errno_from_oserror():
    error = OSError(errno.EMFILE, 'Too many open files')

    assert fd_diagnostics.find_fd_exhaustion_errno(error) == errno.EMFILE


def test_find_fd_exhaustion_errno_from_wrapped_exception_arg():
    error = RuntimeError(OSError(errno.ENFILE, 'File table overflow'))

    assert fd_diagnostics.find_fd_exhaustion_errno(error) == errno.ENFILE


def test_find_fd_exhaustion_errno_from_reason_attribute():
    """urllib3.MaxRetryError stores the underlying error on .reason."""
    class FakeMaxRetryError(Exception):
        def __init__(self, reason):
            super().__init__('Max retries exceeded')
            self.reason = reason

    error = FakeMaxRetryError(OSError(errno.EMFILE, 'Too many open files'))

    assert fd_diagnostics.find_fd_exhaustion_errno(error) == errno.EMFILE


def test_non_fd_error_does_not_log():
    logger = Mock()

    logged = fd_diagnostics.log_fd_exhaustion_if_needed(
        OSError(errno.ENOENT, 'missing'),
        logger,
        'test_stage',
    )

    assert logged is False
    logger.error.assert_not_called()


def test_fd_error_logs_diagnostics_once_per_stage():
    logger = Mock()
    error = OSError(errno.EMFILE, 'Too many open files')

    with patch.object(fd_diagnostics, 'collect_fd_diagnostics', return_value={
        'fd_count': 1024,
        'fd_limit_soft': 1024,
        'fd_limit_hard': 4096,
        'fd_sample': ['0->/dev/null'],
        'active_children': [],
    }):
        first_logged = fd_diagnostics.log_fd_exhaustion_if_needed(
            error,
            logger,
            'test_stage',
            extra={'file': 'recording.wav'},
        )
        second_logged = fd_diagnostics.log_fd_exhaustion_if_needed(
            error,
            logger,
            'test_stage',
        )

    assert first_logged is True
    assert second_logged is False
    logger.error.assert_called_once()

    _message, kwargs = logger.error.call_args
    assert kwargs['extra']['stage'] == 'test_stage'
    assert kwargs['extra']['errno'] == errno.EMFILE
    assert kwargs['extra']['fd_count'] == 1024
    assert kwargs['extra']['file'] == 'recording.wav'
