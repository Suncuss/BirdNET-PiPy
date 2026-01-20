<template>
  <Transition
    enter-active-class="transition ease-out duration-200"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition ease-in duration-150"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="isVisible"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      @click.self="close"
    >
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full max-h-[85vh] overflow-hidden">
        <!-- Header -->
        <div class="px-5 py-4 border-b border-gray-200 bg-gray-50">
          <h3 class="text-lg font-semibold text-gray-900">Detection Info</h3>
          <p v-if="detection" class="text-sm text-gray-500 mt-0.5">
            {{ detection.common_name }}
          </p>
        </div>

        <!-- Content -->
        <div class="px-5 py-4 overflow-y-auto max-h-[60vh]">
          <template v-if="detection">
            <!-- Weather Section -->
            <div v-if="hasWeatherData" class="mb-6">
              <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Weather Conditions
              </h4>
              <div class="bg-gray-50 rounded-lg p-4">
                <!-- Weather Summary Row -->
                <div class="flex items-center gap-3 mb-4">
                  <span class="text-3xl">{{ weatherDescription.icon }}</span>
                  <div>
                    <div class="text-lg font-medium text-gray-900">
                      {{ formatTemperature(weatherData.temp) }}
                    </div>
                    <div class="text-sm text-gray-600">
                      {{ weatherDescription.desc }}
                    </div>
                  </div>
                </div>

                <!-- Weather Details Grid -->
                <div class="grid grid-cols-3 gap-x-4 gap-y-2 text-sm">
                  <div>
                    <div class="text-gray-500 text-xs">Humidity</div>
                    <div class="font-medium">{{ weatherData.humidity }}%</div>
                  </div>
                  <div>
                    <div class="text-gray-500 text-xs">Wind</div>
                    <div class="font-medium">{{ formatWindSpeed(weatherData.wind) }}</div>
                  </div>
                  <div>
                    <div class="text-gray-500 text-xs">Clouds</div>
                    <div class="font-medium">{{ weatherData.cloud_cover }}%</div>
                  </div>
                  <div>
                    <div class="text-gray-500 text-xs">Precip</div>
                    <div class="font-medium">{{ formatPrecipitation(weatherData.precip) }}</div>
                  </div>
                  <div>
                    <div class="text-gray-500 text-xs">Pressure</div>
                    <div class="font-medium">{{ formatPressure(weatherData.pressure) }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Other Metadata Section -->
            <div v-if="hasFilteredExtraData">
              <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Detection Metadata
              </h4>
              <dl class="space-y-3">
                <div
                  v-for="(value, key) in filteredExtraData"
                  :key="key"
                  class="flex justify-between items-start gap-4"
                >
                  <dt class="text-sm text-gray-600 flex-shrink-0">
                    {{ formatKey(key) }}
                  </dt>
                  <dd class="text-sm font-medium text-gray-900 text-right break-all">
                    {{ formatValue(value) }}
                  </dd>
                </div>
              </dl>
            </div>

            <!-- No Extra Data -->
            <div v-if="!hasWeatherData && !hasFilteredExtraData" class="text-center py-6">
              <p class="text-sm text-gray-500">No additional metadata available.</p>
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-gray-200 bg-gray-50">
          <button
            @click="close"
            class="w-full px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
          >
            Close
          </button>
        </div>

        <!-- Close button -->
        <button
          @click="close"
          class="absolute top-3 right-3 p-1 rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          title="Close"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed } from 'vue'
import { useUnitSettings } from '@/composables/useUnitSettings'

const { formatTemperature, formatWindSpeed, formatPrecipitation, formatPressure } = useUnitSettings()

const props = defineProps({
  isVisible: {
    type: Boolean,
    default: false
  },
  detection: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close'])

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

const close = () => {
  emit('close')
}

const extraData = computed(() => {
  if (!props.detection?.extra) return {}
  // Handle both string (JSON) and object
  if (typeof props.detection.extra === 'string') {
    try {
      return JSON.parse(props.detection.extra)
    } catch {
      return {}
    }
  }
  return props.detection.extra
})

// Extract weather data from extra (handle both 'weather' and 'Weather' keys)
const weatherData = computed(() => {
  const extra = extraData.value
  if (!extra) return null
  // Check for weather key case-insensitively
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

const hasWeatherData = computed(() => {
  return weatherData.value !== null
})

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

const hasFilteredExtraData = computed(() => {
  return Object.keys(filteredExtraData.value).length > 0
})

const formatKey = (key) => {
  // Convert snake_case or camelCase to Title Case
  return key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, str => str.toUpperCase())
    .trim()
}

const formatValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>
