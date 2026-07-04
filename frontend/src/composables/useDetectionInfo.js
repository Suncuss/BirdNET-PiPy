import { computed, toValue } from 'vue'

// Weather codes from WMO (World Meteorological Organization)
const weatherCodeMap = {
  0: { desc: 'Clear sky', icon: '☀️' },
  1: { desc: 'Mainly clear', icon: '🌤️' },
  2: { desc: 'Partly cloudy', icon: '⛅' },
  3: { desc: 'Overcast', icon: '☁️' },
  45: { desc: 'Fog', icon: '🌫️' },
  48: { desc: 'Depositing rime fog', icon: '🌫️' },
  51: { desc: 'Light drizzle', icon: '🌧️' },
  53: { desc: 'Moderate drizzle', icon: '🌧️' },
  55: { desc: 'Dense drizzle', icon: '🌧️' },
  56: { desc: 'Light freezing drizzle', icon: '🌨️' },
  57: { desc: 'Dense freezing drizzle', icon: '🌨️' },
  61: { desc: 'Slight rain', icon: '🌧️' },
  63: { desc: 'Moderate rain', icon: '🌧️' },
  65: { desc: 'Heavy rain', icon: '🌧️' },
  66: { desc: 'Light freezing rain', icon: '🌨️' },
  67: { desc: 'Heavy freezing rain', icon: '🌨️' },
  71: { desc: 'Slight snow', icon: '❄️' },
  73: { desc: 'Moderate snow', icon: '❄️' },
  75: { desc: 'Heavy snow', icon: '❄️' },
  77: { desc: 'Snow grains', icon: '❄️' },
  80: { desc: 'Slight rain showers', icon: '🌦️' },
  81: { desc: 'Moderate rain showers', icon: '🌦️' },
  82: { desc: 'Violent rain showers', icon: '🌦️' },
  85: { desc: 'Slight snow showers', icon: '🌨️' },
  86: { desc: 'Heavy snow showers', icon: '🌨️' },
  95: { desc: 'Thunderstorm', icon: '⛈️' },
  96: { desc: 'Thunderstorm with slight hail', icon: '⛈️' },
  99: { desc: 'Thunderstorm with heavy hail', icon: '⛈️' }
}

/**
 * Parses a detection's `extra` blob into weather + general metadata.
 * Accepts a ref, getter, or plain detection object so it can drive both the
 * inline detail panel and the table's popup from the same logic.
 */
export function useDetectionInfo(detection) {
  const extraData = computed(() => {
    const d = toValue(detection)
    if (!d?.extra) return {}
    // Handle both string (JSON) and object
    if (typeof d.extra === 'string') {
      try {
        return JSON.parse(d.extra)
      } catch {
        return {}
      }
    }
    return d.extra
  })

  // Extract weather data from extra (handle both 'weather' and 'Weather' keys)
  const weatherData = computed(() => {
    const extra = extraData.value
    if (!extra) return null
    const weatherKey = Object.keys(extra).find(k => k.toLowerCase() === 'weather')
    if (!weatherKey) return null
    const weather = extra[weatherKey]
    // If weather is a string (double-encoded JSON), parse it
    if (typeof weather === 'string') {
      try {
        return JSON.parse(weather)
      } catch {
        return null
      }
    }
    return weather
  })

  const hasWeatherData = computed(() => weatherData.value !== null)

  const weatherDescription = computed(() => {
    if (!weatherData.value) return { desc: 'Unknown', icon: '❓' }
    return weatherCodeMap[weatherData.value.code] || { desc: 'Unknown', icon: '❓' }
  })

  // Filter out weather from general metadata display (case-insensitive)
  const filteredExtraData = computed(() => {
    if (!extraData.value) return {}
    const result = {}
    for (const [key, value] of Object.entries(extraData.value)) {
      if (key.toLowerCase() !== 'weather') {
        result[key] = value
      }
    }
    return result
  })

  const hasFilteredExtraData = computed(() => Object.keys(filteredExtraData.value).length > 0)

  return {
    weatherData,
    hasWeatherData,
    weatherDescription,
    filteredExtraData,
    hasFilteredExtraData
  }
}
