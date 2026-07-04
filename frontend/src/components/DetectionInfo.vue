<template>
  <div v-if="detection">
    <!-- Weather Section -->
    <div
      v-if="hasWeatherData"
      class="mb-6"
    >
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
            <div class="text-gray-500 text-xs">
              Humidity
            </div>
            <div class="font-medium">
              {{ weatherData.humidity }}%
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs">
              Wind
            </div>
            <div class="font-medium">
              {{ formatWindSpeed(weatherData.wind) }}
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs">
              Clouds
            </div>
            <div class="font-medium">
              {{ weatherData.cloud_cover }}%
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs">
              Precip
            </div>
            <div class="font-medium">
              {{ formatPrecipitation(weatherData.precip) }}
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs">
              Pressure
            </div>
            <div class="font-medium">
              {{ formatPressure(weatherData.pressure) }}
            </div>
          </div>
        </div>
      </div>
      <div class="mt-2">
        <a
          href="https://open-meteo.com/"
          target="_blank"
          rel="noopener noreferrer"
          class="text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >Weather data from Open-Meteo</a>
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
            {{ formatMetadataKey(key) }}
          </dt>
          <dd class="text-sm font-medium text-gray-900 text-right break-all">
            {{ formatMetadataValue(value) }}
          </dd>
        </div>
      </dl>
    </div>

    <!-- No Extra Data -->
    <div
      v-if="!hasWeatherData && !hasFilteredExtraData"
      class="text-center py-6"
    >
      <p class="text-sm text-gray-500">
        No additional metadata available.
      </p>
    </div>
  </div>
</template>

<script setup>
import { toRef } from 'vue'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { useDetectionInfo } from '@/composables/useDetectionInfo'
import { formatMetadataKey, formatMetadataValue } from '@/utils/format'

const props = defineProps({
  detection: {
    type: Object,
    default: null
  }
})

const { formatTemperature, formatWindSpeed, formatPrecipitation, formatPressure } = useUnitSettings()

const {
  weatherData,
  hasWeatherData,
  weatherDescription,
  filteredExtraData,
  hasFilteredExtraData
} = useDetectionInfo(toRef(props, 'detection'))

</script>
