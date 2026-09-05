"""Recording gate: should the recorders be capturing right now?

Two rules, composed by ``evaluate_recording_gate``:

* *no active source* — every configured source is disabled (or none exist).
  Nothing to capture, so this is a pause, not a fault: the station is in the
  state its settings ask for.
* *quiet hours* — a daily local-time window during which recording (and
  therefore detection) is paused.

Both produce a paused ``ScheduleDecision``; only quiet hours knows when it
will end, so ``resumes_at`` is None for the source rule and the UI simply
says "Paused". "No active source" wins when both apply — a resume time is a
lie when there is nothing to resume with.

The recording loop in core.main re-evaluates the gate on every tick against
the live settings, so this is a pure function of (settings, now): there is
no timer to arm or miss, a settings change applies within one tick, and
daylight-saving transitions need no special handling (a wall-clock minute
that is skipped or repeated simply is or isn't inside the window when it
happens).

Window semantics: half-open ``[start, end)`` at minute resolution. A start
later than the end (e.g. 22:00 -> 06:00) wraps past midnight. Equal times
are rejected rather than guessed at (zero-length or all-day?).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Strict 24h wall-clock time, matching what an <input type="time"> yields.
_HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")

REASON_QUIET_HOURS = "quiet_hours"
REASON_NO_SOURCES = "no_sources"

QUIET_HOURS_FIELDS = frozenset({"enabled", "start", "end"})
SCHEDULE_FIELDS = frozenset({"quiet_hours"})


@dataclass(frozen=True)
class ScheduleDecision:
    """Outcome of evaluating the schedule at one instant.

    ``resumes_at`` is a naive station-local datetime (same convention as
    ``timezone_service.local_now``) — only meaningful when ``record`` is
    False. ``error`` reports a rule that was ignored because its values are
    unusable (a hand-edited quiet-hours window); it is independent of
    ``record``, since another rule can still be pausing — the ignored rule
    is simply not the one deciding.
    """

    record: bool
    reason: str | None = None
    resumes_at: datetime | None = None
    error: str | None = None


RECORDING = ScheduleDecision(record=True)


def parse_hhmm(value: Any) -> int | None:
    """Parse a strict ``HH:MM`` string into minutes since midnight.

    Returns None for anything else (wrong type, ``7:05``, ``24:00``, seconds).
    """
    if not isinstance(value, str):
        return None
    match = _HHMM_RE.match(value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def validate_quiet_hours(quiet_hours: Any) -> str | None:
    """Validate a complete quiet_hours object. Returns an error string or None."""
    if not isinstance(quiet_hours, dict):
        return "quiet_hours must be a JSON object"
    unknown = set(quiet_hours) - QUIET_HOURS_FIELDS
    if unknown:
        return f"Unknown quiet_hours fields: {', '.join(sorted(unknown))}"
    if not isinstance(quiet_hours.get("enabled"), bool):
        return "quiet_hours.enabled must be a boolean"
    start = parse_hhmm(quiet_hours.get("start"))
    end = parse_hhmm(quiet_hours.get("end"))
    if start is None:
        return "quiet_hours.start must be a time in HH:MM (24-hour) format"
    if end is None:
        return "quiet_hours.end must be a time in HH:MM (24-hour) format"
    if start == end:
        return "quiet_hours.start and quiet_hours.end must differ"
    return None


def validate_schedule_settings(schedule: Any) -> str | None:
    """Validate a whole ``schedule`` settings section (as saved to disk)."""
    if not isinstance(schedule, dict):
        return "schedule must be a JSON object"
    unknown = set(schedule) - SCHEDULE_FIELDS
    if unknown:
        return f"Unknown schedule fields: {', '.join(sorted(unknown))}"
    if "quiet_hours" in schedule:
        return validate_quiet_hours(schedule["quiet_hours"])
    return None


def _ignored(problem: str) -> ScheduleDecision:
    """Fail open: keep recording, but say why the schedule was not applied."""
    return ScheduleDecision(record=True, error=f"quiet hours ignored: {problem}")


def _in_window(now_minutes: int, start: int, end: int) -> bool:
    if start < end:
        return start <= now_minutes < end
    # Overnight window wraps past midnight.
    return now_minutes >= start or now_minutes < end


def evaluate_schedule(settings: dict[str, Any], now: datetime) -> ScheduleDecision:
    """Decide whether recording should be active at ``now`` (station-local).

    Defensive by design: the settings loader's per-section merge lets a
    hand-edited or partial ``schedule.quiet_hours`` object reach us. An
    absent or disabled schedule is simply off (no error); anything malformed
    fails *open* (keep recording) with ``error`` set so the recording loop
    can warn, rather than silently muting or silently ignoring the station's
    intent.
    """
    schedule = settings.get("schedule")
    if schedule is None:
        return RECORDING
    if not isinstance(schedule, dict):
        return _ignored("schedule must be a JSON object")
    quiet_hours = schedule.get("quiet_hours")
    if quiet_hours is None:
        return RECORDING
    if not isinstance(quiet_hours, dict):
        return _ignored("quiet_hours must be a JSON object")

    enabled = quiet_hours.get("enabled")
    if enabled is None or enabled is False:
        return RECORDING
    if enabled is not True:
        return _ignored("quiet_hours.enabled must be a boolean")

    # Lenient on unknown keys here (they're harmless on disk); strict at the
    # API boundary via validate_quiet_hours.
    start = parse_hhmm(quiet_hours.get("start"))
    end = parse_hhmm(quiet_hours.get("end"))
    if start is None or end is None or start == end:
        return _ignored("start and end must be distinct HH:MM times")

    now_minutes = now.hour * 60 + now.minute
    if not _in_window(now_minutes, start, end):
        return RECORDING

    # Inside the window: recording resumes at the next occurrence of `end`,
    # which is later today unless the window has already wrapped past it.
    resumes_at = now.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if resumes_at <= now:
        resumes_at += timedelta(days=1)
    return ScheduleDecision(
        record=False, reason=REASON_QUIET_HOURS, resumes_at=resumes_at
    )


def enabled_sources(audio_settings: dict[str, Any]) -> list[dict]:
    """Configured sources the station wants recorded.

    A source with no ``enabled`` key predates the toggle and counts as on.
    """
    return [s for s in audio_settings.get("sources", []) if s.get("enabled", True)]


def evaluate_recording_gate(settings: dict[str, Any], now: datetime) -> ScheduleDecision:
    """Compose both pause rules into one decision (see module docstring).

    The schedule is evaluated even when there is no active source, so its
    ``error`` (a malformed but enabled quiet-hours window) keeps being
    reported rather than going quiet until a source comes back.
    """
    decision = evaluate_schedule(settings, now)
    if enabled_sources(settings.get("audio", {})):
        return decision
    return ScheduleDecision(
        record=False, reason=REASON_NO_SOURCES, error=decision.error
    )
