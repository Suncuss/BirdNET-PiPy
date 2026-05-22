import { ref } from 'vue'
import api from '@/services/api'
import { useLogger } from './useLogger'
import { useUnitSettings } from './useUnitSettings'
import { useTimeFormat } from './useTimeFormat'
import { ERR_UNREACHABLE } from '@/utils/errorMessages'
import { createCoalescedLoader } from '@/utils/coalescedLoader'

/**
 * Single owner of the GET /settings payload. One coalesced fetch feeds the
 * whole app; the display-preference composables (useUnitSettings,
 * useTimeFormat) own the conversion logic and are kept in sync from here.
 *
 * Shared state (singleton pattern) — all callers see the same payload.
 */
const settings = ref(null)
const loading = ref(false)
const error = ref('')

// Coalesces the one-time /settings load — see ensureLoaded().
const settingsLoad = createCoalescedLoader()

export function useSettings() {
  const logger = useLogger('useSettings')
  const unitSettings = useUnitSettings()
  const timeFormat = useTimeFormat()

  // Mirror display prefs into the composables that own the conversion logic.
  const syncDisplayPrefs = () => {
    const display = settings.value?.display || {}
    unitSettings.setUseMetricUnits(display.use_metric_units ?? true)
    timeFormat.setTimeFormat(display.time_format)
  }

  const adopt = (data) => {
    settings.value = data
    error.value = ''
    syncDisplayPrefs()
  }

  const fetchSettings = async () => {
    loading.value = true
    try {
      const { data } = await api.get('/settings')
      adopt(data)
      return true
    } catch (err) {
      // A failed load keeps the last-good payload — never destroy known state.
      logger.error('Failed to load settings', err)
      error.value = ERR_UNREACHABLE
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Ensure /settings has loaded at least once (coalesced; a failed load
   * retries on the next call).
   * @returns {Promise<boolean>}
   */
  const ensureLoaded = () => settingsLoad.ensure(fetchSettings)

  /** Force a re-fetch from the server. */
  const refresh = () => {
    settingsLoad.reset()
    return ensureLoaded()
  }

  /** Adopt a payload the caller already holds (e.g. a save response) — no fetch. */
  const setSettings = (data) => {
    // Clone — the store owns its copy and must not share the caller's reference.
    adopt(JSON.parse(JSON.stringify(data)))
    settingsLoad.markLoaded()
  }

  const resetState = () => {
    settings.value = null
    loading.value = false
    error.value = ''
    settingsLoad.reset()
  }

  return {
    settings,
    loading,
    error,
    ensureLoaded,
    refresh,
    setSettings,
    resetState
  }
}
