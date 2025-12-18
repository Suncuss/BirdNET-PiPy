<template>
  <div v-if="isVisible" class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop -->
    <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"></div>

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <!-- Header -->
        <div class="text-center mb-6">
          <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
            <svg class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
            </svg>
          </div>
          <h2 class="text-xl font-semibold text-gray-900">Set Your Location</h2>
          <p class="mt-2 text-sm text-gray-600">
            BirdNET uses your location to filter bird species that are likely in your area.
          </p>
        </div>

        <!-- Error message -->
        <div v-if="errorMessage" class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm">
          {{ errorMessage }}
        </div>

        <!-- Option 1: Use Current Location -->
        <div class="mb-4">
          <button
            @click="useCurrentLocation"
            :disabled="geolocating"
            class="w-full flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
          >
            <svg v-if="!geolocating" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
            </svg>
            <svg v-else class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ geolocating ? 'Getting location...' : 'Use My Current Location' }}
          </button>
        </div>

        <!-- Divider -->
        <div class="relative my-4">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-gray-300"></div>
          </div>
          <div class="relative flex justify-center text-sm">
            <span class="bg-white px-2 text-gray-500">or search by address</span>
          </div>
        </div>

        <!-- Option 2: Address Search -->
        <div class="mb-4">
          <div class="flex gap-2">
            <input
              v-model="searchQuery"
              @keyup.enter="searchAddress"
              type="text"
              placeholder="City, address, or place name..."
              class="flex-1 rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50"
            >
            <button
              @click="searchAddress"
              :disabled="searching || !searchQuery.trim()"
              class="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <svg v-if="!searching" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <svg v-else class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </button>
          </div>

          <!-- Search Results -->
          <div v-if="searchResults.length > 0" class="mt-2 border rounded-md shadow-sm max-h-40 overflow-y-auto">
            <button
              v-for="result in searchResults"
              :key="result.place_id"
              @click="selectSearchResult(result)"
              class="w-full text-left px-3 py-2 hover:bg-gray-100 border-b last:border-b-0 text-sm"
            >
              {{ result.display_name }}
            </button>
          </div>
        </div>

        <!-- Divider -->
        <div class="relative my-4">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-gray-300"></div>
          </div>
          <div class="relative flex justify-center text-sm">
            <span class="bg-white px-2 text-gray-500">or enter coordinates manually</span>
          </div>
        </div>

        <!-- Option 3: Manual Entry -->
        <div class="grid grid-cols-2 gap-4 mb-6">
          <div>
            <label for="latitude" class="block text-sm font-medium text-gray-700 mb-1">Latitude</label>
            <input
              id="latitude"
              v-model.number="latitude"
              type="number"
              step="0.01"
              placeholder="e.g., 42.47"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50"
            >
          </div>
          <div>
            <label for="longitude" class="block text-sm font-medium text-gray-700 mb-1">Longitude</label>
            <input
              id="longitude"
              v-model.number="longitude"
              type="number"
              step="0.01"
              placeholder="e.g., -76.45"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring focus:ring-green-200 focus:ring-opacity-50"
            >
          </div>
        </div>

        <!-- Selected Location Display -->
        <div v-if="latitude && longitude" class="mb-4 p-3 bg-green-50 border border-green-200 rounded-md">
          <p class="text-sm text-green-800">
            <span class="font-medium">Selected:</span> {{ latitude.toFixed(2) }}, {{ longitude.toFixed(2) }}
            <span v-if="locationName" class="block text-xs text-green-600 mt-1">{{ locationName }}</span>
          </p>
        </div>

        <!-- Restart message -->
        <div v-if="serviceRestart.restartMessage.value" class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
          <div class="flex items-center gap-2 text-sm text-blue-800">
            <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ serviceRestart.restartMessage.value }}
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveLocation"
          :disabled="!isValidLocation || saving || serviceRestart.isRestarting.value"
          class="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
        >
          {{ saving ? 'Saving...' : 'Save Location' }}
        </button>

        <!-- Skip for now link -->
        <p v-if="!serviceRestart.isRestarting.value" class="mt-4 text-center text-sm text-gray-500">
          <button @click="skipSetup" class="text-gray-600 hover:text-gray-800 underline">
            Skip for now (use default location)
          </button>
        </p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { useServiceRestart } from '@/composables/useServiceRestart'
import api from '@/services/api'

