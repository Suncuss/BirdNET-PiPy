<template>
    <div class="settings p-4">
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- Location Settings -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">Location Settings</h2>
        <div class="space-y-4">
          <div>
            <label for="latitude" class="block text-sm font-medium text-gray-700 mb-1">Latitude</label>
            <input 
              id="latitude" 
              type="number" 
              step="0.000001"
              v-model.number="settings.location.latitude"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
              placeholder="e.g., 42.47"
            >
            <p class="text-xs text-gray-500 mt-1">Used for species location filtering</p>
          </div>
          <div>
            <label for="longitude" class="block text-sm font-medium text-gray-700 mb-1">Longitude</label>
            <input 
              id="longitude" 
              type="number" 
              step="0.000001"
              v-model.number="settings.location.longitude"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
              placeholder="e.g., -76.45"
            >
            <p class="text-xs text-gray-500 mt-1">Used for species location filtering</p>
          </div>
        </div>
      </div>

      <!-- Detection Settings -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">Detection Settings</h2>
        <div class="space-y-4">
          <div>
            <label for="sensitivity" class="block text-sm font-medium text-gray-700 mb-1">
              Sensitivity: {{ settings.detection.sensitivity }}
            </label>
            <input 
              id="sensitivity" 
              type="range" 
              min="0.1" 
              max="1.0" 
              step="0.05"
              v-model.number="settings.detection.sensitivity" 
              class="block w-full mt-1"
            >
            <p class="text-xs text-gray-500 mt-1">Higher values detect more species (may include false positives)</p>
          </div>
          <div>
            <label for="cutoff" class="block text-sm font-medium text-gray-700 mb-1">
              Confidence Cutoff: {{ settings.detection.cutoff }}
            </label>
            <input 
              id="cutoff" 
              type="range" 
              min="0.1" 
              max="1.0" 
              step="0.05"
              v-model.number="settings.detection.cutoff" 
              class="block w-full mt-1"
            >
            <p class="text-xs text-gray-500 mt-1">Minimum confidence required to report detection</p>
          </div>
        </div>
      </div>

      <!-- Audio Settings -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">Audio Settings</h2>
        <div class="space-y-4">
          <div>
            <label for="recordingMode" class="block text-sm font-medium text-gray-700 mb-1">Recording Mode</label>
            <select
              id="recordingMode"
              v-model="recordingMode"
              @change="onRecordingModeChange"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
            >
              <option value="pulseaudio">Local Microphone</option>
              <option value="http_stream">Custom Stream URL</option>
            </select>
            <p class="text-xs text-gray-500 mt-1">Choose audio recording method</p>
          </div>

          <!-- Custom HTTP Stream -->
          <div v-if="recordingMode === 'http_stream'" class="mt-4">
            <label for="streamUrl" class="block text-sm font-medium text-gray-700 mb-1">Stream URL</label>
            <input
              id="streamUrl"
              type="text"
              v-model="settings.audio.stream_url"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
              placeholder="http://example.com:8888/stream.mp3"
            >
            <p class="text-xs text-gray-500 mt-1">Enter the full URL of your audio stream</p>
          </div>

          <!-- Local Microphone - no additional settings needed -->
        </div>
      </div>

      <!-- Recording Settings -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">Recording Settings</h2>
        <div class="space-y-4">
          <div>
            <label for="recordingLength" class="block text-sm font-medium text-gray-700 mb-1">
              Recording Length
            </label>
            <select
              id="recordingLength"
              v-model.number="settings.audio.recording_length"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
            >
              <option :value="9">9 seconds</option>
              <option :value="12">12 seconds</option>
              <option :value="15">15 seconds</option>
            </select>
            <p class="text-xs text-gray-500 mt-1">Duration of each audio recording chunk</p>
          </div>
          <div>
            <label for="overlap" class="block text-sm font-medium text-gray-700 mb-1">
              Overlap
            </label>
            <select
              id="overlap"
              v-model.number="settings.audio.overlap"
              class="block w-full mt-1 rounded-md border-gray-300 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
            >
              <option :value="0.0">0.0 seconds</option>
              <option :value="0.5">0.5 seconds</option>
              <option :value="1.0">1.0 seconds</option>
              <option :value="1.5">1.5 seconds</option>
              <option :value="2.0">2.0 seconds</option>
              <option :value="2.5">2.5 seconds</option>
            </select>
            <p class="text-xs text-gray-500 mt-1">Overlap between analysis windows (for future use)</p>
          </div>
        </div>
      </div>

      <!-- System Updates -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-3">System Updates</h2>

        <div class="space-y-4">
          <!-- Current Version Info -->
          <div v-if="systemUpdate.versionInfo.value" class="text-sm bg-gray-50 p-3 rounded border border-gray-200">
            <div class="flex justify-between items-start mb-2">
              <span class="font-medium text-gray-700">Current Version</span>
              <span class="text-xs font-mono px-2 py-1 bg-gray-200 text-gray-600 rounded">
                {{ systemUpdate.versionInfo.value.current_branch }}
              </span>
            </div>
            <div class="text-xs text-gray-600 space-y-1">
              <div>
                <span class="font-mono text-blue-600">{{ systemUpdate.versionInfo.value.current_commit }}</span>
                <span class="ml-2 text-gray-500">{{ systemUpdate.versionInfo.value.current_commit_message }}</span>
              </div>
              <div class="text-gray-400">
                {{ formatDate(systemUpdate.versionInfo.value.current_commit_date) }}
              </div>
            </div>
          </div>

          <!-- Check for Updates Button -->
          <button
            @click="systemUpdate.checkForUpdates"
            :disabled="systemUpdate.checking.value || systemUpdate.updating.value"
            class="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            <span v-if="systemUpdate.checking.value">Checking for updates...</span>
            <span v-else-if="systemUpdate.updating.value">Updating system...</span>
            <span v-else>Check for Updates</span>
          </button>

          <!-- Update Available Info -->
          <div
            v-if="systemUpdate.updateAvailable.value && systemUpdate.updateInfo.value"
            class="bg-blue-50 border-l-4 border-blue-400 p-3"
          >
            <p class="text-sm font-semibold text-blue-800 mb-2">
              Update Available ({{ systemUpdate.updateInfo.value.commits_behind }} commits behind)
            </p>

            <!-- Commit Preview -->
            <div
              v-if="systemUpdate.updateInfo.value.preview_commits?.length > 0"
              class="mt-2 text-xs text-blue-700 space-y-1 max-h-40 overflow-y-auto bg-white bg-opacity-50 p-2 rounded"
            >
              <div class="font-semibold mb-1 text-blue-800">Recent changes:</div>
              <div
                v-for="commit in systemUpdate.updateInfo.value.preview_commits"
                :key="commit.hash"
                class="border-l-2 border-blue-300 pl-2 py-0.5"
              >
                <span class="font-mono text-blue-600">{{ commit.hash }}</span>
                <span class="ml-1">{{ commit.message }}</span>
              </div>
            </div>

            <!-- Update Now Button -->
            <button
              @click="showUpdateConfirm = true"
              :disabled="systemUpdate.updating.value"
              class="w-full mt-3 bg-green-600 hover:bg-green-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-green-300 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {{ systemUpdate.updating.value ? 'Updating... Please wait' : 'Update Now' }}
            </button>

            <!-- Downtime Warning -->
            <div class="mt-2 text-xs text-blue-600 italic">
              Update will restart all services (2-5 min downtime)
            </div>
          </div>

          <!-- Status Messages -->
          <div
            v-if="systemUpdate.statusMessage.value"
            :class="{
              'text-red-600 bg-red-50 border-l-4 border-red-400': systemUpdate.statusType.value === 'error',
              'text-green-600 bg-green-50 border-l-4 border-green-400': systemUpdate.statusType.value === 'success',
              'text-blue-600 bg-blue-50 border-l-4 border-blue-400': systemUpdate.statusType.value === 'info'
            }"
            class="text-sm font-medium p-3 rounded"
          >
            {{ systemUpdate.statusMessage.value }}
          </div>
        </div>
      </div>

      <!-- Restart Status -->
      <div v-if="serviceRestart.restartMessage.value" class="col-span-1 lg:col-span-2">
        <div class="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div class="flex items-center gap-3 text-blue-800">
            <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span class="font-medium">{{ serviceRestart.restartMessage.value }}</span>
          </div>
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex flex-col lg:flex-row lg:justify-between items-center col-span-1 lg:col-span-2 space-y-2 lg:space-y-0">
        <div class="text-sm order-2 lg:order-1" :class="saveStatus ? (saveStatus.type === 'success' ? 'text-green-600' : 'text-red-600') : ''">
          {{ saveStatus ? saveStatus.message : '' }}
        </div>
        <div class="flex space-x-2 order-1 lg:order-2">
          <button
            @click="resetToDefaults"
            class="bg-gray-600 hover:bg-gray-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-gray-300"
            :disabled="loading || serviceRestart.isRestarting.value"
          >
            Reset to Defaults
          </button>
          <button
            @click="saveSettings"
            class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300"
            :disabled="loading || serviceRestart.isRestarting.value"
          >
            {{ loading ? 'Saving...' : 'Save Settings' }}
          </button>
        </div>
      </div>
      </div>

      <!-- Update Confirmation Modal -->
      <div v-if="showUpdateConfirm" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"></div>
        <div class="flex min-h-full items-center justify-center p-4">
          <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-yellow-100 mb-4">
                <svg class="h-6 w-6 text-yellow-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </div>
              <h3 class="text-lg font-semibold text-gray-900">Confirm System Update</h3>
              <p class="mt-2 text-sm text-gray-600">
                This will update the system and restart all services.
              </p>
            </div>

            <div class="bg-yellow-50 border border-yellow-200 rounded-md p-3 mb-6">
              <ul class="text-sm text-yellow-800 space-y-1">
                <li>Expected downtime: 2-5 minutes</li>
                <li>Audio detection will be interrupted</li>
                <li>Page will reload when complete</li>
              </ul>
            </div>

            <div class="flex gap-3">
              <button
                @click="showUpdateConfirm = false"
                class="flex-1 bg-gray-200 hover:bg-gray-300 text-gray-800 font-semibold py-2 px-4 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                @click="confirmUpdate"
                class="flex-1 bg-green-600 hover:bg-green-700 text-white font-semibold py-2 px-4 rounded-lg transition-colors"
              >
                Update Now
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </template>
  
  <script>
