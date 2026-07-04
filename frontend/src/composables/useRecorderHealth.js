import { ref, computed } from 'vue'
import api from '@/services/api'
import { useAuth } from './useAuth'
import { useDismissible } from './useDismissible'
import { RECORDER_STATES } from '@/utils/recorderStates'
import { RECORDER_DISMISSED_UNTIL_KEY } from '@/utils/storageKeys'

// Module-level state (shared across all components - singleton)
const recorderStatus = ref(null)

// Recorder warning is snoozable for 24h.
const dismissal = useDismissible(RECORDER_DISMISSED_UNTIL_KEY, 24 * 60 * 60 * 1000)

export function useRecorderHealth() {
  const { isAuthenticated } = useAuth()

  const showRecorderWarning = computed(() => {
    const state = recorderStatus.value?.state
    if (state !== RECORDER_STATES.DEGRADED && state !== RECORDER_STATES.STOPPED) return false
    if (!isAuthenticated.value) return false
    return !dismissal.isDismissed()
  })

  const checkStatus = async () => {
    try {
      const { data } = await api.get('/recorder/status')
      if ('state' in data) {
        const prev = recorderStatus.value
        if (!prev || prev.state !== data.state) {
          recorderStatus.value = data
        }
      }
    } catch {
      // Silent failure — recorder health is non-critical UI
    }
  }

  return {
    showRecorderWarning,
    dismissWarning: dismissal.dismiss,
    checkStatus
  }
}
