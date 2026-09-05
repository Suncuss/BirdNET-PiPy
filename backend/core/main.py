import glob
import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import requests

from config.constants import RecorderState, RecordingMode
from config.settings import (
    ANALYSIS_CHUNK_LENGTH,
    API_HOST,
    API_PORT,
    BIRDNET_SERVER_ENDPOINT,
    BIRDWEATHER_ID,
    EXTRACTED_AUDIO_DIR,
    LAT,
    LOCATION_CONFIGURED,
    LON,
    RECORDING_DIR,
    RECORDING_LENGTH,
    SAMPLE_RATE,
    SPECTROGRAM_DIR,
    TIMEZONE,
)
from core.audio_manager import BaseRecorder, create_recorder
from core.bird_name_utils import get_localized_common_name, get_spectrogram_common_name
from core.birdweather_service import get_birdweather_service
from core.db import DatabaseManager
from core.fd_diagnostics import log_fd_exhaustion_if_needed
from core.internal_auth import INTERNAL_SECRET_HEADER, get_or_create_internal_secret
from core.logging_config import get_logger, setup_logging
from core.media_ownership import (
    KIND_AUDIO,
    KIND_SPECTROGRAM,
    PART_SUFFIX,
    DetectionMissingError,
    publish_media_file,
    with_media_suffix,
)
from core.notification_service import get_notification_service
from core.recording_schedule import (
    REASON_NO_SOURCES,
    REASON_QUIET_HOURS,
    ScheduleDecision,
    enabled_sources,
    evaluate_recording_gate,
)
from core.runtime_config import get_runtime_settings, resolve_source_label
from core.spectrogram import generate_spectrogram
from core.storage_manager import storage_monitor_loop
from core.timezone_service import get_timezone_str, local_now
from core.utils import (
    build_detection_filenames,
    extract_audio_segment,
    sanitize_source_label,
    sanitize_url,
    select_audio_chunks,
)
from core.weather_service import get_weather_service
from version import DISPLAY_NAME, __version__

# Configuration constants
MIN_RECORDING_DURATION = 5.0  # Minimum acceptable recording duration in seconds
FILE_SCAN_INTERVAL = 2.0      # How often to scan for new recordings (seconds)
BROADCAST_TIMEOUT = 5         # WebSocket broadcast request timeout (seconds)
BIRDNET_REQUEST_TIMEOUT = 60  # BirdNet analysis request timeout (seconds) - increased for warmup
BIRDNET_MAX_RETRIES = 5       # Max retries for BirdNet connection errors
BIRDNET_RETRY_BASE_DELAY = 2  # Base delay for exponential backoff (seconds)
RECORDING_THREAD_SHUTDOWN_TIMEOUT = 10  # Max wait for recording thread (seconds)
PROCESSING_THREAD_SHUTDOWN_TIMEOUT = 5  # Max wait for processing thread (seconds)
DEGRADED_FAILURE_THRESHOLD = 3  # Consecutive failures before 'degraded' state
STATUS_REFRESH_INTERVAL = 60   # Re-broadcast recorder status every N seconds
AUDIO_STATUS_NOTIFY_COOLDOWN = 600  # Min seconds between repeat audio-degradation alerts

# (pausing, resuming) log lines per gate reason (core.recording_schedule),
# paired so a new reason can't get half its wording.
_PAUSE_LOG = {
    REASON_QUIET_HOURS: ("⏸️ Quiet hours started, pausing recording",
                         "▶️ Quiet hours ended, resuming recording"),
    REASON_NO_SOURCES: ("⏸️ No active audio source, pausing recording",
                        "▶️ Audio source enabled, resuming recording"),
}
_PAUSE_LOG_DEFAULT = ("⏸️ Pausing recording", "▶️ Resuming recording")


class ModelServiceUnavailableError(RuntimeError):
    """Raised when a recording could not reach the model service at all."""

# Setup logging
setup_logging('main')
logger = get_logger(__name__)

# Initialize the database manager
db_manager = DatabaseManager()

# Global flag to signal all threads to stop
stop_flag = threading.Event()

# Ensure directories exist
for dir in [RECORDING_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR]:
    os.makedirs(dir, exist_ok=True)

def _get_recording_length(audio_settings: dict[str, Any]) -> float:
    return audio_settings.get('recording_length', RECORDING_LENGTH)


def _get_analysis_chunk_length() -> float:
    return get_runtime_settings().get('audio', {}).get('recording_chunk_length', ANALYSIS_CHUNK_LENGTH)


def _get_recorder_signature(audio_settings: dict[str, Any]) -> tuple:
    """Hash the enabled sources to detect config changes."""
    enabled = enabled_sources(audio_settings)
    source_tuples = tuple(
        (s.get('id'), s.get('type'), s.get('url', ''), s.get('device', ''))
        for s in enabled
    )
    return (source_tuples, _get_recording_length(audio_settings))


def _is_valid_timezone(tz: str | None) -> bool:
    if not tz:
        return False
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _is_location_ready(settings: dict[str, Any]) -> bool:
    location = settings.get('location', {})
    configured = location.get('configured', LOCATION_CONFIGURED)
    timezone = location.get('timezone', TIMEZONE)
    return bool(configured) and _is_valid_timezone(timezone)


