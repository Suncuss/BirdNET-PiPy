"""System endpoints: storage, version, update check/trigger, restart, logs.

Owns the update-check response cache (1h TTL, keyed by channel+commit) and the
HA-mode update flow (supervisor + update-entity polling). The GitHub/version/
flag primitives live in core.update_service; these routes shape them into
HTTP responses. Registered on the shared ``api`` blueprint at import time.
"""
import os
import time

import requests
from flask import jsonify, request

from config.settings import BASE_DIR
from core.api_infra import api
from core.api_utils import handle_api_errors
from core.auth import get_request_tier, require_auth, require_scope
from core.ha_mode import get_runtime_mode, is_home_assistant_mode
from core.logging_config import get_logger, log_api_request
from core.settings_store import load_user_settings
from core.update_service import (
    _HA_CORE_API_BASE,
    GITHUB_OWNER,
    GITHUB_REPO,
    _call_supervisor,
    _find_addon_update_entity,
    fetch_update_notes,
    get_commits_comparison,
    get_latest_remote_commit,
    load_ha_source_commit,
    load_version_info,
    should_show_update_note,
    write_flag,
)

logger = get_logger(__name__)

# Update check cache (only cache successful responses)
_update_check_cache = {
    'result': None,
    'timestamp': 0,
    'cache_key': None  # format: "channel:current_commit"
}
UPDATE_CHECK_CACHE_TTL = 3600  # 1 hour in seconds


def _build_update_check_result(update_available, current_commit, remote_commit,
                                commits_behind, current_branch, target_branch,
                                channel, preview_commits, fresh_sync, update_note):
    """Build the update check response dictionary."""
    return {
        'update_available': update_available,
        'current_commit': current_commit,
        'remote_commit': remote_commit,
        'commits_behind': commits_behind,
        'current_branch': current_branch,
        'target_branch': target_branch,
        'channel': channel,
        'preview_commits': preview_commits,
        'fresh_sync': fresh_sync,
        'update_note': update_note
    }


def _cache_and_return_update_result(result, cache_key, now):
    """Cache the result and return JSON response."""
    _update_check_cache['result'] = result
    _update_check_cache['timestamp'] = now
    _update_check_cache['cache_key'] = cache_key
    return jsonify(result), 200



# How long to wait for HA Core's update entity to refresh after triggering
# homeassistant.update_entity (fire-and-forget) before giving up.
_HA_ENTITY_POLL_TIMEOUT_SECONDS = 15
_HA_ENTITY_POLL_INTERVAL_SECONDS = 0.5


