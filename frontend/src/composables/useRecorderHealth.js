import { ref, computed } from 'vue'
import api from '@/services/api'
import { useAuth } from './useAuth'
import { RECORDER_STATES } from '@/utils/recorderStates'

// Module-level state (shared across all components - singleton)
const recorderStatus = ref(null)

// Dismissal state - stores expiry timestamp (when to show again)
const DISMISS_STORAGE_KEY = 'birdnet_recorder_dismissed_until'
const DISMISS_DURATION_MS = 24 * 60 * 60 * 1000 // 24 hours

function loadDismissedUntil() {
  try {
    const stored = localStorage.getItem(DISMISS_STORAGE_KEY)
    return stored ? parseInt(stored, 10) : null
  } catch {
    return null
  }
}

const dismissedUntil = ref(loadDismissedUntil())

export function useRecorderHealth() {
  const { isAuthenticated } = useAuth()

  const showRecorderWarning = computed(() => {
    const state = recorderStatus.value?.state
    if (state !== RECORDER_STATES.DEGRADED && state !== RECORDER_STATES.STOPPED) return false
    if (!isAuthenticated.value) return false
    return !dismissedUntil.value || Date.now() >= dismissedUntil.value
  })

  const dismissWarning = () => {
    const expiry = Date.now() + DISMISS_DURATION_MS
    dismissedUntil.value = expiry
    localStorage.setItem(DISMISS_STORAGE_KEY, String(expiry))
  }

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
    dismissWarning,
    checkStatus
  }
}
