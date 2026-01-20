import { ref, computed } from 'vue'
import api from '@/services/api'

/**
 * Shared state (singleton pattern) - all components share the same refs.
 * This ensures that when one component updates unit settings, all others see the change.
 */
// Default to metric - birds don't care about freedom units
const useMetricUnits = ref(true)
const loading = ref(false)
const error = ref('')

/**
 * Composable for unit settings and conversions.
 * Handles metric/imperial unit preferences for weather display.
 *
 * Data is always stored in SI/metric units (°C, km/h, mm, hPa).
 * Conversion happens only at display time based on user preference.
 */
export function useUnitSettings() {
  // Conversion functions - return raw values (no units attached)
  // Note: We coerce to Number to handle string values from JSON
  const convertTemperature = (celsius) => {
    if (celsius == null) return null
    const value = Number(celsius)
    if (useMetricUnits.value) return value
    return (value * 9 / 5) + 32
  }

  const convertWindSpeed = (kmh) => {
    if (kmh == null) return null
    const value = Number(kmh)
    if (useMetricUnits.value) return value
    return value * 0.621371
  }

  const convertPrecipitation = (mm) => {
    if (mm == null) return null
    const value = Number(mm)
    if (useMetricUnits.value) return value
    return value * 0.0393701
  }

  const convertPressure = (hPa) => {
    if (hPa == null) return null
    const value = Number(hPa)
    if (useMetricUnits.value) return value
    return value * 0.02953
  }

  // Unit labels
  const temperatureUnit = computed(() => useMetricUnits.value ? '°C' : '°F')
  const windSpeedUnit = computed(() => useMetricUnits.value ? 'km/h' : 'mph')
  const precipitationUnit = computed(() => useMetricUnits.value ? 'mm' : 'in')
  const pressureUnit = computed(() => useMetricUnits.value ? 'hPa' : 'inHg')

  // Format functions - return value with unit string
  const formatTemperature = (celsius) => {
    const value = convertTemperature(celsius)
    if (value == null) return '-'
    return `${value.toFixed(1)}${temperatureUnit.value}`
  }

  const formatWindSpeed = (kmh) => {
    const value = convertWindSpeed(kmh)
    if (value == null) return '-'
    return `${value.toFixed(1)} ${windSpeedUnit.value}`
  }

  const formatPrecipitation = (mm) => {
    const value = convertPrecipitation(mm)
    if (value == null) return '-'
    const precision = useMetricUnits.value ? 1 : 2
    return `${value.toFixed(precision)} ${precipitationUnit.value}`
  }

  const formatPressure = (hPa) => {
    const value = convertPressure(hPa)
    if (value == null) return '-'
    const precision = useMetricUnits.value ? 1 : 2
    return `${value.toFixed(precision)} ${pressureUnit.value}`
  }

  /**
   * Load unit setting from API settings
   */
  const loadUnitSetting = async () => {
    try {
      const { data } = await api.get('/settings')
      useMetricUnits.value = data.display?.use_metric_units ?? true
    } catch (err) {
      console.error('Failed to load unit settings:', err)
      // Keep default (metric) on error
    }
  }

  /**
   * Toggle and save unit preference (no restart needed)
   * @returns {Promise<boolean>} - True if save was successful
   */
  const toggleUnits = async () => {
    const newValue = !useMetricUnits.value
    loading.value = true
    error.value = ''

    try {
      await api.put('/settings/units', { use_metric_units: newValue })
      useMetricUnits.value = newValue
      return true
    } catch (err) {
      error.value = 'Failed to save unit preference'
      console.error('Failed to save unit setting:', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Set unit preference directly (used when syncing from settings)
   * @param {boolean} value - True for metric, false for imperial
   */
  const setUseMetricUnits = (value) => {
    useMetricUnits.value = value
  }

  /**
   * Reset state (for testing)
   */
  const resetState = () => {
    useMetricUnits.value = true
    loading.value = false
    error.value = ''
  }

  return {
    // State
    useMetricUnits,
    loading,
    error,

    // Conversion functions (raw values)
    convertTemperature,
    convertWindSpeed,
    convertPrecipitation,
    convertPressure,

    // Format functions (value + unit string)
    formatTemperature,
    formatWindSpeed,
    formatPrecipitation,
    formatPressure,

    // Unit labels
    temperatureUnit,
    windSpeedUnit,
    precipitationUnit,
    pressureUnit,

    // Methods
    loadUnitSetting,
    toggleUnits,
    setUseMetricUnits,
    resetState
  }
}
