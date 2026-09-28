import { ref, computed } from 'vue'

/**
 * Shared state (singleton pattern) - all components share the same refs.
 * This ensures that when one component updates unit settings, all others see the change.
 */
// Default to metric - birds don't care about freedom units
const useMetricUnits = ref(true)

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

  /**
   * Set unit preference directly (used when syncing from settings)
   * @param {boolean} value - True for metric, false for imperial
   */
  const setUseMetricUnits = (value) => {
    useMetricUnits.value = value
  }

  return {
    // State
    useMetricUnits,

    // Conversion functions (raw values)
    convertWindSpeed,
    convertPrecipitation,
    convertPressure,

    // Format functions (value + unit string)
    formatTemperature,

    // Unit labels
    windSpeedUnit,
    precipitationUnit,
    pressureUnit,

    // Methods
    setUseMetricUnits
  }
}