@api.route('/api/system/storage', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_system_storage():
    """Get disk storage information for the data directory (matches df output)"""
    data_path = os.path.join(BASE_DIR, 'data')

    try:
        # Use statvfs to match df's calculation (excludes reserved blocks)
        stat = os.statvfs(data_path)
        block_size = stat.f_frsize

        total_bytes = stat.f_blocks * block_size
        free_bytes = stat.f_bfree * block_size
        avail_bytes = stat.f_bavail * block_size  # Available to non-root (what df shows)
        used_bytes = total_bytes - free_bytes

        total_gb = total_bytes / (1024 ** 3)
        used_gb = used_bytes / (1024 ** 3)
        avail_gb = avail_bytes / (1024 ** 3)

        # Match df's percentage: used / (used + available)
        percent_used = (used_bytes / (used_bytes + avail_bytes)) * 100

        return jsonify({
            'total_gb': round(total_gb, 1),
            'used_gb': round(used_gb, 1),
            'free_gb': round(avail_gb, 1),
            'percent_used': round(percent_used, 0)
        }), 200
    except Exception as e:
        logger.error("Failed to get storage info", extra={'error': str(e)})
        return jsonify({'error': f'Failed to get storage info: {str(e)}'}), 500


def _public_version_view(response):
    """Drop the build fingerprint (exact commit + branch) for anonymous callers.

    The precise commit and branch let anyone match a pinned build to a known CVE.
    Only the owner needs them (Settings displays them); the public view keeps
    ``version`` + ``runtime_mode`` so the background update check still works
    without popping a login modal.
    """
    if get_request_tier() == 'public':
        for field in ('current_commit', 'current_commit_date', 'current_branch'):
            response.pop(field, None)
    return response


@api.route('/api/system/version', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_system_version():
    """Get current system version info for native or HA mode."""
    try:
        response = {}
        runtime_mode = get_runtime_mode()

        if runtime_mode == 'ha':
            app_source_commit = load_ha_source_commit()
            response = {
                'version': os.environ.get('BUILD_VERSION', 'unknown'),
                'current_commit': app_source_commit or 'unknown',
                'current_commit_date': 'unknown',
                'current_branch': 'home_assistant',
                'remote_url': f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}',
                'runtime_mode': runtime_mode,
            }
            return jsonify(_public_version_view(response)), 200

        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        return jsonify(_public_version_view({
            'version': version_info.get('version', 'unknown'),
            'current_commit': version_info.get('commit', 'unknown'),
            'current_commit_date': version_info.get('commit_date', 'unknown'),
            'current_branch': version_info.get('branch', 'unknown'),
            'remote_url': version_info.get('remote_url', f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}'),
            'runtime_mode': runtime_mode,
        })), 200
    except Exception as e:
        return jsonify({'error': f'Failed to get version info: {str(e)}'}), 500

def get_channel_branch():
    """Get the target branch based on update channel setting.

    Returns:
        tuple: (channel, branch) where channel is 'release' or 'latest'
               and branch is 'main' or 'staging'
    """
    settings = load_user_settings()
    channel = settings.get('updates', {}).get('channel', 'release')

    # Normalize old "stable" setting and unknown values to "release" (safe default)
    if channel not in ('release', 'latest'):
        channel = 'release'

    # Map channel to branch
    branch = 'main' if channel == 'release' else 'staging'
    return channel, branch


@api.route('/api/system/update-check', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def check_for_updates():
    """Check if updates are available using GitHub API.

    Compares current commit against the HEAD of the configured channel's branch:
    - release channel: compares against main branch
    - latest channel: compares against staging branch

    Query params:
    - force: Set to 'true' to bypass cache (used by manual "Check for Updates" button)
    """
    try:
        if is_home_assistant_mode():
            force = request.args.get('force', 'false').lower() == 'true'
            if force:
                _call_supervisor('POST', '/store/reload', timeout=30)

            info, error = _call_supervisor('GET', '/addons/self/info')
            if error:
                return jsonify({'error': f'Failed to check for updates: {error}'}), 502

            return jsonify({
                'update_available': bool(info.get('update_available')),
                'runtime_mode': 'ha',
                'current_version': info.get('version', 'unknown'),
                'latest_version': info.get('version_latest'),
                'update_note': None,
            }), 200

        force = request.args.get('force', 'false').lower() == 'true'

        # Load current version info
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        current_commit = version_info.get('commit', '')
        current_branch = version_info.get('branch', 'main')

        # Get target branch based on channel setting
        channel, target_branch = get_channel_branch()

        # Build cache key and check cache (skip if force=true)
        cache_key = f"{channel}:{current_commit}"
        now = time.time()

        if not force and _update_check_cache['cache_key'] == cache_key:
            if now - _update_check_cache['timestamp'] < UPDATE_CHECK_CACHE_TTL:
                logger.debug("Returning cached update check result", extra={
                    'cache_key': cache_key,
                    'cache_age_seconds': int(now - _update_check_cache['timestamp'])
                })
                return jsonify(_update_check_cache['result']), 200

        logger.info("Update check initiated", extra={
            'current_commit': current_commit,
            'current_branch': current_branch,
            'channel': channel,
            'target_branch': target_branch,
            'force': force
        })

        if not current_commit or current_commit == 'unknown':
            return jsonify({
                'error': 'Current commit hash not available in version.json'
            }), 500

        # Get comparison from GitHub API
        comparison, error = get_commits_comparison(current_commit, target_branch)
        fresh_sync = False

        if error:
            # Check if error indicates commit not found (repo history changed)
            if 'No commit found' in error or '404' in error or '422' in error:
                logger.info("Commit not found in remote - repo history may have changed", extra={
                    'current_commit': current_commit,
                    'error': error
                })
                # Fall back to comparing with latest remote commit
                remote_info, remote_error = get_latest_remote_commit(target_branch)
                if remote_error:
                    logger.error("Failed to get remote commit", extra={'error': remote_error})
                    return jsonify({'error': f'Failed to check for updates: {remote_error}'}), 500

                remote_commit = remote_info['sha']
                # If commits differ, update is available (fresh sync required)
                update_available = current_commit[:7] != remote_commit[:7]
                fresh_sync = update_available

                logger.info("Fresh sync check result", extra={
                    'current_commit': current_commit,
                    'remote_commit': remote_commit,
                    'update_available': update_available,
                    'fresh_sync': fresh_sync
                })

                # Fetch update notes if update is available
                update_note = None
                if update_available:
                    note_data = fetch_update_notes(target_branch)
                    if should_show_update_note(current_commit, note_data):
                        update_note = note_data.get('message')

                result = _build_update_check_result(
                    update_available, current_commit, remote_commit,
                    commits_behind=None,  # Unknown for fresh sync
                    current_branch=current_branch, target_branch=target_branch,
                    channel=channel, preview_commits=[],  # No history available
                    fresh_sync=fresh_sync, update_note=update_note
                )
                return _cache_and_return_update_result(result, cache_key, now)
            else:
                # Do NOT cache error responses - let them retry
                logger.error("GitHub API comparison failed", extra={'error': error})
                return jsonify({'error': f'Failed to check for updates: {error}'}), 500

        # Determine if update is available
        # ahead_by: how many commits the target branch is ahead of current
        # behind_by: how many commits the target branch is behind current (channel switch case)
        commits_behind = comparison.get('ahead_by', 0)
        status = comparison.get('status', 'unknown')

        # Update is available if:
        # 1. Target is ahead of us (normal update), OR
        # 2. Commits are different (channel switch - target may be behind but we want to switch)
        # Only 'identical' status means no update needed
        update_available = status != 'identical'

        logger.info("GitHub API comparison result", extra={
            'comparison_status': status,
            'ahead_by': comparison.get('ahead_by'),
            'behind_by': comparison.get('behind_by'),
            'commits_behind': commits_behind,
            'update_available': update_available
        })

        # Get latest remote commit info
        remote_info, _ = get_latest_remote_commit(target_branch)
        remote_commit = remote_info['sha'] if remote_info else comparison.get('target_commit', 'unknown')

        if remote_info:
            logger.info("Latest remote commit", extra={
                'remote_commit': remote_commit,
                'remote_message': remote_info.get('message', 'N/A')
            })

        # Fetch update notes if update is available
        update_note = None
        if update_available:
            note_data = fetch_update_notes(target_branch)
            if should_show_update_note(current_commit, note_data):
                update_note = note_data.get('message')

        result = _build_update_check_result(
            update_available, current_commit, remote_commit,
            commits_behind, current_branch, target_branch,
            channel, comparison['commits'], fresh_sync, update_note
        )
        return _cache_and_return_update_result(result, cache_key, now)

    except Exception as e:
        # Do NOT cache error responses - let them retry
        return jsonify({'error': f'Failed to check for updates: {str(e)}'}), 500

@api.route('/api/system/update', methods=['POST'])
@require_auth
@log_api_request
@handle_api_errors
def trigger_system_update():
    """Trigger system update by writing flag file.

    Writes the target branch name to the flag file so the service script
    knows which branch to update to:
    - release channel: writes 'main'
    - latest channel: writes 'staging'

    Note: Update availability is already verified by frontend via /api/system/update-check
    before this endpoint is called. No need to re-check here.
    """
    try:
        if is_home_assistant_mode():
            # Supervisor forbids an addon from updating itself directly
            # (supervisor/api/store.py: "App {slug} can't update itself!").
            # Workaround: call HA Core's update.install service, which routes
            # the request through Core so Supervisor sees Core as the caller.
            addon_info, info_error = _call_supervisor('GET', '/addons/self/info')
            if info_error:
                return jsonify({
                    'error': f'Failed to determine Home Assistant addon slug: {info_error}'
                }), 502

            addon_slug = addon_info.get('slug')
            if not addon_slug:
                return jsonify({'error': 'Failed to determine Home Assistant addon slug'}), 502

            token = os.environ.get('SUPERVISOR_TOKEN', '')
            entity_id, lookup_error = _find_addon_update_entity(addon_slug, token)
            if lookup_error:
                return jsonify({'error': lookup_error}), 502

            # Refresh HA Core's update entity so its latest_version is current.
            # Without this, update.install fails with "No update available" when
            # installed_version == latest_version (cached state right after a
            # version bump). The update_entity service is fire-and-forget — it
            # triggers a debounced coordinator refresh and returns immediately,
            # so we then poll the entity state until the new latest_version
            # propagates. (We avoid /store/reload because it kicks off
            # addon-group jobs that race with update.install.)
            try:
                requests.post(
                    f"{_HA_CORE_API_BASE}/services/homeassistant/update_entity",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"entity_id": entity_id},
                    timeout=15,
                )
            except requests.RequestException as e:
                logger.warning("Failed to refresh HA update entity (continuing)", extra={
                    'entity_id': entity_id,
                    'error': str(e),
                })

            deadline = time.monotonic() + _HA_ENTITY_POLL_TIMEOUT_SECONDS
            entity_ready = False
            while True:
                try:
                    state_resp = requests.get(
                        f"{_HA_CORE_API_BASE}/states/{entity_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=5,
                    )
                    if state_resp.ok:
                        attrs = state_resp.json().get('attributes', {})
                        installed = attrs.get('installed_version')
                        latest = attrs.get('latest_version')
                        if installed and latest and installed != latest:
                            entity_ready = True
                            break
                except requests.RequestException:
                    pass
                if time.monotonic() >= deadline:
                    break
                time.sleep(_HA_ENTITY_POLL_INTERVAL_SECONDS)

            if not entity_ready:
                return jsonify({
                    'error': 'Home Assistant has not yet refreshed the addon update state. Try again in a moment.'
                }), 502

            # HA Core's REST service call blocks until update.install
            # finishes, but installing OUR addon kills this process mid-flight
            # — so a ReadTimeout or ConnectionError after dispatch is the
            # expected outcome, not a failure. Only treat HTTP error responses
            # (which arrive before Supervisor swaps us out) as real failures.
            try:
                resp = requests.post(
                    f"{_HA_CORE_API_BASE}/services/update/install",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"entity_id": entity_id},
                    timeout=10,
                )
                resp.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.info(
                    "HA addon update dispatched; connection closed as expected during self-update",
                    extra={'entity_id': entity_id, 'error': str(e)},
                )
            except requests.RequestException as e:
                response = getattr(e, 'response', None)
                core_message = None
                if response is not None:
                    try:
                        core_message = response.json().get('message')
                    except (ValueError, AttributeError):
                        core_message = None
                logger.error("Failed to trigger HA addon update", extra={
                    'error': str(e),
                    'status_code': getattr(response, 'status_code', None),
                    'response_text': (getattr(response, 'text', None) or '')[:500],
                })
                error_message = 'Failed to trigger Home Assistant addon update'
                if core_message:
                    error_message = f'{error_message}: {core_message}'
                return jsonify({'error': error_message}), 502

            logger.info("HA addon update triggered via Core service", extra={
                'entity_id': entity_id,
            })
            return jsonify({
                'status': 'update_triggered',
                'message': 'Home Assistant addon update initiated.',
                'estimated_downtime': '2-5 minutes',
            }), 200

        # Load current version info for logging
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available'
            }), 500

        # Get target branch based on channel setting
        channel, target_branch = get_channel_branch()

        # Write update flag with target branch as content
        write_flag('update-requested', target_branch)

        logger.info("System update triggered", extra={
            'current_commit': version_info.get('commit', 'unknown'),
            'channel': channel,
            'target_branch': target_branch
        })

        return jsonify({
            'status': 'update_triggered',
            'message': 'System update initiated. Services will restart shortly.',
            'estimated_downtime': '2-5 minutes',
            'channel': channel,
            'target_branch': target_branch
        }), 200

    except Exception as e:
        return jsonify({'error': f'Failed to trigger update: {str(e)}'}), 500


