<template>
    <div class="settings p-4 max-w-4xl mx-auto">
      <!-- Header with Save/Reset buttons -->
      <div class="flex justify-between items-center mb-4">
        <h1 class="text-xl font-semibold text-gray-800">Settings</h1>
        <div class="flex items-center gap-2">
          <span v-if="saveStatus" :class="saveStatus.type === 'success' ? 'text-green-600' : 'text-red-600'" class="text-sm mr-2">
            {{ saveStatus.message }}
          </span>
          <button
            @click="resetToDefaults"
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            :disabled="loading || serviceRestart.isRestarting.value || systemUpdate.isRestarting.value"
          >
            Reset
          </button>
          <button
            @click="saveSettings"
            class="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg shadow-sm transition-colors disabled:bg-gray-400"
            :disabled="loading || serviceRestart.isRestarting.value || systemUpdate.isRestarting.value"
          >
            {{ loading ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </div>

      <!-- Restart Status Banner (shows for both settings save and system update) -->
      <div v-if="serviceRestart.restartMessage.value || systemUpdate.restartMessage.value" class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <div class="flex items-center gap-2 text-blue-700 text-sm">
          <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span>{{ serviceRestart.restartMessage.value || systemUpdate.restartMessage.value }}</span>
        </div>
      </div>

      <!-- Restart Taking Longer Banner -->
      <div v-if="serviceRestart.restartError.value" class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
        <div class="flex items-center gap-2 text-amber-700 text-sm">
          <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>{{ serviceRestart.restartError.value }}</span>
        </div>
      </div>

      <div class="space-y-4">
        <!-- Location & Audio Source -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-4">Location & Audio</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Location -->
            <div class="space-y-3">
              <div class="flex gap-3">
                <div class="flex-1">
                  <label for="latitude" class="block text-sm text-gray-600 mb-1">Latitude</label>
                  <input
                    id="latitude"
                    type="number"
                    step="0.000001"
                    v-model.number="settings.location.latitude"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                    placeholder="42.47"
                  >
                </div>
                <div class="flex-1">
                  <label for="longitude" class="block text-sm text-gray-600 mb-1">Longitude</label>
                  <input
                    id="longitude"
                    type="number"
                    step="0.000001"
                    v-model.number="settings.location.longitude"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                    placeholder="-76.45"
                  >
                </div>
              </div>
              <p class="text-xs text-gray-400">Used for filtering species by region</p>
            </div>

            <!-- Audio Source -->
            <div class="space-y-3">
              <div>
                <label for="recordingMode" class="block text-sm text-gray-600 mb-1">Audio Source</label>
                <select
                  id="recordingMode"
                  v-model="recordingMode"
                  @change="onRecordingModeChange"
                  class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                >
                  <option value="pulseaudio">Local Microphone</option>
                  <option value="http_stream">HTTP Stream</option>
                  <option value="rtsp">RTSP Stream</option>
                </select>
              </div>
              <div v-if="recordingMode === 'http_stream'">
                <input
                  id="streamUrl"
                  type="text"
                  v-model="settings.audio.stream_url"
                  class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="http://example.com:8888/stream.mp3"
                >
              </div>
              <div v-if="recordingMode === 'rtsp'">
                <input
                  id="rtspUrl"
                  type="text"
                  v-model="settings.audio.rtsp_url"
                  class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="rtsp://user:pass@192.168.1.100:554/stream"
                >
                <p class="text-xs text-gray-400 mt-1">Supports rtsp:// and rtsps://</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Storage -->
        <div v-if="storage" class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-4">Storage</h2>
          <div class="flex justify-between items-center mb-2">
            <span class="text-sm text-gray-600">Disk Usage</span>
            <span class="text-sm font-medium text-gray-800">{{ storage.percent_used }}%</span>
          </div>
          <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-300"
              :class="storage.percent_used >= 75 ? 'bg-orange-500' : 'bg-green-500'"
              :style="{ width: storage.percent_used + '%' }"
            ></div>
          </div>
          <div class="flex justify-between mt-2 text-xs text-gray-500">
            <span>{{ storage.used_gb }}GB used</span>
            <span>{{ storage.free_gb }}GB free of {{ storage.total_gb }}GB</span>
          </div>
          <p class="text-xs text-gray-400 mt-3">Auto-cleanup removes oldest recordings when usage exceeds 85%.</p>
        </div>

        <!-- Security Settings -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-4">Security</h2>

          <!-- Auth Toggle -->
          <div class="flex items-center justify-between mb-4">
            <div>
              <label class="text-sm text-gray-600">Require Authentication</label>
              <p class="text-xs text-gray-400">Protect settings and audio stream with password</p>
            </div>
            <button
              @click="handleAuthToggle"
              :disabled="authLoading"
              :class="auth.authStatus.value.authEnabled ? 'bg-green-600' : 'bg-gray-200'"
              class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
            >
              <span
                :class="auth.authStatus.value.authEnabled ? 'translate-x-6' : 'translate-x-1'"
                class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              />
            </button>
          </div>

          <!-- Change Password (when auth enabled and setup complete) -->
          <div v-if="auth.authStatus.value.authEnabled && auth.authStatus.value.setupComplete" class="mb-4">
            <button
              @click="showChangePassword = true"
              class="text-sm text-blue-600 hover:text-blue-800"
            >
              Change Password
            </button>
          </div>

          <!-- Auth Error Message -->
          <div v-if="auth.error.value" class="mb-4 p-2 bg-red-50 text-red-600 text-xs rounded-lg">
            {{ auth.error.value }}
          </div>

          <!-- Password Reset Help -->
          <p class="text-xs text-gray-400">
            Forgot password? Create a file named <code class="bg-gray-100 px-1 rounded">RESET_PASSWORD</code>
            in <code class="bg-gray-100 px-1 rounded">data/config/</code> on your Pi to reset.
          </p>
        </div>

        <!-- Advanced Settings (Collapsible) -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100">
          <button
            @click="showAdvancedSettings = !showAdvancedSettings"
            class="w-full p-5 flex items-center justify-between text-left hover:bg-gray-50 transition-colors rounded-lg"
          >
            <div>
              <h2 class="text-base font-medium text-gray-800">Advanced Settings</h2>
              <p class="text-xs text-gray-400 mt-0.5">Detection, recording, and species filters</p>
            </div>
            <svg
              class="w-5 h-5 text-gray-400 transition-transform duration-200"
              :class="{ 'rotate-180': showAdvancedSettings }"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <div v-show="showAdvancedSettings" class="border-t border-gray-100 p-5 space-y-6">
            <!-- Detection Settings -->
            <div>
              <h3 class="text-sm font-medium text-gray-700 mb-3">Detection</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <div class="flex justify-between items-center mb-2">
                    <label for="sensitivity" class="text-sm text-gray-600">Sensitivity</label>
                    <span class="text-sm font-medium text-gray-800">{{ settings.detection.sensitivity }}</span>
                  </div>
                  <input
                    id="sensitivity"
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    v-model.number="settings.detection.sensitivity"
                    class="w-full h-2 rounded-lg cursor-pointer"
                  >
                  <p class="text-xs text-gray-400 mt-1">Higher = more detections</p>
                </div>
                <div>
                  <div class="flex justify-between items-center mb-2">
                    <label for="cutoff" class="text-sm text-gray-600">Confidence Threshold</label>
                    <span class="text-sm font-medium text-gray-800">{{ settings.detection.cutoff }}</span>
                  </div>
                  <input
                    id="cutoff"
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    v-model.number="settings.detection.cutoff"
                    class="w-full h-2 rounded-lg cursor-pointer"
                  >
                  <p class="text-xs text-gray-400 mt-1">Minimum confidence to report</p>
                </div>
              </div>
            </div>

            <!-- Recording Settings -->
            <div class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-medium text-gray-700 mb-3">Recording</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label for="recordingLength" class="block text-sm text-gray-600 mb-1">Chunk Length</label>
                  <select
                    id="recordingLength"
                    v-model.number="settings.audio.recording_length"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  >
                    <option :value="9">9 seconds</option>
                    <option :value="12">12 seconds</option>
                    <option :value="15">15 seconds</option>
                  </select>
                </div>
                <div>
                  <label for="overlap" class="block text-sm text-gray-600 mb-1">Overlap</label>
                  <select
                    id="overlap"
                    v-model.number="settings.audio.overlap"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  >
                    <option :value="0.0">None</option>
                    <option :value="0.5">0.5s</option>
                    <option :value="1.0">1.0s</option>
                    <option :value="1.5">1.5s</option>
                    <option :value="2.0">2.0s</option>
                    <option :value="2.5">2.5s</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- Species Filter Settings -->
            <div class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-medium text-gray-700 mb-3">Species Filter</h3>
              <div class="space-y-3">
                <!-- Allowed Species -->
                <div class="border border-gray-200 rounded-lg p-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <h4 class="text-sm font-medium text-gray-700">Allowed Species</h4>
                      <p class="text-xs text-gray-400">Only detect these species (leave empty for all)</p>
                    </div>
                    <button
                      @click="openFilterModal('allowed')"
                      class="px-3 py-1.5 text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors"
                    >
                      Edit
                    </button>
                  </div>
                  <div v-if="settings.species_filter?.allowed_species?.length" class="flex flex-wrap gap-1.5 mt-2">
                    <span
                      v-for="species in settings.species_filter.allowed_species.slice(0, 5)"
                      :key="species"
                      class="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full"
                    >
                      {{ species }}
                    </span>
                    <span v-if="settings.species_filter.allowed_species.length > 5" class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                      +{{ settings.species_filter.allowed_species.length - 5 }} more
                    </span>
                  </div>
                  <p v-else class="text-xs text-gray-400 mt-2 italic">All species for your location</p>
                </div>

                <!-- Blocked Species -->
                <div class="border border-gray-200 rounded-lg p-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <h4 class="text-sm font-medium text-gray-700">Blocked Species</h4>
                      <p class="text-xs text-gray-400">Never detect these species</p>
                    </div>
                    <button
                      @click="openFilterModal('blocked')"
                      class="px-3 py-1.5 text-xs bg-red-50 text-red-600 hover:bg-red-100 rounded-lg transition-colors"
                    >
                      Edit
                    </button>
                  </div>
                  <div v-if="settings.species_filter?.blocked_species?.length" class="flex flex-wrap gap-1.5 mt-2">
                    <span
                      v-for="species in settings.species_filter.blocked_species.slice(0, 5)"
                      :key="species"
                      class="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded-full"
                    >
                      {{ species }}
                    </span>
                    <span v-if="settings.species_filter.blocked_species.length > 5" class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                      +{{ settings.species_filter.blocked_species.length - 5 }} more
                    </span>
                  </div>
                  <p v-else class="text-xs text-gray-400 mt-2 italic">No species blocked</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- System Updates -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-base font-medium text-gray-800">System</h2>
            <div v-if="systemUpdate.versionInfo.value" class="flex items-center gap-2 text-xs text-gray-500">
              <span class="font-mono">{{ systemUpdate.versionInfo.value.current_commit }}</span>
              <span class="px-1.5 py-0.5 bg-gray-100 rounded text-gray-600">{{ systemUpdate.versionInfo.value.current_branch }}</span>
            </div>
          </div>

          <!-- Update Available -->
          <div v-if="systemUpdate.updateAvailable.value && systemUpdate.updateInfo.value" class="mb-4 p-3 bg-blue-50 rounded-lg">
            <div class="flex items-center justify-between">
              <div>
                <p class="text-sm font-medium text-blue-800">Update available</p>
                <p class="text-xs text-blue-600">
                  {{ systemUpdate.updateInfo.value.fresh_sync ? 'Major version' : `${systemUpdate.updateInfo.value.commits_behind} new commits` }}
                </p>
              </div>
              <button
                @click="showUpdateConfirm = true"
                :disabled="systemUpdate.updating.value"
                class="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
              >
                Update
              </button>
            </div>
            <!-- Commit preview - collapsible -->
            <details v-if="systemUpdate.updateInfo.value.preview_commits?.length > 0" class="mt-2">
              <summary class="text-xs text-blue-600 cursor-pointer hover:text-blue-800">View changes</summary>
              <div class="mt-2 text-xs text-blue-700 space-y-1 max-h-32 overflow-y-auto">
                <div
                  v-for="commit in systemUpdate.updateInfo.value.preview_commits"
                  :key="commit.hash"
                  class="flex gap-2"
                >
                  <span class="font-mono text-blue-500">{{ commit.hash }}</span>
                  <span>{{ commit.message }}</span>
                </div>
              </div>
            </details>
          </div>

          <!-- Check for Updates Button -->
          <button
            @click="systemUpdate.checkForUpdates"
            :disabled="systemUpdate.checking.value || systemUpdate.updating.value"
            class="w-full py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors disabled:text-gray-400 disabled:hover:bg-transparent"
          >
            <span v-if="systemUpdate.checking.value">Checking...</span>
            <span v-else-if="systemUpdate.updating.value">Updating...</span>
            <span v-else>Check for Updates</span>
          </button>

          <!-- Status Messages -->
          <div
            v-if="systemUpdate.statusMessage.value"
            :class="{
              'text-red-600 bg-red-50': systemUpdate.statusType.value === 'error',
              'text-green-600 bg-green-50': systemUpdate.statusType.value === 'success',
              'text-blue-600 bg-blue-50': systemUpdate.statusType.value === 'info'
            }"
            class="mt-3 p-2 text-xs rounded-lg text-center"
          >
            {{ systemUpdate.statusMessage.value }}
          </div>
        </div>
      </div>

      <!-- Change Password Modal -->
      <div v-if="showChangePassword" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" @click="showChangePassword = false"></div>
        <div class="flex min-h-full items-center justify-center p-4">
          <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-4">Change Password</h3>

            <div v-if="changePasswordError" class="mb-4 p-2 bg-red-50 text-red-600 text-sm rounded-lg">
              {{ changePasswordError }}
            </div>

            <form @submit.prevent="handleChangePassword" class="space-y-4">
              <div>
                <label class="block text-sm text-gray-600 mb-1">Current Password</label>
                <input
                  v-model="currentPassword"
                  type="password"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="Enter current password"
                >
              </div>
              <div>
                <label class="block text-sm text-gray-600 mb-1">New Password</label>
                <input
                  v-model="newPassword"
                  type="password"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="Enter new password (min 8 characters)"
                >
              </div>
              <div>
                <label class="block text-sm text-gray-600 mb-1">Confirm New Password</label>
                <input
                  v-model="confirmNewPassword"
                  type="password"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="Confirm new password"
                >
              </div>

              <div class="flex gap-3 pt-2">
                <button
                  type="button"
                  @click="showChangePassword = false"
                  class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  :disabled="authLoading || !newPassword || newPassword !== confirmNewPassword"
                  class="flex-1 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
                >
                  {{ authLoading ? 'Changing...' : 'Change Password' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>

      <!-- Setup Password Modal -->
      <div v-if="showSetupPassword" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" @click="showSetupPassword = false"></div>
        <div class="flex min-h-full items-center justify-center p-4">
          <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-2">Set Up Authentication</h3>
            <p class="text-sm text-gray-600 mb-4">
              Create a password to protect your settings and audio stream.
            </p>

            <div v-if="setupPasswordError" class="mb-4 p-2 bg-red-50 text-red-600 text-sm rounded-lg">
              {{ setupPasswordError }}
            </div>

            <form @submit.prevent="handleSetupPassword" class="space-y-4">
              <div>
                <label class="block text-sm text-gray-600 mb-1">Password</label>
                <input
                  v-model="setupPassword"
                  type="password"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="Enter password (min 8 characters)"
                >
              </div>
              <div>
                <label class="block text-sm text-gray-600 mb-1">Confirm Password</label>
                <input
                  v-model="confirmSetupPassword"
                  type="password"
                  class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="Confirm password"
                >
              </div>

              <div class="flex gap-3 pt-2">
                <button
                  type="button"
                  @click="showSetupPassword = false"
                  class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  :disabled="authLoading || setupPassword.length < 8 || setupPassword !== confirmSetupPassword"
                  class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
                >
                  {{ authLoading ? 'Setting up...' : 'Enable Authentication' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>

      <!-- Update Confirmation Modal -->
      <div v-if="showUpdateConfirm" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" @click="showUpdateConfirm = false"></div>
        <div class="flex min-h-full items-center justify-center p-4">
          <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-2">Update System?</h3>
            <p class="text-sm text-gray-600 mb-4">
              This will restart all services. Detection will pause briefly during the update.
            </p>
            <div class="flex gap-3">
              <button
                @click="showUpdateConfirm = false"
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                @click="confirmUpdate"
                class="flex-1 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                Update
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Species Filter Modal -->
      <SpeciesFilterModal
        v-if="showSpeciesFilterModal"
        :title="speciesFilterModalConfig.title"
        :description="speciesFilterModalConfig.description"
        v-model="speciesFilterModalConfig.list"
        @close="closeFilterModal"
        @update:modelValue="updateFilterList"
      />
    </div>
  </template>

  <script>
import { ref, onMounted } from 'vue'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { useServiceRestart } from '@/composables/useServiceRestart'
import { useAuth } from '@/composables/useAuth'
import api from '@/services/api'
import SpeciesFilterModal from '@/components/SpeciesFilterModal.vue'

export default {
  name: 'Settings',
  components: {
    SpeciesFilterModal
  },
  setup() {
    // Composables
    const serviceRestart = useServiceRestart()
    const auth = useAuth()

    // State
    const loading = ref(false)
    const saveStatus = ref(null)
    const recordingMode = ref('pulseaudio')
    const showUpdateConfirm = ref(false)

    // Storage state
    const storage = ref(null)

    // Advanced settings toggle
    const showAdvancedSettings = ref(false)

    // Species filter modal state
    const showSpeciesFilterModal = ref(false)
    const currentFilterType = ref(null)
    const speciesFilterModalConfig = ref({
      title: '',
      description: '',
      list: []
    })

    // Auth-related state
    const authLoading = ref(false)
    const showChangePassword = ref(false)
    const showSetupPassword = ref(false)
    const currentPassword = ref('')
    const newPassword = ref('')
    const confirmNewPassword = ref('')
    const setupPassword = ref('')
    const confirmSetupPassword = ref('')
    const changePasswordError = ref('')
    const setupPasswordError = ref('')
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
      species_filter: {
        allowed_species: [],
        blocked_species: []
      },
      audio: {
        recording_mode: 'pulseaudio',
        stream_url: null,
        rtsp_url: null,
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
    })

    // System update composable
    const systemUpdate = useSystemUpdate()

    // Load storage info
    const loadStorageInfo = async () => {
      try {
        const { data } = await api.get('/system/storage')
        storage.value = data
      } catch (error) {
        console.error('Error loading storage info:', error)
      }
    }

    // Load settings from API with retry
    const loadSettings = async (retryCount = 0) => {
      try {
        loading.value = true
        const { data } = await api.get('/settings')
        settings.value = data
        recordingMode.value = settings.value.audio.recording_mode || 'pulseaudio'
        if (saveStatus.value?.type === 'error') {
          saveStatus.value = null
        }
      } catch (error) {
        console.error('Error loading settings:', error)
        if (retryCount < 2) {
          setTimeout(() => loadSettings(retryCount + 1), 2000)
        } else {
          showStatus('error', `Failed to load settings`)
        }
      } finally {
        loading.value = false
      }
    }

    // Save settings to API
    const saveSettings = async () => {
      try {
        loading.value = true
        settings.value.location.configured = true
        await api.put('/settings', settings.value)
        loading.value = false
        await serviceRestart.waitForRestart({ autoReload: true })
      } catch (error) {
        console.error('Error saving settings:', error)
        showStatus('error', 'Failed to save')
        loading.value = false
      }
    }

    // Reset to default settings (fetched from backend - single source of truth)
    const resetToDefaults = async () => {
      if (confirm('Reset all settings to defaults?')) {
        try {
          const { data: defaults } = await api.get('/settings/defaults')
          settings.value = defaults
          recordingMode.value = defaults.audio?.recording_mode || 'pulseaudio'
          await saveSettings()
        } catch (error) {
          console.error('Error fetching defaults:', error)
          showStatus('error', 'Failed to load default settings')
        }
      }
    }

    // Show status message
    const showStatus = (type, message) => {
      saveStatus.value = { type, message }
      setTimeout(() => { saveStatus.value = null }, 5000)
    }

    // Handle recording mode change - just update the mode, preserve all URLs
    const onRecordingModeChange = () => {
      settings.value.audio.recording_mode = recordingMode.value
    }

    // Confirm and trigger system update
    const confirmUpdate = async () => {
      showUpdateConfirm.value = false
      await systemUpdate.triggerUpdate(true)
    }

    // Species filter modal handlers
    const openFilterModal = (filterType) => {
      currentFilterType.value = filterType

      // Ensure species_filter exists
      if (!settings.value.species_filter) {
        settings.value.species_filter = {
          allowed_species: [],
          blocked_species: []
        }
      }

      const configs = {
        allowed: {
          title: 'Allowed Species',
          description: 'Only detect these species. Leave empty to detect all species for your location.',
          listKey: 'allowed_species'
        },
        blocked: {
          title: 'Blocked Species',
          description: 'Never detect these species, even if they match your location.',
          listKey: 'blocked_species'
        }
      }

      const config = configs[filterType]
      speciesFilterModalConfig.value = {
        title: config.title,
        description: config.description,
        list: [...(settings.value.species_filter[config.listKey] || [])]
      }
      showSpeciesFilterModal.value = true
    }

    const closeFilterModal = () => {
      showSpeciesFilterModal.value = false
      currentFilterType.value = null
    }

    const updateFilterList = (newList) => {
      if (!settings.value.species_filter) {
        settings.value.species_filter = {
          allowed_species: [],
          blocked_species: []
        }
      }

      const listKeys = {
        allowed: 'allowed_species',
        blocked: 'blocked_species'
      }

      const listKey = listKeys[currentFilterType.value]
      if (listKey) {
        settings.value.species_filter[listKey] = newList
      }
    }

    // Handle auth toggle
    const handleAuthToggle = async () => {
      const newState = !auth.authStatus.value.authEnabled

      // If enabling auth and no password set, show setup modal
      if (newState && !auth.authStatus.value.setupComplete) {
        setupPassword.value = ''
        confirmSetupPassword.value = ''
        setupPasswordError.value = ''
        showSetupPassword.value = true
        return
      }

      authLoading.value = true
      await auth.toggleAuth(newState)
      authLoading.value = false
    }

    // Handle initial password setup
    const handleSetupPassword = async () => {
      setupPasswordError.value = ''

      if (setupPassword.value.length < 8) {
        setupPasswordError.value = 'Password must be at least 8 characters'
        return
      }

      if (setupPassword.value !== confirmSetupPassword.value) {
        setupPasswordError.value = 'Passwords do not match'
        return
      }

      authLoading.value = true
      const success = await auth.setup(setupPassword.value)
      authLoading.value = false

      if (success) {
        showSetupPassword.value = false
        setupPassword.value = ''
        confirmSetupPassword.value = ''
        showStatus('success', 'Authentication enabled')
      } else {
        setupPasswordError.value = auth.error.value || 'Failed to set password'
      }
    }

    // Handle password change
    const handleChangePassword = async () => {
      changePasswordError.value = ''

      if (newPassword.value.length < 8) {
        changePasswordError.value = 'New password must be at least 8 characters'
        return
      }

      if (newPassword.value !== confirmNewPassword.value) {
        changePasswordError.value = 'Passwords do not match'
        return
      }

      authLoading.value = true
      const success = await auth.changePassword(currentPassword.value, newPassword.value)
      authLoading.value = false

      if (success) {
        showChangePassword.value = false
        currentPassword.value = ''
        newPassword.value = ''
        confirmNewPassword.value = ''
        showStatus('success', 'Password changed successfully')
      } else {
        changePasswordError.value = auth.error.value || 'Failed to change password'
      }
    }

    // Load settings on component mount
    onMounted(() => {
      loadSettings()
      loadStorageInfo()
      systemUpdate.loadVersionInfo()
      auth.checkAuthStatus()
    })

    return {
      settings,
      loading,
      saveStatus,
      recordingMode,
      showUpdateConfirm,
      storage,
      saveSettings,
      resetToDefaults,
      onRecordingModeChange,
      confirmUpdate,
      systemUpdate,
      serviceRestart,
      // Advanced settings
      showAdvancedSettings,
      // Auth
      auth,
      authLoading,
      showChangePassword,
      showSetupPassword,
      currentPassword,
      newPassword,
      confirmNewPassword,
      setupPassword,
      confirmSetupPassword,
      changePasswordError,
      setupPasswordError,
      handleAuthToggle,
      handleChangePassword,
      handleSetupPassword,
      // Species filter
      showSpeciesFilterModal,
      speciesFilterModalConfig,
      openFilterModal,
      closeFilterModal,
      updateFilterList
    }
  }
}
</script>

  <style scoped>
  /* Custom select styling - normalize Safari appearance */
  select {
    -webkit-appearance: none;
    -moz-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3E%3Cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3E%3C/svg%3E");
    background-position: right 0.5rem center;
    background-repeat: no-repeat;
    background-size: 1.5em 1.5em;
    padding-right: 2.5rem;
  }

  /* Custom range slider styling - cross-browser */
  input[type="range"] {
    -webkit-appearance: none;
    appearance: none;
    background: transparent;
  }

  /* Track styling */
  input[type="range"]::-webkit-slider-runnable-track {
    height: 0.5rem;
    border-radius: 9999px;
    background-color: theme('colors.gray.200');
  }

  input[type="range"]::-moz-range-track {
    height: 0.5rem;
    border-radius: 9999px;
    background-color: theme('colors.gray.200');
  }

  /* Thumb styling - Chrome, Safari, Edge */
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 1.25rem;
    height: 1.25rem;
    border-radius: 9999px;
    background-color: theme('colors.blue.600');
    cursor: pointer;
    margin-top: -0.375rem;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  }

  /* Thumb styling - Firefox */
  input[type="range"]::-moz-range-thumb {
    width: 1.25rem;
    height: 1.25rem;
    border-radius: 9999px;
    background-color: theme('colors.blue.600');
    cursor: pointer;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  }

  /* Hover state */
  input[type="range"]:hover::-webkit-slider-thumb {
    background-color: theme('colors.blue.700');
  }

  input[type="range"]:hover::-moz-range-thumb {
    background-color: theme('colors.blue.700');
  }
  </style>
