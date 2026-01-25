"""
API utility functions and decorators for BirdNet-PiPy
Provides common functionality for error handling, logging, validation, and file serving
"""

from functools import wraps
from flask import jsonify, request, send_from_directory, make_response
from datetime import datetime
import os
from core.logging_config import get_logger

logger = get_logger(__name__)


def handle_api_errors(f):
    """
    Decorator to handle common API errors in a standardized way
    
    Catches and formats various exceptions into consistent JSON responses:
    - ValueError: 400 Bad Request
    - FileNotFoundError: 404 Not Found  
    - KeyError: 400 Bad Request
    - Exception: 500 Internal Server Error
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"Validation error in {f.__name__}", extra={
                'endpoint': f.__name__,
                'error': str(e),
                'request_args': dict(request.args)
            })
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            logger.warning(f"Resource not found in {f.__name__}", extra={
                'endpoint': f.__name__,
                'error': str(e)
            })
            return jsonify({"error": str(e)}), 404
        except KeyError as e:
            logger.warning(f"Missing required parameter in {f.__name__}", extra={
                'endpoint': f.__name__,
                'missing_key': str(e)
            })
            return jsonify({"error": f"Missing required parameter: {e}"}), 400
        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}", extra={
                'endpoint': f.__name__,
                'error': str(e),
                'error_type': type(e).__name__
            }, exc_info=True)
            return jsonify({"error": "Internal server error"}), 500
    return decorated_function


def validate_date_param(param_name='date', required=False, default_today=True):
    """
    Decorator to validate date parameters in YYYY-MM-DD format
    
    Args:
        param_name: Name of the date parameter to validate
        required: Whether the parameter is required
        default_today: If True and parameter missing, use today's date
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            date_str = request.args.get(param_name)
            
            # Handle missing parameter
            if not date_str:
                if required:
                    return jsonify({"error": f"Date parameter is required"}), 400
                elif default_today:
                    # No need to validate, will use default in endpoint
                    return f(*args, **kwargs)
                else:
                    return f(*args, **kwargs)
            
            # Validate format
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": f"Invalid date format. Use YYYY-MM-DD."}), 400
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def serve_file_with_fallback(directory, filename, default_file_path, file_type="file"):
    """
    Generic file serving function with fallback to default file

    Args:
        directory: Directory to look for the file
        filename: Name of the file to serve
        default_file_path: Full path to default file if requested file not found
        file_type: Type of file for logging (e.g., "audio", "spectrogram")

    Returns:
        Flask response object
    """
    # Security: Validate filename to prevent path traversal attacks
    # Reject filenames with path separators or parent directory references
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        logger.warning(f"Invalid {file_type} filename rejected", extra={
            'filename': filename,
            'type': file_type
        })
        default_dir = os.path.dirname(default_file_path)
        default_name = os.path.basename(default_file_path)
        return make_response(send_from_directory(default_dir, default_name))

    file_path = os.path.join(directory, filename)

    # Security: Verify resolved path is within the directory (prevents symlink attacks)
    real_dir = os.path.realpath(directory)
    real_file = os.path.realpath(file_path)
    if not real_file.startswith(real_dir + os.sep) and real_file != real_dir:
        logger.warning(f"Symlink attack attempt blocked for {file_type}", extra={
            'filename': filename,
            'resolved_path': real_file,
            'expected_dir': real_dir
        })
        default_dir = os.path.dirname(default_file_path)
        default_name = os.path.basename(default_file_path)
        return make_response(send_from_directory(default_dir, default_name))

    if os.path.exists(file_path):
        logger.debug(f"Serving {file_type} file", extra={
            'file': filename,
            'type': file_type
        })
        return make_response(send_from_directory(directory, filename))
    else:
        logger.warning(f"{file_type.capitalize()} file not found, serving default", extra={
            'requested_file': filename,
            'type': file_type
        })
        default_dir = os.path.dirname(default_file_path)
        default_name = os.path.basename(default_file_path)
        return make_response(send_from_directory(default_dir, default_name))


def validate_limit_param(default=10, min_val=1, max_val=100):
    """
    Decorator to validate and constrain 'limit' parameter
    
    Args:
        default: Default value if not provided
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                limit = request.args.get('limit', default=default, type=int)
                if limit < min_val or limit > max_val:
                    return jsonify({"error": f"Limit must be between {min_val} and {max_val}"}), 400
            except ValueError:
                return jsonify({"error": "Limit must be a valid integer"}), 400
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_data_metrics(endpoint_name, data, custom_metrics=None):
    """
    Log standardized metrics about returned data
    
    Args:
        endpoint_name: Name of the endpoint
        data: The data being returned
        custom_metrics: Optional dict of custom metrics to log
    """
    metrics = {
        'endpoint': endpoint_name
    }
    
    # Add standard metrics based on data type
    if isinstance(data, list):
        metrics['count'] = len(data)
    elif isinstance(data, dict):
        metrics['keys'] = list(data.keys())
        
    # Add custom metrics
    if custom_metrics:
        metrics.update(custom_metrics)
        
    logger.debug(f"Data returned from {endpoint_name}", extra=metrics)