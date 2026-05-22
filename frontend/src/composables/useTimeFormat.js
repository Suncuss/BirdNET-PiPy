import { ref, computed } from 'vue'
import api from '@/services/api'

/**
 * Time-format display preference.
 *
 * Two-state design with browser fallback:
 *   - `explicitFormat` (singleton ref): the user's saved choice — '12h' | '24h' | null.
 *     `null` means the user has never explicitly chosen, in which case the
 *     browser's locale provides the default.
 *   - `effectiveFormat` (derived): always resolves to '12h' or '24h' for use.
 *
 * The setting only affects display, never storage — timestamps stay ISO 8601.
 */

const VALID_FORMATS = ['12h', '24h']

// Detect from browser locale. Returns '12h' or '24h'.
const detectFromBrowser = () => {
  try {
    const opts = new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).resolvedOptions()
    return opts.hour12 === false ? '24h' : '12h'
  } catch {
    return '12h'
  }
}

// Singleton state shared across components.
const explicitFormat = ref(null)
const detectedFormat = ref(detectFromBrowser())
const loading = ref(false)
const error = ref('')

// Coerce any input to a valid format or null. Tolerates the legacy "auto" value
// from settings written before we tightened the contract.
const sanitize = (value) => (VALID_FORMATS.includes(value) ? value : null)

export function useTimeFormat() {
  // Effective resolution: explicit choice wins; otherwise fall back to browser.
  const effectiveFormat = computed(() => explicitFormat.value || detectedFormat.value)
  const hour12 = computed(() => effectiveFormat.value !== '24h')
  const isExplicit = computed(() => explicitFormat.value !== null)

  /**
   * Format a timestamp/Date as a time-of-day string respecting the user's preference.
   * Defaults to `{ hour: '2-digit', minute: '2-digit' }` — pass `options` to override.
   */
  const formatTime = (input, options = {}) => {
    if (input == null) return ''
    const date = input instanceof Date ? input : new Date(input)
    // Use hourCycle (not hour12): on en-US, `hour12: false` resolves to h24,
    // which renders midnight as "24:30" instead of "00:30". h23 is consistent.
    const opts = {
      hour: '2-digit',
      minute: '2-digit',
      ...options,
      hourCycle: hour12.value ? 'h12' : 'h23'
    }
    return date.toLocaleTimeString(undefined, opts)
  }

  /**
   * Format a single hour-of-day integer (0–23) for chart x-axis labels.
   * Returns "HH:00" in 24h mode or "h AM"/"h PM" in 12h mode.
   */
  const formatHour = (hour) => {
    if (hour == null) return ''
    const h = Number(hour)
    if (!Number.isFinite(h)) return ''
    if (hour12.value === false) {
      return `${String(h).padStart(2, '0')}:00`
    }
    if (h === 0) return '12 AM'
    if (h === 12) return '12 PM'
    return h > 12 ? `${h - 12} PM` : `${h} AM`
  }

  /**
   * Format a "HH:00" chart-axis label string (as produced by `generateHourLabels()`
   * or returned by the activity API) according to the user's preference.
   * Returns the original label unchanged if it doesn't parse.
   */
  const formatHourLabel = (label) => {
    if (typeof label !== 'string') return ''
    const hour = parseInt(label.split(':')[0], 10)
    return Number.isFinite(hour) ? formatHour(hour) : label
  }

  /**
   * Save an explicit user choice to the backend. Only '12h' and '24h' are accepted.
   */
  const saveTimeFormat = async (value) => {
    if (!VALID_FORMATS.includes(value)) return false
    loading.value = true
    error.value = ''
    try {
      await api.put('/settings/time-format', { time_format: value })
      explicitFormat.value = value
      return true
    } catch (err) {
      error.value = 'Failed to save time format preference'
      console.error('Failed to save time format setting:', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Sync local state without hitting the API. Any value other than '12h'/'24h'
   * (including null, undefined, or the legacy "auto") clears the explicit choice
   * so detection takes over.
   */
  const setTimeFormat = (value) => {
    explicitFormat.value = sanitize(value)
  }

  const resetState = () => {
    explicitFormat.value = null
    detectedFormat.value = detectFromBrowser()
    loading.value = false
    error.value = ''
  }

  return {
    // The format actually used for display (always '12h' or '24h')
    timeFormat: effectiveFormat,
    explicitFormat,
    detectedFormat,
    isExplicit,
    hour12,
    loading,
    error,
    formatTime,
    formatHour,
    formatHourLabel,
    saveTimeFormat,
    setTimeFormat,
    resetState
  }
}
