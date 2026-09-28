import { ref } from 'vue'

/**
 * Shared app-level status state: whether the station's location is set up
 * (gates the setup wizard) and its display name.
 */
const locationConfigured = ref(null) // null = checking, false = not configured, true = ready
const stationName = ref('')

export function useAppStatus() {
  const setLocationConfigured = (value) => {
    locationConfigured.value = value
  }

  const setStationName = (value) => {
    stationName.value = value || ''
  }

  return {
    locationConfigured,
    stationName,
    setLocationConfigured,
    setStationName
  }
}