export default {
  name: 'LocationSetupModal',
  props: {
    isVisible: {
      type: Boolean,
      default: false
    }
  },
  emits: ['close', 'location-saved'],
  setup(props, { emit }) {
    // Composables
    const serviceRestart = useServiceRestart()

    // State
    const latitude = ref(null)
    const longitude = ref(null)
    const locationName = ref('')
    const searchQuery = ref('')
    const searchResults = ref([])
    const errorMessage = ref('')
    const geolocating = ref(false)
    const searching = ref(false)
    const saving = ref(false)

    // Computed
    const isValidLocation = computed(() => {
      return latitude.value !== null &&
             longitude.value !== null &&
             latitude.value >= -90 && latitude.value <= 90 &&
             longitude.value >= -180 && longitude.value <= 180
    })

    // Methods
    const useCurrentLocation = async () => {
      if (!navigator.geolocation) {
        errorMessage.value = 'Geolocation is not supported by your browser'
        return
      }

      geolocating.value = true
      errorMessage.value = ''

      try {
        const position = await new Promise((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
          })
        })

        // Round to 2 decimal places (sufficient precision for BirdNET species filtering)
        latitude.value = Math.round(position.coords.latitude * 100) / 100
        longitude.value = Math.round(position.coords.longitude * 100) / 100
        locationName.value = 'Current location'

        // Try to get a readable name via reverse geocoding
        reverseGeocode(latitude.value, longitude.value)
      } catch (error) {
        console.error('Geolocation error:', error)
        if (error.code === 1) {
          errorMessage.value = 'Location access denied. Please enable location permissions or enter manually.'
        } else if (error.code === 2) {
          errorMessage.value = 'Unable to determine location. Please try again or enter manually.'
        } else if (error.code === 3) {
          errorMessage.value = 'Location request timed out. Please try again or enter manually.'
        } else {
          errorMessage.value = 'Failed to get location. Please enter manually.'
        }
      } finally {
        geolocating.value = false
      }
    }

    const reverseGeocode = async (lat, lon) => {
      try {
        const response = await fetch(
          `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
          {
            headers: {
              'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy)'
            }
          }
        )
        if (response.ok) {
          const data = await response.json()
          if (data.display_name) {
            // Shorten the display name to city/region
            const parts = data.display_name.split(', ')
            locationName.value = parts.slice(0, 3).join(', ')
          }
        }
      } catch (error) {
        // Silently fail - we already have coordinates
        console.warn('Reverse geocoding failed:', error)
      }
    }

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
      // Round to 2 decimal places (sufficient precision for BirdNET species filtering)
      latitude.value = Math.round(parseFloat(result.lat) * 100) / 100
      longitude.value = Math.round(parseFloat(result.lon) * 100) / 100
      locationName.value = result.display_name.split(', ').slice(0, 3).join(', ')
      searchResults.value = []
      searchQuery.value = ''
    }

    const saveLocation = async () => {
      if (!isValidLocation.value) return

      saving.value = true
      errorMessage.value = ''

      try {
        // First, get current settings
        const { data: settings } = await api.get('/settings')

        // Update location with configured flag
        settings.location = {
          latitude: latitude.value,
          longitude: longitude.value,
          configured: true
        }

        // Save updated settings (triggers restart)
        await api.put('/settings', settings)

        emit('location-saved', {
          latitude: latitude.value,
          longitude: longitude.value
        })

        saving.value = false

        // Wait for service restart, then auto-reload
        await serviceRestart.waitForRestart({ autoReload: true })
      } catch (error) {
        console.error('Save error:', error)
        errorMessage.value = 'Failed to save location. Please try again.'
        saving.value = false
      }
    }

    const skipSetup = async () => {
      // Mark as configured with default values
      saving.value = true

      try {
        const { data: settings } = await api.get('/settings')
        settings.location.configured = true

        await api.put('/settings', settings)

        saving.value = false

        // Wait for service restart, then auto-reload
        await serviceRestart.waitForRestart({ autoReload: true })
      } catch (error) {
        console.error('Skip setup error:', error)
        emit('close') // Close anyway on skip
        saving.value = false
      }
    }

    return {
      latitude,
      longitude,
      locationName,
      searchQuery,
      searchResults,
      errorMessage,
      geolocating,
      searching,
      saving,
      isValidLocation,
      useCurrentLocation,
      searchAddress,
      selectSearchResult,
      saveLocation,
      skipSetup,
      serviceRestart
    }
  }
}
</script>
