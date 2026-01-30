import { ref } from 'vue'

/**
 * Shared app-level status state.
 * Used to coordinate UI during initialization and restarts.
 */
const locationConfigured = ref(null) // null = checking, false = not configured, true = ready
const isRestarting = ref(false)

export function useAppStatus() {
  const setLocationConfigured = (value) => {
    locationConfigured.value = value
  }

  const setRestarting = (value) => {
    isRestarting.value = value
  }

  // Convenience: true when app is ready for normal operation
  const isReady = () => locationConfigured.value === true && !isRestarting.value

  return {
    locationConfigured,
    isRestarting,
    setLocationConfigured,
    setRestarting,
    isReady
  }
}