def setup_recorder(source: dict, recording_length: float, thread_logger) -> BaseRecorder:
    """Create and configure audio recorder for a single source.

    Args:
        source: Source entry dict with type, device/url, label, etc.
        recording_length: Recording chunk duration in seconds
        thread_logger: Logger instance for this thread

    Returns:
        Configured recorder instance
    """
    source_type = source.get('type', 'pulseaudio')
    source_id = source.get('id', 'unknown')
    output_dir = os.path.join(RECORDING_DIR, source_id)
    os.makedirs(output_dir, exist_ok=True)

    if source_type == RecordingMode.PULSEAUDIO:
        device = source.get('device', 'default')
        thread_logger.info("🔴 Starting PulseAudio recording", extra={
            'source_id': source_id,
            'pulseaudio_source': device,
            'chunk_duration': recording_length,
            'output_dir': output_dir
        })
        return create_recorder(
            recording_mode=RecordingMode.PULSEAUDIO,
            chunk_duration=recording_length,
            output_dir=output_dir,
            target_sample_rate=SAMPLE_RATE,
            source_name=device,
        )
    elif source_type == RecordingMode.RTSP:
        rtsp_url = source.get('url')
        thread_logger.info("🔴 Starting RTSP stream recording", extra={
            'source_id': source_id,
            'rtsp_url': sanitize_url(rtsp_url),
            'chunk_duration': recording_length,
            'output_dir': output_dir
        })
        return create_recorder(
            recording_mode=RecordingMode.RTSP,
            chunk_duration=recording_length,
            output_dir=output_dir,
            target_sample_rate=SAMPLE_RATE,
            rtsp_url=rtsp_url,
        )
    else:
        raise ValueError(f"Unknown source type: {source_type}")

def _get_recorder_state(recorder: BaseRecorder | None, healthy: bool) -> str:
    """Derive simple state string for change detection.

    Args:
        recorder: Recorder instance or None
        healthy: Cached result of recorder.is_healthy()
    """
    if recorder is None or not healthy:
        return RecorderState.STOPPED
    if recorder.consecutive_failures >= DEGRADED_FAILURE_THRESHOLD:
        return RecorderState.DEGRADED
    return RecorderState.RUNNING


def _get_aggregate_state(
    recorders: dict[str, BaseRecorder],
    health_cache: dict[str, bool] | None = None,
) -> str:
    """Derive aggregate state across all recorders.

    Returns 'running' if all healthy, 'degraded' if any unhealthy,
    'stopped' if none running.

    Args:
        recorders: source_id → recorder mapping
        health_cache: pre-computed {source_id: is_healthy} to avoid redundant calls
    """
    if not recorders:
        return RecorderState.STOPPED

    any_running = False
    any_degraded = False

    for sid, recorder in recorders.items():
        healthy = health_cache[sid] if health_cache else recorder.is_healthy()
        if healthy:
            any_running = True
            if recorder.consecutive_failures >= DEGRADED_FAILURE_THRESHOLD:
                any_degraded = True
        else:
            any_degraded = True

    if not any_running:
        return RecorderState.STOPPED
    if any_degraded:
        return RecorderState.DEGRADED
    return RecorderState.RUNNING