import { ref, onMounted } from 'vue'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { useServiceRestart } from '@/composables/useServiceRestart'

export default {
  name: 'Settings',
  setup() {
    // Composables
    const serviceRestart = useServiceRestart()

    // State
    const loading = ref(false)
    const saveStatus = ref(null)
    const recordingMode = ref('pulseaudio')  // UI state: 'pulseaudio' or 'http_stream'
    const showUpdateConfirm = ref(false)
    const settings = ref({
      location: {
        latitude: 42.47,
        longitude: -76.45,
        configured: false
      },
      detection: {
        sensitivity: 0.75,
        cutoff: 0.60
      },
      audio: {
        recording_mode: 'pulseaudio',  // Backend: 'pulseaudio' or 'http_stream'
        stream_url: null,  // For HTTP streaming mode
        pulseaudio_source: null,  // For PulseAudio mode (uses default if null)
        recording_length: 9,
        overlap: 0.0,  // Overlap in seconds for future use
        sample_rate: 48000,
        recording_chunk_length: 3
      },
      spectrogram: {
        max_freq_khz: 12,
        min_freq_khz: 0,
        max_dbfs: 0,
        min_dbfs: -120
      }
    })

    // System update composable
    const systemUpdate = useSystemUpdate()

    // Helper function for date formatting
    const formatDate = (isoString) => {
      if (!isoString) return ''
      const date = new Date(isoString)
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
    }

    // Load settings from API with retry
    const loadSettings = async (retryCount = 0) => {
      try {
        loading.value = true
        console.log(`Loading settings... (attempt ${retryCount + 1})`)
        const response = await fetch('/api/settings')
        if (response.ok) {
          const data = await response.json()
          settings.value = data
          console.log('Settings loaded successfully:', data)

          // Map backend recording_mode to UI recordingMode
          recordingMode.value = settings.value.audio.recording_mode || 'pulseaudio'
          
          // Clear any previous error status
          if (saveStatus.value?.type === 'error') {
            saveStatus.value = null
          }
        } else {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }
      } catch (error) {
        console.error('Error loading settings:', error)
        
        // Retry up to 3 times with delay
        if (retryCount < 2) {
          console.log(`Retrying in 2 seconds... (${retryCount + 1}/3)`)
          setTimeout(() => loadSettings(retryCount + 1), 2000)
        } else {
          showStatus('error', `Failed to load settings: ${error.message}`)
        }
      } finally {
        loading.value = false
      }
    }

    // Save settings to API
    const saveSettings = async () => {
      try {
        loading.value = true
        // Mark location as configured when saving from settings page
        settings.value.location.configured = true
        const response = await fetch('/api/settings', {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(settings.value)
        })

        if (response.ok) {
          const data = await response.json()
          console.log('Settings saved:', data)
          loading.value = false

          // Wait for service restart, then auto-reload
          await serviceRestart.waitForRestart({ autoReload: true })
        } else {
          throw new Error('Failed to save settings')
        }
      } catch (error) {
        console.error('Error saving settings:', error)
        showStatus('error', 'Failed to save settings')
        loading.value = false
      }
    }

    // Reset to default settings
    const resetToDefaults = async () => {
      if (confirm('Are you sure you want to reset all settings to defaults?')) {
        settings.value = {
          location: {
            latitude: 42.47,
            longitude: -76.45,
            configured: true  // Keep as configured since user explicitly chose defaults
          },
          detection: {
            sensitivity: 0.75,
            cutoff: 0.60
          },
          audio: {
            recording_mode: 'pulseaudio',
            stream_url: null,
            pulseaudio_source: null,
            recording_length: 9,
            overlap: 0.0,
            sample_rate: 48000,
            recording_chunk_length: 3
          },
          spectrogram: {
            max_freq_khz: 12,
            min_freq_khz: 0,
            max_dbfs: 0,
            min_dbfs: -120
          }
        }
        recordingMode.value = 'pulseaudio'
        await saveSettings()
      }
    }

    // Show status message
    const showStatus = (type, message) => {
      saveStatus.value = { type, message }
      setTimeout(() => {
        saveStatus.value = null
      }, 5000)
    }

    // Handle recording mode change
    const onRecordingModeChange = () => {
      // UI values match backend values directly
      settings.value.audio.recording_mode = recordingMode.value

      // Clear irrelevant fields based on mode
      if (recordingMode.value === 'pulseaudio') {
        settings.value.audio.stream_url = null
      } else if (recordingMode.value === 'http_stream') {
        settings.value.audio.pulseaudio_source = null
      }
    }

    // Confirm and trigger system update
    const confirmUpdate = async () => {
      showUpdateConfirm.value = false
      await systemUpdate.triggerUpdate(true) // Pass true to skip the browser confirm
    }

    // Load settings on component mount
    onMounted(() => {
      loadSettings()
      systemUpdate.loadVersionInfo()
    })

    return {
      settings,
      loading,
      saveStatus,
      recordingMode,
      showUpdateConfirm,
      saveSettings,
      resetToDefaults,
      onRecordingModeChange,
      confirmUpdate,
      systemUpdate,
      serviceRestart,
      formatDate
    }
  }
}
</script>
  
  <style scoped>
  /* Add your styles here if needed */
  </style>
  