@api.route('/api/system/restart', methods=['POST'])
@require_auth
@log_api_request
@handle_api_errors
def trigger_service_restart():
    """Trigger service restart for native mode or HA add-on mode."""
    if is_home_assistant_mode():
        _data, error = _call_supervisor('POST', '/addons/self/restart')
        if error:
            logger.error("Failed to restart HA add-on", extra={'error': error})
            return jsonify({'error': 'Failed to restart Home Assistant add-on'}), 502
        logger.info("Home Assistant add-on restart triggered via API")
        return jsonify({
            'status': 'restart_requested',
            'message': 'Home Assistant add-on restart initiated. Services will restart shortly.',
            'estimated_downtime': '10-30 seconds',
        }), 200

    write_flag('restart-backend')
    logger.info("Service restart triggered via API")
    return jsonify({
        'status': 'restart_requested',
        'message': 'Service restart initiated. Services will restart shortly.',
        'estimated_downtime': '10-30 seconds'
    }), 200


# =============================================================================
# Log Viewer Endpoint
# =============================================================================

@api.route('/api/system/logs', methods=['GET'])
@require_auth
@handle_api_errors
def get_system_logs():
    """Return merged, filtered log entries from all services."""
    from core.log_reader import get_logs

    service = request.args.get('service')
    search = request.args.get('search')
    limit = request.args.get('limit', type=int)

    result = get_logs(service=service, search=search, limit=limit)
    return jsonify(result)
