<template>
  <div
    v-if="isVisible"
    class="fixed inset-0 z-50 overflow-y-auto"
  >
    <!-- Backdrop -->
    <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <!-- Error message (shared across steps) -->
        <div
          v-if="errorMessage"
          class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm"
        >
          {{ errorMessage }}
        </div>

        <div v-if="step === 1">
          <!-- Header -->
          <div class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
              <svg
                class="h-6 w-6 text-green-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"
                />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">
              Set Your Location
            </h2>
            <p class="mt-2 text-sm text-gray-600">
              BirdNET uses your location to filter bird species likely in your area and to retrieve local weather information.
            </p>
          </div>

          <!-- Address Search -->
          <div class="mb-4">
            <div class="flex gap-2">
              <input
                v-model="searchQuery"
                type="text"
                placeholder="City, address, or place name..."
                class="flex-1 rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50 pl-3"
                @keyup.enter="searchAddress"
              >
              <button
                :disabled="searching || !searchQuery.trim()"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300"
                @click="searchAddress"
              >
                <svg
                  v-if="!searching"
                  class="h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
                  />
                </svg>
                <svg
                  v-else
                  class="animate-spin h-5 w-5"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    class="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    stroke-width="4"
                  />
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
              </button>
            </div>

            <!-- Search Results -->
            <div
              v-if="searchResults.length > 0"
              class="mt-2 border rounded-md shadow-sm max-h-40 overflow-y-auto"
            >
              <button
                v-for="result in searchResults"
                :key="result.place_id"
                class="w-full text-left px-3 py-2 hover:bg-gray-100 border-b last:border-b-0 text-sm"
                @click="selectSearchResult(result)"
              >
                {{ result.display_name }}
              </button>
            </div>
          </div>

          <!-- Divider -->
          <div class="relative my-4">
            <div class="absolute inset-0 flex items-center">
              <div class="w-full border-t border-gray-300" />
            </div>
            <div class="relative flex justify-center text-sm">
              <span class="bg-white px-2 text-gray-500">or enter coordinates manually</span>
            </div>
          </div>

          <!-- Manual Entry -->
          <div class="grid grid-cols-2 gap-4 mb-6">
            <div>
              <label
                for="latitude"
                class="block text-sm font-medium text-gray-700 mb-1"
              >Latitude</label>
              <input
                id="latitude"
                v-model.number="latitude"
                type="text"
                inputmode="decimal"
                placeholder="e.g., 42.47"
                class="w-full rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50 pl-3"
                @input="limitDecimals"
              >
            </div>
            <div>
              <label
                for="longitude"
                class="block text-sm font-medium text-gray-700 mb-1"
              >Longitude</label>
              <input
                id="longitude"
                v-model.number="longitude"
                type="text"
                inputmode="decimal"
                placeholder="e.g., -76.45"
                class="w-full rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50 pl-3"
                @input="limitDecimals"
              >
            </div>
          </div>

          <!-- Selected Location Display -->
          <div
            v-if="latitude !== null && longitude !== null"
            class="mb-4 p-3 bg-green-50 border border-green-200 rounded-md"
          >
            <p class="text-sm text-green-800">
              <span class="font-medium">Selected:</span> {{ latitude.toFixed(2) }}, {{ longitude.toFixed(2) }}
              <span
                v-if="locationName"
                class="block text-xs text-green-600 mt-1"
              >{{ locationName }}</span>
            </p>
          </div>

          <!-- Next Button -->
          <button
            :disabled="!isValidLocation"
            class="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
            @click="errorMessage = ''; step = 2"
          >
            Next
          </button>
        </div>

        <div v-if="step === 2">
          <!-- Header -->
          <div class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
              <svg
                class="h-6 w-6 text-green-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z"
                />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">
              Audio Source
            </h2>
            <p class="mt-2 text-sm text-gray-600">
              How will BirdNET listen for birds?
            </p>
          </div>

          <!-- Audio source cards -->
          <div class="space-y-3 mb-4">
            <!-- Microphone card -->
            <button
              class="w-full text-left p-4 rounded-lg border-2 transition-colors"
              :class="audioType === 'pulseaudio'
                ? 'border-green-500 bg-green-50'
                : 'border-gray-200 hover:border-gray-300'"
              @click="audioType = 'pulseaudio'"
            >
              <div class="flex items-center gap-3">
                <div
                  class="flex-shrink-0 w-5 h-5 rounded-full border-2 flex items-center justify-center"
                  :class="audioType === 'pulseaudio' ? 'border-green-500' : 'border-gray-300'"
                >
                  <div
                    v-if="audioType === 'pulseaudio'"
                    class="w-2.5 h-2.5 rounded-full bg-green-500"
                  />
                </div>
                <div>
                  <div class="font-medium text-gray-900">
                    Microphone
                  </div>
                  <div class="text-sm text-gray-500">
                    Use a USB or built-in microphone
                  </div>
                </div>
              </div>
            </button>

            <!-- Network Stream card -->
            <div
              class="rounded-lg border-2 transition-colors"
              :class="audioType === 'rtsp'
                ? 'border-green-500 bg-green-50'
                : 'border-gray-200 hover:border-gray-300'"
            >
              <button
                class="w-full text-left p-4"
                @click="audioType = 'rtsp'"
              >
                <div class="flex items-center gap-3">
                  <div
                    class="flex-shrink-0 w-5 h-5 rounded-full border-2 flex items-center justify-center"
                    :class="audioType === 'rtsp' ? 'border-green-500' : 'border-gray-300'"
                  >
                    <div
                      v-if="audioType === 'rtsp'"
                      class="w-2.5 h-2.5 rounded-full bg-green-500"
                    />
                  </div>
                  <div>
                    <div class="font-medium text-gray-900">
                      Network Stream
                    </div>
                    <div class="text-sm text-gray-500">
                      Use audio from an RTSP stream (e.g. IP camera)
                    </div>
                  </div>
                </div>
              </button>

              <!-- RTSP fields (expanded when selected) -->
              <div
                v-if="audioType === 'rtsp'"
                class="px-4 pb-4 pt-1 space-y-3 border-t border-green-200"
              >
                <!-- URL field -->
                <div>
                  <label
                    for="rtsp-url"
                    class="block text-sm text-gray-600 mb-1"
                  >Stream URL</label>
                  <input
                    id="rtsp-url"
                    v-model="rtspUrl"
                    type="text"
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-green-500 focus:ring-1 focus:ring-green-400"
                    placeholder="rtsp://192.168.1.100/stream"
                    @input="clearRtspError"
                  >
                </div>

                <!-- Label field -->
                <div>
                  <label
                    for="rtsp-label"
                    class="block text-sm text-gray-600 mb-1"
                  >Label <span class="text-gray-400 font-normal">(optional)</span></label>
                  <input
                    id="rtsp-label"
                    v-model="rtspLabel"
                    type="text"
                    maxlength="30"
                    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-green-500 focus:ring-1 focus:ring-green-400"
                    placeholder="e.g. Backyard mic"
                    @input="sanitizeRtspLabel"
                  >
                  <p class="text-xs text-gray-400 mt-0.5">
                    Letters, numbers, spaces, hyphens, underscores. Max 30 characters.
                  </p>
                </div>

                <!-- Testing progress -->
                <div
                  v-if="testingStream"
                  class="flex items-center gap-2 text-blue-700 text-sm"
                >
                  <svg
                    class="animate-spin h-4 w-4"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      class="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      stroke-width="4"
                    />
                    <path
                      class="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span>Testing stream connection...</span>
                </div>

                <!-- RTSP error -->
                <div
                  v-else-if="rtspError"
                  class="text-xs text-amber-700 bg-amber-50 p-2 rounded-lg"
                >
                  <span>{{ rtspError }}</span>
                  <button
                    v-if="canForceAdd"
                    type="button"
                    class="block text-gray-500 hover:text-gray-700 underline mt-1"
                    @click="forceAddStream"
                  >
                    Finish anyway
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer hint -->
          <p class="text-xs text-gray-400 text-center mb-4">
            You can add more audio sources later in Settings.
          </p>

          <!-- Restart message -->
          <div
            v-if="serviceRestart.restartMessage.value"
            class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md"
          >
            <div class="flex items-center gap-2 text-sm text-blue-800">
              <svg
                class="animate-spin h-4 w-4"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  class="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  stroke-width="4"
                />
                <path
                  class="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              {{ serviceRestart.restartMessage.value }}
            </div>
          </div>

          <!-- Back / Finish buttons -->
          <div class="flex gap-3">
            <button
              :disabled="saving || testingStream || serviceRestart.isRestarting.value"
              class="flex-1 bg-gray-200 hover:bg-gray-300 disabled:bg-gray-100 disabled:cursor-not-allowed text-gray-700 font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-gray-300"
              @click="errorMessage = ''; step = 1"
            >
              Back
            </button>
            <button
              :disabled="!canFinish || saving || testingStream || serviceRestart.isRestarting.value"
              class="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
              @click="finish"
            >
              {{ saving ? 'Saving...' : 'Finish' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { requestRestart, useServiceRestart } from '@/composables/useServiceRestart'
import { limitDecimals, sanitizeLabel } from '@/utils/inputHelpers'
import api from '@/services/api'

export default {
  name: 'SetupWizard',
  props: {
    isVisible: {
      type: Boolean,
      default: false
    }
  },
  setup() {
    // Composables
    const serviceRestart = useServiceRestart()

    const step = ref(1)

    const latitude = ref(null)
    const longitude = ref(null)
    const locationName = ref('')
    const searchQuery = ref('')
    const searchResults = ref([])
    const errorMessage = ref('')
    const searching = ref(false)

    const audioType = ref('pulseaudio')
    const rtspUrl = ref('')
    const rtspLabel = ref('')
    const testingStream = ref(false)
    const rtspError = ref('')
    const canForceAdd = ref(false)
    const rtspValidated = ref(false)
    const saving = ref(false)

    const isValidLocation = computed(() => {
      return latitude.value !== null &&
             longitude.value !== null &&
             latitude.value >= -90 && latitude.value <= 90 &&
             longitude.value >= -180 && longitude.value <= 180
    })

    const canFinish = computed(() => {
      if (audioType.value === 'pulseaudio') return true
      return !!rtspUrl.value.trim()
    })

    const searchAddress = async () => {
      if (!searchQuery.value.trim()) return

      searching.value = true
      errorMessage.value = ''
      searchResults.value = []

      try {
        const response = await fetch(
          `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(searchQuery.value)}&format=json&limit=5`,
          {
            headers: {
              'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy)'
            }
          }
        )

        if (response.ok) {
          const data = await response.json()
          if (data.length > 0) {
            searchResults.value = data
          } else {
            errorMessage.value = 'No results found. Try a different search term.'
          }
        } else {
          throw new Error('Search failed')
        }
      } catch (error) {
        console.error('Address search error:', error)
        errorMessage.value = 'Search failed. Please try again or enter coordinates manually.'
      } finally {
        searching.value = false
      }
    }

    const selectSearchResult = (result) => {
      latitude.value = Math.round(parseFloat(result.lat) * 100) / 100
      longitude.value = Math.round(parseFloat(result.lon) * 100) / 100
      locationName.value = result.display_name.split(', ').slice(0, 3).join(', ')
      searchResults.value = []
      searchQuery.value = ''
    }

    const clearRtspError = () => {
      rtspError.value = ''
      canForceAdd.value = false
      rtspValidated.value = false
    }

    const sanitizeRtspLabel = () => {
      rtspLabel.value = sanitizeLabel(rtspLabel.value)
    }

    const validateRtspUrl = () => {
      const trimmed = rtspUrl.value.trim()
      if (!trimmed) {
        rtspError.value = 'URL is required'
        return null
      }
      if (!trimmed.startsWith('rtsp://') && !trimmed.startsWith('rtsps://')) {
        rtspError.value = 'Must start with rtsp:// or rtsps://'
        return null
      }
      return trimmed
    }

    const forceAddStream = () => {
      rtspError.value = ''
      canForceAdd.value = false
      rtspValidated.value = true
      finish()
    }

    const finish = async () => {
      errorMessage.value = ''

      // Auto-test RTSP stream if not already validated
      if (audioType.value === 'rtsp' && !rtspValidated.value) {
        clearRtspError()
        const validatedUrl = validateRtspUrl()
        if (!validatedUrl) return

        testingStream.value = true
        try {
          const { data } = await api.post('/stream/test', {
            url: validatedUrl,
            type: 'rtsp',
          })
          if (!data.success) {
            rtspError.value = data.message || 'Stream not accessible'
            canForceAdd.value = true
            return
          }
          rtspValidated.value = true
        } catch {
          rtspError.value = 'Test request failed'
          canForceAdd.value = true
          return
        } finally {
          testingStream.value = false
        }
      }

      saving.value = true

      try {
        // Get current settings
        const { data: settings } = await api.get('/settings')

        // Apply location
        settings.location = {
          ...settings.location,
          latitude: latitude.value,
          longitude: longitude.value,
          configured: true
        }

        // Apply audio source based on user's choice
        const sources = settings.audio?.sources || []
        let nextId = settings.audio?.next_source_id || 0

        if (audioType.value === 'pulseaudio') {
          // Create mic source if one doesn't already exist
          const existingMic = sources.find(s => s.type === 'pulseaudio')
          if (!existingMic) {
            sources.push({
              id: `source_${nextId}`,
              type: 'pulseaudio',
              device: 'default',
              label: 'Local Mic',
              enabled: true
            })
            nextId++
          } else {
            existingMic.enabled = true
          }
        } else {
          const trimmedUrl = rtspUrl.value.trim()

          // Disable existing mic source
          sources.forEach(s => {
            if (s.type === 'pulseaudio') {
              s.enabled = false
            }
          })

          // Re-enable existing source with same URL (idempotent on retry),
          // otherwise add a new one
          const existing = sources.find(s => s.type === 'rtsp' && s.url === trimmedUrl)
          if (existing) {
            existing.enabled = true
            if (rtspLabel.value.trim()) existing.label = rtspLabel.value.trim()
          } else {
            sources.push({
              id: `source_${nextId}`,
              type: 'rtsp',
              url: trimmedUrl,
              label: rtspLabel.value.trim(),
              enabled: true
            })
            nextId++
          }
        }

        settings.audio = {
          ...settings.audio,
          sources,
          next_source_id: nextId
        }

        // Save everything in one PUT
        const { data: saveResult } = await api.put('/settings', settings)

        // Check that timezone was resolved
        const savedLocation = saveResult?.settings?.location || settings.location
        if (!savedLocation.timezone) {
          errorMessage.value = 'Could not determine timezone for this location. Please try different coordinates.'
          saving.value = false
          step.value = 1
          return
        }

        // Trigger restart
        await requestRestart()
        await serviceRestart.waitForRestart({
          autoReload: true,
          message: 'Applying settings'
        })
      } catch (error) {
        console.error('Setup save error:', error)
        errorMessage.value = 'Failed to save settings. Please try again.'
        saving.value = false
      }
    }

    return {
      step,
      latitude,
      longitude,
      locationName,
      searchQuery,
      searchResults,
      errorMessage,
      searching,
      isValidLocation,
      searchAddress,
      selectSearchResult,
      limitDecimals,
      audioType,
      rtspUrl,
      rtspLabel,
      testingStream,
      rtspError,
      canForceAdd,
      canFinish,
      clearRtspError,
      sanitizeRtspLabel,
      forceAddStream,
      saving,
      finish,
      serviceRestart
    }
  }
}
</script>
