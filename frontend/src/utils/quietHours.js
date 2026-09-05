/**
 * Quiet-hours helpers (Settings → Detection → Quiet Hours).
 *
 * The backend stores strict "HH:MM" station-local times and treats the window
 * as half-open [start, end); a start later than the end wraps past midnight.
 * These helpers only *describe* that window for display — validation is
 * server-side (PUT /api/settings/schedule).
 */

const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/
const MINUTES_PER_DAY = 24 * 60

export const QUIET_HOURS_DEFAULTS = Object.freeze({ enabled: false, start: '22:00', end: '06:00' })

/** "HH:MM" → minutes since midnight, or null when not a strict 24-hour time. */
export function parseHHMM(value) {
  const match = typeof value === 'string' ? HHMM.exec(value) : null
  return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

/** Length of the [start, end) window in minutes, wrapping past midnight. */
export function quietHoursDuration(start, end) {
  const s = parseHHMM(start)
  const e = parseHHMM(end)
  if (s == null || e == null) return null
  return (e - s + MINUTES_PER_DAY) % MINUTES_PER_DAY
}

/** Whole minutes as "8 h" / "7 h 30 min" / "45 min". */
export function formatDuration(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m} min`
  return m ? `${h} h ${m} min` : `${h} h`
}

/** Format an "HH:MM" clock time with the user's 12/24-hour preference (useTimeFormat.formatTime). */
export function formatClock(hhmm, formatTime) {
  const minutes = parseHHMM(hhmm)
  if (minutes == null) return ''
  return formatTime(new Date(1970, 0, 1, Math.floor(minutes / 60), minutes % 60))
}

/** One-line description shown under the Start/End inputs. */
export function describeQuietHours({ enabled, start, end }, formatTime) {
  if (!enabled) return 'Recording runs around the clock.'
  const duration = quietHoursDuration(start, end)
  if (duration == null) return ''
  const wraps = parseHHMM(start) > parseHHMM(end)
  const window = `${formatClock(start, formatTime)} – ${formatClock(end, formatTime)}`
  return `Pauses ${window} every day (${formatDuration(duration)}).${wraps ? ' Overnight ranges wrap past midnight.' : ''}`
}