def broadcast_recorder_status(
    state: str, recorders: dict[str, BaseRecorder],
    sources: list[dict], thread_logger,
    health_cache: dict[str, bool] | None = None,
    pause: dict | None = None,
) -> bool:
    """Send recorder health status to API for WebSocket broadcast.

    ``pause`` (see _pause_payload) marks an intentional stop: sources
    without a recorder then report 'paused' rather than 'stopped' so the
    UI can tell quiet hours from a fault.

    Returns True if broadcast succeeded, False otherwise.
    """
    try:
        per_source = {}
        for source in sources:
            sid = source.get('id', '')
            recorder = recorders.get(sid)
            if recorder:
                healthy = health_cache[sid] if health_cache else recorder.is_healthy()
                per_source[sid] = {
                    'label': source.get('label', sid),
                    'type': source.get('type', ''),
                    'state': _get_recorder_state(recorder, healthy),
                    **recorder.get_health_status(healthy=healthy),
                }
            else:
                per_source[sid] = {
                    'label': source.get('label', sid),
                    'type': source.get('type', ''),
                    'state': RecorderState.PAUSED if pause else RecorderState.STOPPED,
                    **BaseRecorder.default_health_status(),
                }

        status_data = {
            'state': state,
            'sources': per_source,
            'pause': pause,
        }
        resp = requests.post(
            f'http://{API_HOST}:{API_PORT}/api/broadcast/recorder-status',
            json=status_data,
            headers={INTERNAL_SECRET_HEADER: get_or_create_internal_secret()},
            timeout=BROADCAST_TIMEOUT
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log_fd_exhaustion_if_needed(e, thread_logger, 'recorder_status_broadcast')
        thread_logger.debug("Failed to broadcast recorder status", extra={
            'error': str(e)
        })
        return False


def _collect_problem_sources(
    recorders: dict[str, BaseRecorder],
    sources: list[dict],
    health_cache: dict[str, bool],
) -> list[dict]:
    """List sources whose recorder is not in the running state.

    Each entry carries the human label, current per-source state, and the
    most recent error message — enough for a useful notification body.
    """
    problems = []
    for source in sources:
        sid = source.get('id', '')
        label = source.get('label', sid)
        recorder = recorders.get(sid)
        if recorder is None:
            problems.append({'label': label, 'state': RecorderState.STOPPED, 'error': ''})
            continue
        healthy = health_cache.get(sid, recorder.is_healthy())
        state = _get_recorder_state(recorder, healthy)
        if state != RecorderState.RUNNING:
            problems.append({
                'label': label,
                'state': state,
                'error': recorder.last_error_message,
            })
    return problems


@dataclass
class _AudioAlertTracker:
    """Episode bookkeeping for audio-status notifications.

    Lives for the recorder thread's lifetime. ``decide`` debounces flapping
    so a persistently-broken stream alerts once (not every tick) while still
    letting a degraded→stopped escalation through.
    """

    active: bool = False  # an unresolved problem alert was sent
    problem_state: str | None = None
    last_problem_time: float = 0.0

    def decide(self, current_state: str, prev_state: str | None) -> str | None:
        """Classify a state transition, mutating episode state when it
        warrants an alert. Returns 'problem', 'recovery', or None.
        """
        if prev_state is None or current_state == prev_state:
            return None

        if current_state in (RecorderState.DEGRADED, RecorderState.STOPPED):
            escalated = (
                current_state == RecorderState.STOPPED
                and self.problem_state == RecorderState.DEGRADED
            )
            new_episode = (
                not self.active
                and (time.time() - self.last_problem_time)
                >= AUDIO_STATUS_NOTIFY_COOLDOWN
            )
            if not (escalated or new_episode):
                return None
            self.active = True
            self.problem_state = current_state
            self.last_problem_time = time.time()
            return 'problem'

        if self.active:
            self.active = False
            self.problem_state = None
            return 'recovery'
        return None


def _maybe_notify_audio_status(
    current_state: str,
    prev_state: str | None,
    recorders: dict[str, BaseRecorder],
    sources: list[dict],
    health_cache: dict[str, bool],
    tracker: _AudioAlertTracker,
    thread_logger,
) -> None:
    """Surface audio pipeline degradation/recovery via the notification service.

    No-op unless the user has both notification URLs configured and the
    ``audio_status`` toggle enabled (both enforced inside the service).
    """
    if prev_state is None or current_state == prev_state:
        return

    notif_service = get_notification_service(db_manager)
    if notif_service is None:
        return

    kind = tracker.decide(current_state, prev_state)
    if kind is None:
        return

    problem_sources = (
        _collect_problem_sources(recorders, sources, health_cache)
        if kind == 'problem' else []
    )
    notif_service.notify_audio_status({
        'state': current_state,
        'previous_state': prev_state,
        'problem_sources': problem_sources,
    })
    thread_logger.info("Audio status alert queued", extra={
        'kind': kind, 'state': current_state, 'previous_state': prev_state,
    })


def _pause_payload(decision: ScheduleDecision) -> dict | None:
    """Status-broadcast fragment for an intentional pause; None when recording.

    ``resumes_at`` is station-local naive ISO (minutes), matching the
    convention detection timestamps already use.
    """
    if decision.record:
        return None
    resumes_at = decision.resumes_at
    return {
        'reason': decision.reason,
        'resumes_at': resumes_at.isoformat(timespec='minutes') if resumes_at else None,
    }


def _log_schedule_error(
    decision: ScheduleDecision, previous_error: str | None, thread_logger,
) -> str | None:
    """Warn once when an enabled schedule is being ignored, and once when it
    becomes usable again. Returns the error to carry into the next tick."""
    if decision.error != previous_error:
        if decision.error:
            # The gate composes both rules, so an invalid schedule can coincide
            # with a pause from another rule (no enabled source). Don't promise
            # recording continues when it isn't.
            thread_logger.warning(
                "Recording schedule invalid, schedule ignored"
                + (", recording continues" if decision.record else ""),
                extra={'error': decision.error})
        else:
            thread_logger.info("Recording schedule valid again")
    return decision.error


def continuous_audio_recording(thread_logger):
    """Continuous audio recording from one or more audio sources.

    This thread manages recorders (FFmpeg processes) for all enabled sources.
    It does not scan for files or queue them - that's the processing thread's job.
    """
    recorders: dict[str, BaseRecorder] = {}  # source_id → recorder
    current_signature: tuple | None = None
    last_broadcast_state: str | None = None
    last_broadcast_pause: dict | None = None
    last_broadcast_time: float = 0.0
    last_notify_state: str | None = None
    audio_alert_tracker = _AudioAlertTracker()
    # Why the gate has recording stopped (None = recording); not a fault.
    pause_reason: str | None = None
    schedule_error: str | None = None

    def _start_all(audio_settings, sig):
        nonlocal current_signature
        enabled = enabled_sources(audio_settings)
        recording_length = _get_recording_length(audio_settings)
        for source in enabled:
            sid = source.get('id', 'unknown')
            try:
                rec = setup_recorder(source, recording_length, thread_logger)
                rec.start()
                recorders[sid] = rec
            except ValueError as e:
                thread_logger.error("Recorder configuration invalid",
                                    extra={'source_id': sid, 'error': str(e)})
        current_signature = sig

    def _stop_all():
        for sid, rec in recorders.items():
            try:
                rec.stop()
            except Exception as e:
                thread_logger.debug(f"Error stopping recorder {sid}: {e}")
        recorders.clear()

    def _apply_gate(decision: ScheduleDecision) -> None:
        """Enter or leave the paused state, logging once per transition.

        ``pause_reason`` is the whole pause state: None means recording. A
        reason change while already paused (quiet hours starting after the
        last source was disabled, say) logs too — otherwise the resume line
        would name a rule that is no longer the one in force.
        """
        nonlocal pause_reason
        if decision.record:
            if pause_reason:
                thread_logger.info(
                    _PAUSE_LOG.get(pause_reason, _PAUSE_LOG_DEFAULT)[1])
                pause_reason = None
            return
        if pause_reason != decision.reason:
            thread_logger.info(
                _PAUSE_LOG.get(decision.reason, _PAUSE_LOG_DEFAULT)[0],
                extra=_pause_payload(decision))
            pause_reason = decision.reason
        if recorders:
            _stop_all()

    try:
        # Initialize recorders on startup (unless the schedule says not to)
        try:
            initial_settings = get_runtime_settings()
            initial_audio_settings = initial_settings.get('audio', {})
            initial_decision = evaluate_recording_gate(initial_settings, local_now())
            _apply_gate(initial_decision)
            if initial_decision.record:
                _start_all(initial_audio_settings, _get_recorder_signature(initial_audio_settings))
        except Exception as e:
            log_fd_exhaustion_if_needed(e, thread_logger, 'recording_loop_init')
            thread_logger.error("Recording loop error", extra={'error': str(e)}, exc_info=True)
            time.sleep(1)

        while not stop_flag.is_set():
            try:
                settings = get_runtime_settings()
                audio_settings = settings.get('audio', {})
                new_signature = _get_recorder_signature(audio_settings)
                decision = evaluate_recording_gate(settings, local_now())
                schedule_error = _log_schedule_error(decision, schedule_error, thread_logger)
                _apply_gate(decision)
                paused = not decision.record

                if paused:
                    pass  # recorders are down on purpose; nothing to (re)start
                elif not recorders:
                    _start_all(audio_settings, new_signature)
                elif new_signature != current_signature:
                    thread_logger.info("🔴 Audio settings changed, reloading recorders")
                    _stop_all()
                    _start_all(audio_settings, new_signature)

                # Check recorder health (once per recorder) and restart unhealthy ones
                health_cache = {
                    sid: recorder.is_healthy()
                    for sid, recorder in recorders.items()
                }
                for sid, healthy in health_cache.items():
                    if not healthy:
                        thread_logger.warning(f"Recorder {sid} unhealthy, restarting...")
                        recorders[sid].restart()
                        health_cache[sid] = recorders[sid].is_healthy()

                # Broadcast status on state change or periodic refresh
                active_sources = enabled_sources(audio_settings)
                pause_info = _pause_payload(decision)
                current_state = (
                    RecorderState.PAUSED if paused
                    else _get_aggregate_state(recorders, health_cache)
                )
                # Pause metadata counts as state: editing the window's end
                # while paused must not leave a stale resumes_at until the
                # next periodic refresh.
                state_changed = (
                    current_state != last_broadcast_state
                    or pause_info != last_broadcast_pause
                )
                refresh_due = (time.time() - last_broadcast_time) >= STATUS_REFRESH_INTERVAL
                if state_changed or refresh_due:
                    ok = broadcast_recorder_status(
                        current_state, recorders, active_sources, thread_logger,
                        health_cache, pause=pause_info,
                    )
                    if ok:
                        last_broadcast_state = current_state
                        last_broadcast_pause = pause_info
                        last_broadcast_time = time.time()

                # Runs even if the broadcast above failed, so a flaky API
                # socket can't mask audio degradation. A pause (quiet hours
                # or no active source) is invisible to the notifier: it is
                # not a problem, and by not advancing last_notify_state
                # through it, the first state after resuming is judged
                # against the state before the pause — an unresolved
                # degradation still gets its recovery alert, and a stream
                # that died during the pause still alerts.
                if not paused:
                    _maybe_notify_audio_status(
                        current_state, last_notify_state, recorders,
                        active_sources, health_cache, audio_alert_tracker,
                        thread_logger,
                    )
                    last_notify_state = current_state

                time.sleep(FILE_SCAN_INTERVAL)

            except ValueError as e:
                thread_logger.error("Recorder configuration invalid", extra={'error': str(e)})
                time.sleep(2)
            except Exception as e:
                log_fd_exhaustion_if_needed(e, thread_logger, 'recording_loop_main')
                thread_logger.error("Recording loop error", extra={
                    'error': str(e)
                }, exc_info=True)
                time.sleep(1)

    finally:
        thread_logger.info("🔴 Stopping audio recording")
        _stop_all()

def extract_detection_audio(detection: dict[str, Any], input_file_path: str) -> tuple[str, int]:
    """Extract audio segment for detection and convert to MP3.

    The frontend's analysis-window bar mirrors this start/end math from the
    detection row alone (see select_audio_chunks NOTE) — keep them in step.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file

    Returns:
        Tuple of (path to the MP3 file, size in bytes)
    """
    analysis_chunk_length = _get_analysis_chunk_length()
    step_seconds = detection.get('step_seconds', analysis_chunk_length)
    audio_segments_indices = select_audio_chunks(
        detection['chunk_index'], detection['total_chunks'])
    start_time = audio_segments_indices[0] * step_seconds
    end_time = audio_segments_indices[1] * step_seconds + analysis_chunk_length

    mp3_path = os.path.join(
        EXTRACTED_AUDIO_DIR, detection['bird_song_file_name']).replace('.wav', '.mp3')

    normalize = get_runtime_settings().get('playback', {}).get('normalize', False)
    # Atomic publication: ffmpeg writes the temp name (explicit -f, since
    # .part hides the container), then the final name is claimed without
    # ever exposing a partial file under it.
    part_path = mp3_path + PART_SUFFIX
    extract_audio_segment(input_file_path, part_path, start_time, end_time,
                          normalize=normalize, output_format='mp3')
    size = publish_media_file(part_path, mp3_path)
    return mp3_path, size


def create_detection_spectrogram(detection: dict[str, Any], input_file_path: str) -> tuple[str, int]:
    """Generate spectrogram image for detection.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file

    Returns:
        Tuple of (path to the spectrogram image, size in bytes)
    """
    analysis_chunk_length = _get_analysis_chunk_length()
    step_seconds = detection.get('step_seconds', analysis_chunk_length)
    spectrogram_path = os.path.join(SPECTROGRAM_DIR, detection['spectrogram_file_name'])

    display_name = get_spectrogram_common_name(
        detection.get('scientific_name'),
        detection.get('common_name'),
    )
    title = f"{display_name} ({detection['confidence']:.2f}) - {detection['timestamp']}"
    start_time = step_seconds * detection['chunk_index']
    end_time = start_time + analysis_chunk_length

    # Atomic publication (Pillow's format comes from the explicit 'WEBP'
    # arg, so the .part suffix is fine as a write target).
    part_path = spectrogram_path + PART_SUFFIX
    generate_spectrogram(input_file_path, part_path, title,
                        start_time=start_time, end_time=end_time)
    size = publish_media_file(part_path, spectrogram_path)
    return spectrogram_path, size


def save_detection_to_db(detection: dict[str, Any]) -> None:
    """Insert detection record into database.

    Stamps the new row's id back onto the detection dict so downstream
    consumers (notification permalinks) can reference it.

    Args:
        detection: Detection dictionary from BirdNet analysis
    """
    detection['id'] = db_manager.insert_detection({
        'timestamp': detection['timestamp'],
        'group_timestamp': detection['group_timestamp'],
        'scientific_name': detection['scientific_name'],
        'common_name': detection['common_name'],
        'confidence': detection['confidence'],
        'latitude': detection['latitude'],
        'longitude': detection['longitude'],
        'cutoff': detection['cutoff'],
        'sensitivity': detection['sensitivity'],
        'overlap': detection['overlap'],
        'extra': detection.get('extra', {}),
        'audio_source': detection.get('audio_source')
    })


def broadcast_detection(detection: dict[str, Any], thread_logger) -> None:
    """Send detection to WebSocket clients via API.

    Args:
        detection: Detection dictionary from BirdNet analysis
        thread_logger: Logger instance for this thread
    """
    try:
        display_name = get_localized_common_name(
            detection.get('scientific_name'),
            detection.get('common_name'),
        )
        detection_data = {
            'timestamp': detection['timestamp'],
            'common_name': detection['common_name'],
            'display_common_name': display_name,
            'scientific_name': detection['scientific_name'],
            'confidence': detection['confidence'],
            'bird_song_file_name': detection['bird_song_file_name'].replace('.wav', '.mp3'),
            'spectrogram_file_name': detection['spectrogram_file_name'],
            'audio_source': detection.get('audio_source')
        }
        requests.post(
            f'http://{API_HOST}:{API_PORT}/api/broadcast/detection',
            json=detection_data,
            headers={INTERNAL_SECRET_HEADER: get_or_create_internal_secret()},
            timeout=BROADCAST_TIMEOUT
        )
        thread_logger.debug("Detection broadcasted via WebSocket", extra={
            'species': detection['common_name']
        })
    except Exception as e:
        log_fd_exhaustion_if_needed(e, thread_logger, 'detection_broadcast', extra={
            'species': detection['common_name'],
        })
        thread_logger.warning("Failed to broadcast detection", extra={
            'species': detection['common_name'],
            'error': str(e)
        })


def handle_detection(detection: dict[str, Any], input_file_path: str, thread_logger) -> None:
    """Process a single bird detection: save to DB, create media, broadcast.

    Row-first creation (media-ownership design): the detection row is
    committed before any file exists, media files are published under
    id+nonce names, and ownership is recorded before anything downstream
    sees the detection. A crash mid-way leaves either a file-less row
    (normal) or a nonce-named orphan reconciliation can repair — never an
    unrecognizable state.

    Args:
        detection: Detection dictionary from BirdNet analysis
        input_file_path: Path to the source audio file
        thread_logger: Logger instance for this thread
    """
    thread_logger.info("🐦 Bird detected", extra={
        'species': detection['common_name'],
        'confidence': round(detection['confidence'] * 100),
        'time': detection['timestamp'].split('T')[1].split('.')[0]
    })

    runtime_settings = get_runtime_settings()
    location = runtime_settings.get('location', {})
    lat = location.get('latitude', LAT)
    lon = location.get('longitude', LON)
    location_configured = location.get('configured', LOCATION_CONFIGURED)

    # Attach weather data if location is configured (explicit None check for
    # 0-coordinate support). Before the save so it lands in the stored row.
    if location_configured and lat is not None and lon is not None:
        weather_service = get_weather_service(lat, lon)
        if weather_service:
            weather_data = weather_service.get_current_weather()
            if weather_data:
                extra = detection.get('extra', {})
                if isinstance(extra, str):
                    try:
                        extra = json.loads(extra)
                    except json.JSONDecodeError:
                        extra = {}
                extra['weather'] = weather_data
                detection['extra'] = extra
                thread_logger.debug("Weather attached to detection", extra={
                    'species': detection['common_name'],
                    'temp': weather_data.get('temp')
                })

    thread_logger.debug("Saving detection to database", extra={
        'species': detection['common_name'],
        'scientific_name': detection['scientific_name']
    })
    save_detection_to_db(detection)

    # The row's id + persisted nonce name the media files; every consumer
    # from here on (broadcast, notifications, API reads) sees these names.
    nonce = db_manager.get_media_nonce(detection['id'])
    detection['bird_song_file_name'] = with_media_suffix(
        detection['bird_song_file_name'].replace('.wav', '.mp3'),
        detection['id'], nonce)
    detection['spectrogram_file_name'] = with_media_suffix(
        detection['spectrogram_file_name'], detection['id'], nonce)

    audio_path, audio_bytes = extract_detection_audio(detection, input_file_path)
    spectrogram_path, spectrogram_bytes = create_detection_spectrogram(
        detection, input_file_path)

    try:
        db_manager.record_detection_media(detection['id'], [
            {'filename': detection['bird_song_file_name'],
             'kind': KIND_AUDIO, 'rank': 0, 'bytes': audio_bytes},
            {'filename': detection['spectrogram_file_name'],
             'kind': KIND_SPECTROGRAM, 'rank': 0, 'bytes': spectrogram_bytes},
        ])
    except DetectionMissingError:
        # A delete won the race between the insert and here — leave no
        # ownership residue and no unowned files behind.
        thread_logger.info("Detection deleted mid-creation; removing media", extra={
            'detection_id': detection['id']})
        for path in (audio_path, spectrogram_path):
            try:
                os.remove(path)
            except OSError:
                pass
        return

    # Upload to BirdWeather if configured
    birdweather_id = runtime_settings.get('birdweather', {}).get('id', BIRDWEATHER_ID)
    if birdweather_id:
        bw_service = get_birdweather_service()
        if bw_service:
            analysis_chunk_length = _get_analysis_chunk_length()
            step_seconds = detection.get('step_seconds', analysis_chunk_length)
            bw_start_time = step_seconds * detection['chunk_index']
            bw_end_time = bw_start_time + analysis_chunk_length
            bw_service.publish(detection, input_file_path, bw_start_time, bw_end_time)

    broadcast_detection(detection, thread_logger)

    # Send notification if configured (service reads config from file per-detection)
    notif_service = get_notification_service(db_manager)
    if notif_service:
        notif_service.notify(detection)

def is_valid_recording(file_path: str, thread_logger) -> bool:
    """Check if a recording file is valid (meets minimum duration).

    Args:
        file_path: Path to WAV file to validate
        thread_logger: Logger instance for this thread

    Returns:
        True if file is valid, False if too short (and should be deleted)
    """
    try:
        file_size = os.path.getsize(file_path)
        # Calculate duration: mono 16-bit = 2 bytes per sample
        actual_duration = file_size / (SAMPLE_RATE * 2)
        min_acceptable_size = SAMPLE_RATE * 2 * MIN_RECORDING_DURATION

        if file_size >= min_acceptable_size:
            return True
        else:
            thread_logger.warning("Recording too short, removing", extra={
                'file': os.path.basename(file_path),
                'size_bytes': file_size,
                'duration_seconds': round(actual_duration, 3),
                'expected_min_duration': MIN_RECORDING_DURATION
            })
            return False

    except OSError as e:
        log_fd_exhaustion_if_needed(e, thread_logger, 'validate_recording', extra={
            'file': os.path.basename(file_path),
        })
        thread_logger.error("Failed to validate file", extra={
            'file': os.path.basename(file_path),
            'error': str(e)
        })
        return False


def remove_recording_from_queue(file_path: str, file_name: str, thread_logger) -> None:
    """Remove a recording after it has been accepted for processing.

    The recording directory is the processing queue. If post-analysis work
    fails, leaving the same WAV in place causes an infinite retry loop.
    """
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log_fd_exhaustion_if_needed(e, thread_logger, 'remove_recording', extra={
            'file': file_name,
        })
        thread_logger.warning("Failed to delete processed file", extra={
            'file': file_name,
            'error': str(e)
        })


def _collect_wav_files() -> list[tuple[str, str | None]]:
    """Collect WAV files from root recording dir and source subdirs.

    Returns list of (file_path, source_id) tuples sorted by filename
    (timestamp-based) for chronological processing across sources.
    """
    candidates: list[tuple[str, str | None]] = []

    # Legacy: root-level files (no source, from before multi-source)
    for f in glob.glob(os.path.join(RECORDING_DIR, "*.wav")):
        candidates.append((f, None))

    # Source subdirs: RECORDING_DIR/source_*/
    for subdir in glob.glob(os.path.join(RECORDING_DIR, "source_*")):
        if not os.path.isdir(subdir):
            continue
        source_id = os.path.basename(subdir)
        for f in glob.glob(os.path.join(subdir, "*.wav")):
            candidates.append((f, source_id))

    # Sort by filename for chronological order across sources
    candidates.sort(key=lambda x: os.path.basename(x[0]))
    return candidates


def process_audio_files():
    """Processing thread: scans directory for .wav files and processes them.

    The filesystem IS the queue - no in-memory queue needed.
    Files are deleted after a model response is accepted so a failed
    post-analysis step cannot retry the same WAV indefinitely. Network-level
    model outages leave recordings queued until analysis is reachable again.
    Collects from root dir (legacy) and per-source subdirs.
    """
    thread_logger = get_logger(f"{__name__}.processing")
    thread_logger.info("Processing thread started")

    while not stop_flag.is_set():
        try:
            candidates = _collect_wav_files()

            for file_path, audio_source in candidates:
                if stop_flag.is_set():
                    break

                file_name = os.path.basename(file_path)

                # Validate file size/duration
                if not is_valid_recording(file_path, thread_logger):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    continue

                thread_logger.info("🔄 Processing recording", extra={
                    'file': file_name,
                    'audio_source': audio_source
                })

                detections = []
                processing_failed = False
                preserve_recording = False
                try:
                    # Process the audio file via BirdNet
                    detections = process_audio_file(file_path)
                    if detections:
                        # Resolve and sanitize source label once per file
                        source_label = ''
                        if audio_source:
                            raw_label = resolve_source_label(audio_source)
                            source_label = sanitize_source_label(raw_label)

                        for detection in detections:
                            try:
                                detection['audio_source'] = audio_source
                                # Store source label in extra for filename reconstruction
                                if source_label:
                                    extra = detection.get('extra', {})
                                    extra['source_label'] = source_label
                                    detection['extra'] = extra
                                # Recompute filenames with source label suffix
                                if audio_source:
                                    fnames = build_detection_filenames(
                                        detection['common_name'],
                                        detection['confidence'],
                                        detection['timestamp'],
                                        audio_extension='wav',
                                        audio_source=source_label or None
                                    )
                                    detection['bird_song_file_name'] = fnames['audio_filename']
                                    detection['spectrogram_file_name'] = fnames['spectrogram_filename']
                                handle_detection(detection, file_path, thread_logger)
                            except Exception as e:
                                processing_failed = True
                                log_fd_exhaustion_if_needed(e, thread_logger, 'detection_processing', extra={
                                    'file': file_name,
                                    'species': detection.get('common_name', 'unknown'),
                                })
                                thread_logger.error("Detection processing failed", extra={
                                    'file': file_name,
                                    'species': detection.get('common_name', 'unknown'),
                                    'error': str(e)
                                }, exc_info=True)

                except ModelServiceUnavailableError as e:
                    processing_failed = True
                    preserve_recording = True
                    thread_logger.warning(
                        "Model service unavailable; recording remains queued",
                        extra={'file': file_name, 'error': str(e)},
                    )
                except Exception as e:
                    processing_failed = True
                    log_fd_exhaustion_if_needed(e, thread_logger, 'recording_processing', extra={
                        'file': file_name,
                    })
                    thread_logger.error("Recording processing failed", extra={
                        'file': file_name,
                        'error': str(e)
                    }, exc_info=True)
                finally:
                    thread_logger.debug("Audio file processed", extra={
                        'file': file_name,
                        'detections': len(detections) if detections else 0,
                        'processing_failed': processing_failed,
                        'preserved_for_retry': preserve_recording,
                    })
                    # A network-level model outage means analysis never happened,
                    # so keep the WAV in the filesystem queue. Post-analysis
                    # failures still consume it to avoid infinite retries.
                    if not preserve_recording:
                        remove_recording_from_queue(
                            file_path, file_name, thread_logger
                        )

                if preserve_recording:
                    time.sleep(FILE_SCAN_INTERVAL)
                    break

            # Sleep before next scan (only if no files were found)
            if not candidates:
                time.sleep(FILE_SCAN_INTERVAL)

        except Exception as e:
            log_fd_exhaustion_if_needed(e, thread_logger, 'processing_loop')
            thread_logger.error("Processing error", extra={
                'error': str(e)
            }, exc_info=True)
            time.sleep(1)

def process_audio_file(audio_file_path: str) -> list[dict[str, Any]]:
    """Send audio file to BirdNet service for analysis.

    Includes retry logic with exponential backoff for connection errors,
    which can occur during server startup (warmup period). Raises
    ModelServiceUnavailableError when analysis never reached the service so
    the filesystem queue can preserve the recording.
    """
    payload = {'audio_file_path': audio_file_path}
    file_name = os.path.basename(audio_file_path)

    for attempt in range(BIRDNET_MAX_RETRIES):
        try:
            response = requests.post(
                BIRDNET_SERVER_ENDPOINT,
                json=payload,
                timeout=BIRDNET_REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                detections = response.json()
                logger.debug("BirdNet analysis complete", extra={
                    'file': file_name,
                    'detections_count': len(detections)
                })
                return detections
            else:
                logger.error("BirdNet service error", extra={
                    'file': file_name,
                    'status_code': response.status_code,
                    'response': response.text[:200]
                })
                return []

        except requests.exceptions.ConnectionError as e:
            log_fd_exhaustion_if_needed(e, logger, 'birdnet_request', extra={
                'file': file_name,
            })
            # Server not ready yet (still warming up) - retry with backoff
            if attempt < BIRDNET_MAX_RETRIES - 1:
                wait_time = BIRDNET_RETRY_BASE_DELAY ** (attempt + 1)  # 2, 4, 8, 16, 32 seconds
                logger.warning("BirdNet service not ready, retrying", extra={
                    'file': file_name,
                    'attempt': attempt + 1,
                    'max_retries': BIRDNET_MAX_RETRIES,
                    'retry_in': wait_time
                })
                time.sleep(wait_time)
            else:
                logger.error("BirdNet service unavailable after retries", extra={
                    'file': file_name,
                    'attempts': BIRDNET_MAX_RETRIES,
                    'error': str(e)
                })
                raise ModelServiceUnavailableError(
                    "BirdNet service unavailable after connection retries"
                ) from e

        except requests.exceptions.Timeout as e:
            log_fd_exhaustion_if_needed(e, logger, 'birdnet_request', extra={
                'file': file_name,
            })
            # Request timed out - don't retry, server is likely overloaded
            logger.error("BirdNet service request timed out", extra={
                'file': file_name,
                'timeout': BIRDNET_REQUEST_TIMEOUT,
                'error': str(e)
            })
            raise ModelServiceUnavailableError(
                "BirdNet service request timed out"
            ) from e

        except requests.RequestException as e:
            log_fd_exhaustion_if_needed(e, logger, 'birdnet_request', extra={
                'file': file_name,
            })
            logger.error("BirdNet service request failed", extra={
                'file': file_name,
                'error': str(e)
            })
            raise ModelServiceUnavailableError(
                "BirdNet service request failed"
            ) from e

        except Exception as e:
            log_fd_exhaustion_if_needed(e, logger, 'birdnet_request', extra={
                'file': file_name,
            })
            logger.error("Unexpected error calling BirdNet service", extra={
                'file': file_name,
                'error': str(e)
            }, exc_info=True)
            return []

    return []  # Should not reach here, but safety fallback

def shutdown():
    logger.info("Shutdown initiated")
    stop_flag.set()  # Signal all threads to stop

    # Threads may not exist if shutdown occurs before they're created
    # (e.g., signal received while waiting for location configuration)
    # Also handle the race where thread is created but not yet started
    if 'recording_thread' in globals():
        try:
            recording_thread.join(timeout=RECORDING_THREAD_SHUTDOWN_TIMEOUT)
            if recording_thread.is_alive():
                logger.warning("Recording thread did not stop cleanly")
        except RuntimeError:
            pass  # Thread was created but not started yet

    if 'processing_thread' in globals():
        try:
            processing_thread.join(timeout=PROCESSING_THREAD_SHUTDOWN_TIMEOUT)
            if processing_thread.is_alive():
                logger.warning("Processing thread did not stop cleanly")
        except RuntimeError:
            pass  # Thread was created but not started yet

    logger.info("Shutdown complete")

def signal_handler(signum, _):
    """Handle shutdown signals gracefully"""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal, initiating graceful shutdown")
    shutdown()

if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)  # Docker stop
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C

    startup_settings = get_runtime_settings()
    startup_audio = startup_settings.get('audio', {})

    logger.info(f"🎵 {DISPLAY_NAME} v{__version__} starting", extra={
        'recording_dir': RECORDING_DIR,
        'recording_length': startup_audio.get('recording_length', 9),
        'analysis_chunk_length': startup_audio.get('recording_chunk_length', 3),
        'timezone': get_timezone_str()
    })

    # Wait for location and timezone to be configured before starting detection.
    # This loop now polls runtime settings, so detection can start without restarting the container.
    waiting_message_logged = False
    while not stop_flag.is_set():
        current_settings = get_runtime_settings()
        if _is_location_ready(current_settings):
            break

        if not waiting_message_logged:
            location = current_settings.get('location', {})
            if not location.get('configured', False):
                logger.info("⏳ Location not configured. Waiting for user to set location in the web interface...")
            else:
                logger.info("⏳ Timezone not configured. Please re-save your location in the web interface...")
            waiting_message_logged = True
        time.sleep(1)

    if stop_flag.is_set():
        logger.info("Shutdown received while waiting for location/timezone configuration")
        import sys
        sys.exit(0)

    # Start weather service early to fetch timezone from API
    # (singleton - detection processing will reuse this instance)
    location = get_runtime_settings().get('location', {})
    lat = location.get('latitude', LAT)
    lon = location.get('longitude', LON)
    if lat is not None and lon is not None:
        get_weather_service(lat, lon)

    # One-time live-media index build BEFORE any local writer exists
    # (media-ownership design: the build holds the writer lock for its
    # whole duration; deferred under the maintenance lease if the API
    # container's bulk importer is running). Function-local import:
    # media_frontier imports storage_manager.
    from core.media_frontier import ensure_live_media_index
    ensure_live_media_index(db_manager)

    # Start the recording thread
    recording_logger = get_logger(f"{__name__}.recording")
    recording_thread = threading.Thread(
        target=continuous_audio_recording,
        args=(recording_logger,),
        name="RecordingThread"
    )
    recording_thread.start()
    logger.info("Recording thread started")

    # Start the processing thread
    processing_thread = threading.Thread(target=process_audio_files, name="ProcessingThread")
    processing_thread.start()
    logger.info("Processing thread started")

    # Start the storage monitor thread
    storage_thread = threading.Thread(
        target=storage_monitor_loop,
        args=(stop_flag, db_manager),
        name="StorageThread"
    )
    storage_thread.start()
    logger.info("Storage monitor thread started")

    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        # Signal handler will handle this
        pass
