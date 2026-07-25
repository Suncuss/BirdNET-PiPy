"""Update/version plumbing: GitHub comparisons, HA supervisor calls, flags.

Everything the system/update endpoints need that is not HTTP-request shaped:
the GitHub API client and commit comparisons, remote UPDATE_NOTES fetching and
targeting, version.json / HA source-commit loading, the Home Assistant
Supervisor + Core API helpers, and the flag files that ask the host to act.
The routes in core/routes/system.py translate these into responses and own the
update-check response cache.
"""
import json
import os
import uuid

import requests

from config.settings import BASE_DIR
from core.logging_config import get_logger
from core.timezone_service import local_now
from version import DISPLAY_NAME, __version__

logger = get_logger(__name__)

# Random identity for this API process, reported by /api/system/version so the
# frontend can tell a freshly restarted server from the old one still shutting
# down (reachability alone can't distinguish them on slow hardware). Relies on
# the single-gunicorn-worker deployment (docker-compose --workers 1, which
# SocketIO already requires); multiple workers would each mint their own id.
BOOT_ID = str(uuid.uuid4())

_HA_CORE_API_BASE = "http://supervisor/core/api"


def _call_supervisor(method, path, timeout=10):
    """Call Home Assistant Supervisor API. Returns (data, error_message)."""
    token = os.environ.get('SUPERVISOR_TOKEN', '')
    try:
        resp = requests.request(
            method,
            f"http://supervisor{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
        return body.get('data', {}), None
    except requests.RequestException as e:
        return None, str(e)


def _find_addon_update_entity(addon_slug, token):
    """Find this addon's update.* entity_id via HA Core states.

    HA Core registers an UpdateEntity per addon with entity_picture set to
    /api/hassio/addons/<full_slug>/icon — a unique key per addon. Returns
    (entity_id, error_message).
    """
    try:
        resp = requests.get(
            f"{_HA_CORE_API_BASE}/states",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        states = resp.json()
    except requests.RequestException as e:
        return None, f'Failed to fetch HA Core states: {e}'
    except ValueError as e:
        return None, f'Invalid response from HA Core states: {e}'

    icon_url = f"/api/hassio/addons/{addon_slug}/icon"
    for state in states:
        entity_id = state.get('entity_id', '')
        if not entity_id.startswith('update.'):
            continue
        if state.get('attributes', {}).get('entity_picture') == icon_url:
            return entity_id, None

    return None, f'Could not find update entity for addon {addon_slug}'


def write_flag(flag_name, content=None):
    """Write flag file to trigger host action.

    Args:
        flag_name: Name of the flag file (e.g., 'restart-backend', 'update-requested')
        content: Optional content to write. If None, writes timestamp.
                 For update-requested, content should be the target branch name.
    """
    flag_dir = os.path.join(BASE_DIR, 'data', 'flags')
    os.makedirs(flag_dir, exist_ok=True)
    flag_file = os.path.join(flag_dir, flag_name)
    with open(flag_file, 'w') as f:
        f.write(content if content else local_now().isoformat())
    logger.debug("Flag file written", extra={
        'flag': flag_name,
        'content': content,
        'path': flag_file
    })


# Written by install.sh / birdnet-service.sh as the update pipeline advances
# (pending -> in_progress -> success|failed) and surfaced via
# /api/system/version so the frontend's restart poll can tell a failed update
# (old code restarted) from one still in progress.
UPDATE_STATUS_FLAG = 'update-status'


def _update_status_path():
    return os.path.join(BASE_DIR, 'data', 'flags', UPDATE_STATUS_FLAG)


def read_update_status():
    """Return the update-status flag content, or None if absent/unreadable.

    ValueError covers UnicodeDecodeError from a file corrupted mid-write
    (e.g. power loss on an SD card): an advisory field must never take the
    whole /system/version response down with it. The read is capped — valid
    statuses are single short words.
    """
    try:
        with open(_update_status_path()) as f:
            return f.read(64).strip() or None
    except (OSError, ValueError):
        return None


def reset_update_status():
    """Best-effort reset to 'pending' before dispatching a new update.

    Without this, a 'failed' left by a previous attempt would be visible to
    the frontend's poll before install.sh overwrites it, producing an instant
    false "update failed" report. Removes-then-recreates because the existing
    file may be root-owned (install.sh writes as root) while the flags dir
    itself is user-writable. Never raises: the status is advisory and must
    not block an update dispatch.

    Returns the status read back from disk after the reset (normally
    'pending'). The trigger response forwards it so the frontend has a
    server-confirmed post-reset value: any 'failed' it sees later must have
    been written by this attempt, not a stale survivor.
    """
    path = _update_status_path()
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove stale update-status flag", extra={
            'path': path, 'error': str(e)
        })
    try:
        write_flag(UPDATE_STATUS_FLAG, 'pending')
    except OSError as e:
        logger.warning("Could not write pending update-status flag", extra={
            'path': path, 'error': str(e)
        })
    return read_update_status()

