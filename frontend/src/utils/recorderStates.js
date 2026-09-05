import { formatClock } from './quietHours'

/**
 * Recorder health states — must match backend RecorderState in config/constants.py.
 */
export const RECORDER_STATES = {
  RUNNING: 'running',
  DEGRADED: 'degraded',
  STOPPED: 'stopped',
  PAUSED: 'paused',
}

/**
 * Why the recorder is paused — must match the REASON_* constants in backend
 * core/recording_schedule.py. Both are intentional states, not faults.
 */
export const PAUSE_REASONS = {
  QUIET_HOURS: 'quiet_hours',
  NO_SOURCES: 'no_sources',
}

/**
 * Hover text per reason — the sentence the short label leaves out. A reason
 * with no entry (an older or newer backend) still gets a usable pill.
 */
const PAUSE_TITLES = {
  [PAUSE_REASONS.QUIET_HOURS]: 'Recording is paused by quiet hours',
  [PAUSE_REASONS.NO_SOURCES]: 'Recording is paused — no audio source is active',
}
const PAUSE_TITLE_DEFAULT = 'Recording is paused'

/**
 * Badge text while the recorder is paused, from the `pause` fragment of the
 * recorder status broadcast. It keys off the payload rather than the reason:
 * a pause that knows when it ends shows the clock, and any other reads as a
 * plain "Audio Paused", in the same vocabulary as the healthy/degraded/
 * stopped badges. The why lives in `pausedTitle` and in the hint under the
 * source list, next to the toggle that fixes it.
 *
 * `pause.resumes_at` is station-local "YYYY-MM-DDTHH:MM"; only the clock part
 * is shown so a viewer in another timezone sees station time, matching the
 * quiet-hours Start/End inputs.
 */
export function pausedLabel(pause, formatTime) {
  const resumesAt = typeof pause?.resumes_at === 'string' ? pause.resumes_at.slice(11, 16) : ''
  const clock = formatClock(resumesAt, formatTime)
  return clock ? `Paused until ${clock}` : 'Audio Paused'
}

export function pausedTitle(pause) {
  return PAUSE_TITLES[pause?.reason] ?? PAUSE_TITLE_DEFAULT
}
