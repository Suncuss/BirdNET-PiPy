import json
import logging
import os
import sys
from datetime import datetime


class HumanReadableFormatter(logging.Formatter):
    """Formatter that outputs human-readable logs with color support"""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }

    def __init__(self, service_name, use_color=True):
        super().__init__()
        self.service_name = service_name
        self.use_color = use_color and sys.stdout.isatty()

    def format(self, record):
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')

        # Get color codes
        if self.use_color:
            level_color = self.COLORS.get(record.levelname, '')
            reset_color = self.COLORS['RESET']
        else:
            level_color = reset_color = ''

        # Format level name with fixed width
        level = f"{level_color}{record.levelname:8}{reset_color}"

        # Build the base message
        base_msg = f"[{timestamp}] {level} [{self.service_name}] {record.getMessage()}"

        # Add extra fields if present
        extras = []
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename',
                          'funcName', 'levelname', 'levelno', 'lineno',
                          'module', 'msecs', 'pathname', 'process',
                          'processName', 'relativeCreated', 'thread',
                          'threadName', 'exc_info', 'exc_text', 'stack_info']:
                if isinstance(value, (dict, list)):
                    extras.append(f"{key}={json.dumps(value)}")
                else:
                    extras.append(f"{key}={value}")

        if extras:
            base_msg += " | " + " | ".join(extras)

        # Add exception info if present
        if record.exc_info:
            base_msg += "\n" + self.formatException(record.exc_info)

        return base_msg

class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs JSON-structured logs"""

    def __init__(self, service_name):
        super().__init__()
        self.service_name = service_name

    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'service': self.service_name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage()
        }

        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)

        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename',
                          'funcName', 'levelname', 'levelno', 'lineno',
                          'module', 'msecs', 'pathname', 'process',
                          'processName', 'relativeCreated', 'thread',
                          'threadName', 'exc_info', 'exc_text', 'stack_info']:
                log_obj[key] = value

        return json.dumps(log_obj)

def setup_logging(service_name, log_level=None, format_type=None):
    """
    Setup logging for a service with configurable format

    Args:
        service_name: Name of the service (e.g., 'api', 'birdnet', 'main')
        log_level: Logging level (defaults to env var LOG_LEVEL or INFO)
        format_type: 'json' or 'human' (defaults to env var LOG_FORMAT or 'human')
    """
    if log_level is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO')

    if format_type is None:
        format_type = os.getenv('LOG_FORMAT', 'human').lower()

    # Get root logger
    logger = logging.getLogger()

    # Check if logging is already configured to prevent duplicates
    if hasattr(logger, '_birdnet_configured'):
        return logger

    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers to prevent duplicates
    logger.handlers = []

    # Create console handler with appropriate formatter
    handler = logging.StreamHandler(sys.stdout)

    if format_type == 'json':
        handler.setFormatter(StructuredFormatter(service_name))
    else:
        handler.setFormatter(HumanReadableFormatter(service_name))

    logger.addHandler(handler)

    # Mark as configured to prevent duplicate setup
    logger._birdnet_configured = True

    # Suppress noisy libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('watchdog.observers.inotify_buffer').setLevel(logging.WARNING)

    return logger

def get_logger(name):
    """Get a logger instance for a specific module"""
    return logging.getLogger(name)

# Example usage patterns
class LoggerMixin:
    """Mixin class to add logging capabilities to any class"""

    @property
    def logger(self):
        if not hasattr(self, '_logger'):
            self._logger = logging.getLogger(self.__class__.__module__ + '.' + self.__class__.__name__)
        return self._logger

# Decorators for common logging patterns
import functools
import time


def log_execution_time(func):
    """Decorator to log function execution time"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.info(f"{func.__name__} completed", extra={
                'execution_time': execution_time,
                'function_name': func.__name__
            })
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func.__name__} failed", extra={
                'execution_time': execution_time,
                'function_name': func.__name__,
                'error': str(e)
            }, exc_info=True)
            raise
    return wrapper

def log_api_request(func):
    """Decorator to log API requests"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from flask import request
        logger = logging.getLogger(func.__module__)

        # Generate request ID
        request_id = request.headers.get('X-Request-ID',
                                       datetime.utcnow().strftime('%Y%m%d%H%M%S%f'))

        logger.info(f"API request: {request.method} {request.path}", extra={
            'request_id': request_id,
            'method': request.method,
            'path': request.path,
            'remote_addr': request.remote_addr
        })

        try:
            result = func(*args, **kwargs)
            logger.info(f"API response: {request.method} {request.path}", extra={
                'request_id': request_id,
                'status': 200
            })
            return result
        except Exception as e:
            logger.error(f"API error: {request.method} {request.path}", extra={
                'request_id': request_id,
                'error': str(e)
            }, exc_info=True)
            raise
    return wrapper