# GitHub API configuration
GITHUB_OWNER = "Suncuss"
GITHUB_REPO = "BirdNET-PiPy"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
HA_SOURCE_COMMIT_ENV = "BIRDNET_PIPY_SOURCE_COMMIT"
HA_SOURCE_COMMIT_FILE = os.path.join(BASE_DIR, "birdnet_pipy_source_commit.txt")


def load_version_info():
    """Load version information from version.json"""
    version_file = os.path.join(BASE_DIR, 'data', 'version.json')

    if not os.path.exists(version_file):
        logger.warning("version.json not found", extra={'path': version_file})
        return None

    try:
        with open(version_file) as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load version.json", extra={'error': str(e)})
        return None


def load_ha_source_commit():
    """Load BirdNET-PiPy source commit baked into HA add-on image."""
    commit_from_env = os.environ.get(HA_SOURCE_COMMIT_ENV, "").strip()
    if commit_from_env:
        return commit_from_env

    if not os.path.exists(HA_SOURCE_COMMIT_FILE):
        return None

    try:
        with open(HA_SOURCE_COMMIT_FILE) as f:
            commit = f.read().strip()
            return commit or None
    except Exception as e:
        logger.warning("Failed to load Home Assistant source commit", extra={
            'path': HA_SOURCE_COMMIT_FILE,
            'error': str(e),
        })
        return None


def call_github_api(endpoint, timeout=10):
    """Call GitHub API and return JSON response"""
    url = f"{GITHUB_API_BASE}/{endpoint}"
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': f'{DISPLAY_NAME}/{__version__}'
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.Timeout:
        return None, "GitHub API request timed out"
    except requests.exceptions.RequestException as e:
        return None, f"GitHub API error: {str(e)}"

def get_commits_comparison(base_commit, target_branch='main'):
    """Compare local commit with remote branch using GitHub API"""
    # NOTE: GitHub API requires three dots (...), not two dots (..)
    # Two-dot syntax causes 404 error
    endpoint = f"compare/{base_commit}...{target_branch}"
    data, error = call_github_api(endpoint)
    if error:
        return None, error

    return {
        'ahead_by': data.get('ahead_by', 0),
        'behind_by': data.get('behind_by', 0),
        'status': data.get('status', 'unknown'),
        'commits': [
            {
                'hash': c['sha'][:7],
                'message': c['commit']['message'].split('\n')[0],
                'date': c['commit']['committer']['date']
            }
            for c in data.get('commits', [])[:10]  # Limit to 10 commits
        ],
        'target_commit': data.get('commits', [{}])[-1].get('sha', '')[:7] if data.get('commits') else ''
    }, None

def get_latest_remote_commit(branch='main'):
    """Get the latest commit on the remote branch"""
    endpoint = f"commits/{branch}"
    data, error = call_github_api(endpoint)

    if error:
        return None, error

    return {
        'sha': data.get('sha', '')[:7],
        'message': data['commit']['message'].split('\n')[0],
        'date': data['commit']['committer']['date']
    }, None

def fetch_update_notes(branch='main'):
    """Fetch deployment/UPDATE_NOTES.json from remote repository

    Returns:
        dict: Update notes with 'message' and 'show_to_versions_before' fields
        None: If file not found or empty/invalid
    """
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{branch}/deployment/UPDATE_NOTES.json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            logger.debug("UPDATE_NOTES.json not found in remote repository")
            return None
        response.raise_for_status()

        data = response.json()
        message = data.get('message')

        # Return None if no message (same behavior as before)
        if not message:
            return None

        return {
            'message': message,
            'show_to_versions_before': data.get('show_to_versions_before')
        }
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch UPDATE_NOTES.json", extra={'error': str(e)})
        return None
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in UPDATE_NOTES.json")
        return None

def should_show_update_note(current_commit, note_data):
    """Determine if update note should be shown based on version targeting

    Args:
        current_commit: User's current commit hash
        note_data: Dict with 'message' and 'show_to_versions_before'

    Returns:
        bool: True if note should be shown
    """
    if not note_data or not note_data.get('message'):
        return False

    target_commit = note_data.get('show_to_versions_before')

    # If no version targeting, always show
    if not target_commit:
        return True

    # Compare commits: GET /compare/{current_commit}...{target_commit}
    # GitHub API semantics:
    #   - status 'ahead': target is ahead of current (user is on older version)
    #   - status 'behind': target is behind current (user is on newer version)
    #   - status 'identical': commits are the same
    #   - status 'diverged': branches diverged, can't determine order
    #   - ahead_by: how many commits target is ahead of current
    comparison, error = get_commits_comparison(current_commit, target_commit)

    if error:
        # If comparison fails (e.g., commit not found), show the message to be safe
        logger.warning("Could not compare commits for update note", extra={
            'current_commit': current_commit,
            'target_commit': target_commit,
            'error': error
        })
        return True

    status = comparison.get('status', '')
    ahead_by = comparison.get('ahead_by', 0)

    # Handle diverged case: can't determine order, show to be safe
    if status == 'diverged':
        return True

    # Show if user is strictly BEFORE the target (target is ahead of user)
    # 'identical' means user is AT the target commit - don't show (they already have it)
    return status == 'ahead' or ahead_by > 0
