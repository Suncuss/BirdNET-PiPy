/**
 * Formatting helpers shared across components.
 */

/**
 * Format a byte count as a human-readable string (B, KB, MB, GB).
 * Returns "0 B" for falsy / zero input.
 */
export const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`
}

/**
 * Format elapsed media time as mm:ss ("1:07"). Returns "0:00" for negative or
 * non-finite input. This is a playback position, not wall-clock time-of-day —
 * see useTimeFormat for the latter. Shared by the audio transports.
 */
export const formatClock = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * Playback progress as a CSS-width percentage string ("42%"), clamped to 100%;
 * "0%" when duration is missing/zero. Drives both transports' playheads.
 */
export const progressPercentString = (currentTime, duration) =>
  duration ? `${Math.min(100, (currentTime / duration) * 100)}%` : '0%'

/**
 * Round a 0–1 confidence to an integer percent (0–100). Returns null for
 * null/undefined so callers can decide what to render for a missing value.
 */
export const confidencePercent = (confidence) =>
  confidence == null ? null : Math.round(confidence * 100)

/**
 * Format a 0–1 confidence as a percentage string ("94%"). Returns '' for
 * null/undefined so callers render nothing for a missing value.
 */
export const formatConfidence = (confidence) => {
  const pct = confidencePercent(confidence)
  return pct == null ? '' : `${pct}%`
}

/**
 * Tailwind text-color class for a 0–1 confidence (green → yellow → orange as it
 * falls). Treats null/undefined as 0 (lowest).
 */
export const confidenceColorClass = (confidence) => {
  const c = confidence ?? 0
  if (c >= 0.9) return 'text-green-600'
  if (c >= 0.7) return 'text-green-500'
  if (c >= 0.5) return 'text-yellow-600'
  return 'text-orange-500'
}

/**
 * Title-case a snake_case/camelCase metadata key for display
 * ("source_label" → "Source Label").
 */
export const formatMetadataKey = (key) =>
  key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (s) => s.toUpperCase())
    .trim()

/**
 * Stringify an arbitrary metadata value for display: null/undefined → '-',
 * booleans → Yes/No, objects → JSON, everything else → String().
 */
export const formatMetadataValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
