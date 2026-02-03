<template>
    <div class="settings p-4 max-w-4xl mx-auto">
      <!-- Header with Save/Reset buttons -->
      <div class="flex justify-between items-center mb-4">
        <h1 class="text-xl font-semibold text-gray-800">Settings</h1>
        <div class="flex items-center gap-2">
          <span v-if="saveStatus" :class="saveStatus.type === 'success' ? 'text-green-600' : 'text-red-600'" class="text-sm mr-2">
            {{ saveStatus.message }}
          </span>
          <AppButton
            variant="secondary"
            @click="resetToDefaults"
            :disabled="loading || serviceRestart.isRestarting.value || systemUpdate.isRestarting.value"
          >
            Reset
          </AppButton>
          <AppButton
            @click="saveSettings"
            :loading="loading"
            loading-text="Saving..."
            :disabled="serviceRestart.isRestarting.value || systemUpdate.isRestarting.value"
          >
            Save
            <span v-if="hasUnsavedChanges" class="ml-1.5 w-2 h-2 bg-orange-500 rounded-full inline-block"></span>
          </AppButton>
        </div>
      </div>

      <!-- Error Banner (save errors or restart errors) -->
      <AlertBanner
        :message="settingsSaveError || serviceRestart.restartError.value"
        variant="warning"
        @dismiss="dismissSettingsError"
      />

      <!-- Restart/Update Progress (replaces update available banner when active) -->
      <div
        v-if="(serviceRestart.isRestarting.value || systemUpdate.isRestarting.value) && (serviceRestart.restartMessage.value || systemUpdate.restartMessage.value)"
        class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg"
      >
        <div class="flex items-center gap-2 text-blue-700 text-sm">
          <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span>{{ serviceRestart.restartMessage.value || systemUpdate.restartMessage.value }}</span>
        </div>
      </div>

      <!-- Update Timeout Banner (shown when update is taking longer than expected) -->
      <div
        v-else-if="systemUpdate.restartError.value"
        class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg"
      >
        <div class="flex items-center gap-2 text-amber-700 text-sm">
          <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{{ systemUpdate.restartError.value }}</span>
        </div>
      </div>

      <!-- Update Available Banner (shown when not restarting/updating) -->
      <div
        v-else-if="systemUpdate.showUpdateIndicator.value && systemUpdate.updateInfo.value"
        class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg"
      >
        <div class="flex items-center justify-between">
          <p class="text-sm font-medium text-blue-800"><a href="#system-updates" class="underline hover:text-blue-900">System update</a> available</p>
          <button
            @click="systemUpdate.dismissUpdate()"
            class="text-blue-400 hover:text-blue-600 p-1 -m-1"
            aria-label="Dismiss update reminder"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <div class="space-y-4">
        <!-- Location & Audio Source -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-3">Location & Audio</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Location -->
            <div class="space-y-3">
              <div class="flex gap-3">
                <div class="flex-1">
                  <label for="latitude" class="block text-sm text-gray-600 mb-1">Latitude</label>
                  <input
                    id="latitude"
                    type="text"
                    inputmode="decimal"
                    v-model.number="settings.location.latitude"
                    @input="limitDecimals"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                    placeholder="42.47"
                  >
                </div>
                <div class="flex-1">
                  <label for="longitude" class="block text-sm text-gray-600 mb-1">Longitude</label>
                  <input
                    id="longitude"
                    type="text"
                    inputmode="decimal"
                    v-model.number="settings.location.longitude"
                    @input="limitDecimals"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                    placeholder="-76.45"
                  >
                </div>
              </div>
              <p class="text-xs text-gray-400">Used for species filtering and weather data</p>
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
                  <option
                    v-for="mode in recordingModeOptions"
                    :key="mode.value"
                    :value="mode.value"
                  >{{ mode.label }}</option>
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
              </div>
            </div>
          </div>
        </div>

        <!-- Storage -->
        <div v-if="storage" class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-3">Storage</h2>
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
          <h2 class="text-base font-medium text-gray-800 mb-3">Security</h2>

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
              class="relative inline-flex flex-shrink-0 h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
            >
              <span
                :class="auth.authStatus.value.authEnabled ? 'translate-x-6' : 'translate-x-1'"
                class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              />
            </button>
          </div>

          <!-- Change Password (when auth enabled and setup complete) -->
          <div v-if="auth.authStatus.value.authEnabled && auth.authStatus.value.setupComplete" class="mb-3">
            <button
              @click="showChangePassword = true"
              class="text-sm text-blue-600 hover:text-blue-800"
            >
              Change Password
            </button>
          </div>

          <!-- Auth Error Message -->
          <div v-if="auth.error.value" class="mb-3 p-2 bg-red-50 text-red-600 text-xs rounded-lg">
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
                    <option
                      v-for="len in recordingLengthOptions"
                      :key="len.value"
                      :value="len.value"
                    >{{ len.label }}</option>
                  </select>
                </div>
                <div>
                  <label for="overlap" class="block text-sm text-gray-600 mb-1">Overlap</label>
                  <select
                    id="overlap"
                    v-model.number="settings.audio.overlap"
                    class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  >
                    <option
                      v-for="ov in overlapOptions"
                      :key="ov.value"
                      :value="ov.value"
                    >{{ ov.label }}</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- Display Settings -->
            <div class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-medium text-gray-700 mb-3">Display</h3>
              <div class="flex items-center justify-between">
                <div>
                  <label class="text-sm text-gray-600">Use Metric Units</label>
                  <p class="text-xs text-gray-400">Show weather in °C, km/h, mm (off for °F, mph, in)</p>
                </div>
                <button
                  @click="toggleMetricUnits"
                  :class="settings.display?.use_metric_units !== false ? 'bg-green-600' : 'bg-gray-200'"
                  class="relative inline-flex flex-shrink-0 h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                >
                  <span
                    :class="settings.display?.use_metric_units !== false ? 'translate-x-6' : 'translate-x-1'"
                    class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                  />
                </button>
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
                      {{ getCommonName(species) }}
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
                      {{ getCommonName(species) }}
                    </span>
                    <span v-if="settings.species_filter.blocked_species.length > 5" class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                      +{{ settings.species_filter.blocked_species.length - 5 }} more
                    </span>
                  </div>
                  <p v-else class="text-xs text-gray-400 mt-2 italic">No species blocked</p>
                </div>
              </div>
            </div>

            <!-- BirdWeather Integration -->
            <div class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-medium text-gray-700 mb-3">BirdWeather</h3>
              <div>
                <label for="birdweatherId" class="block text-sm text-gray-600 mb-1">Station ID</label>
                <input
                  id="birdweatherId"
                  type="text"
                  :value="settings.birdweather?.id || ''"
                  @input="updateBirdweatherId($event.target.value)"
                  class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  placeholder="your-station-token"
                >
                <p class="text-xs text-gray-400 mt-1">
                  Share detections with <a href="https://app.birdweather.com/account/stations" target="_blank" rel="noopener noreferrer" class="text-blue-500 hover:underline">BirdWeather.com</a>
                </p>
              </div>
            </div>

            <!-- Import from BirdNET-Pi -->
            <div class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-medium text-gray-700 mb-3">Data Migration</h3>
              <p class="text-xs text-gray-400 mb-2">Import historical detections from BirdNET-Pi.</p>
              <button
                @click="showMigrationModal = true"
                class="w-full py-2 text-sm text-center text-blue-600 hover:text-blue-800 hover:bg-blue-50 border border-blue-200 rounded-lg transition-colors"
              >
                Import from BirdNET-Pi
              </button>
            </div>
          </div>
        </div>

        <!-- Data Management -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <h2 class="text-base font-medium text-gray-800 mb-1">Data</h2>
          <p class="text-sm text-gray-600 mb-3">View and manage all bird detections stored in the database.</p>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <router-link
              to="/table"
              class="block py-2 text-sm text-center text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors"
            >
              View Detections
            </router-link>
            <button
              @click="exportCSV"
              :disabled="exporting"
              class="py-2 text-sm text-center text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors disabled:text-gray-400 disabled:hover:bg-transparent"
            >
              {{ exporting ? 'Exporting...' : 'Export as CSV' }}
            </button>
          </div>
        </div>

        <!-- System Updates -->
        <div id="system-updates" class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-base font-medium text-gray-800">System</h2>
            <div v-if="systemUpdate.versionInfo.value" class="flex items-center gap-2 text-xs text-gray-500">
              <span class="font-mono">{{ systemUpdate.versionInfo.value.current_commit }}</span>
              <span class="px-1.5 py-0.5 bg-gray-100 rounded text-gray-600">{{ systemUpdate.versionInfo.value.current_branch }}</span>
            </div>
          </div>

          <!-- Update Channel Toggle -->
          <div class="flex items-center justify-between mb-4">
            <div>
              <label class="text-sm text-gray-600">Try Experimental Features</label>
              <p class="text-xs text-gray-400">Get newest features before stable release</p>
            </div>
            <button
              @click="toggleUpdateChannel"
              :class="settings.updates?.channel === 'latest' ? 'bg-green-600' : 'bg-gray-200'"
              class="relative inline-flex flex-shrink-0 h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
            >
              <span
                :class="settings.updates?.channel === 'latest' ? 'translate-x-6' : 'translate-x-1'"
                class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              />
            </button>
          </div>

          <!-- Update Available -->
          <div v-if="systemUpdate.updateAvailable.value && systemUpdate.updateInfo.value" class="mb-3 p-3 bg-blue-50 rounded-lg">
            <div class="flex items-center justify-between">
              <div>
                <p class="text-sm font-medium text-blue-800">Update available</p>
                <p class="text-xs text-blue-600">
                  {{ systemUpdate.updateInfo.value.fresh_sync ? 'Major version' :
                     systemUpdate.updateInfo.value.commits_behind === 0 ? `Switch to ${systemUpdate.updateInfo.value.channel} channel` :
                     `${systemUpdate.updateInfo.value.commits_behind} new commits` }}
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
            @click="systemUpdate.checkForUpdates({ force: true })"
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
            <!-- Update Note from deployment/UPDATE_NOTES.json -->
            <div
              v-if="systemUpdate.updateInfo.value?.update_note"
              class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg"
            >
              <p class="text-sm text-amber-800 font-medium mb-1">Important</p>
              <p class="text-sm text-amber-700">{{ systemUpdate.updateInfo.value.update_note }}</p>
            </div>
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
        :speciesList="speciesList"
        :onSave="saveSpeciesFilter"
        :isRestarting="serviceRestart.isRestarting.value"
        :restartMessage="serviceRestart.restartMessage.value"
        :restartError="serviceRestart.restartError.value"
        @close="closeFilterModal"
        @update:modelValue="updateFilterList"
      />

      <!-- Unsaved Changes Modal -->
      <UnsavedChangesModal
        v-if="showUnsavedModal"
        :saving="loading"
        :error="settingsSaveError"
        @save="handleUnsavedSave"
        @discard="handleUnsavedDiscard"
        @cancel="handleUnsavedCancel"
      />

      <!-- Migration Modal -->
      <MigrationModal
        v-if="showMigrationModal"
        @close="showMigrationModal = false"
      />
    </div>
  </template>

  <script>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { useServiceRestart } from '@/composables/useServiceRestart'
import { useAuth } from '@/composables/useAuth'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { limitDecimals } from '@/utils/inputHelpers'
import api, { createLongRequest } from '@/services/api'
import SpeciesFilterModal from '@/components/SpeciesFilterModal.vue'
import AlertBanner from '@/components/AlertBanner.vue'
import AppButton from '@/components/AppButton.vue'
import UnsavedChangesModal from '@/components/UnsavedChangesModal.vue'
import MigrationModal from '@/components/MigrationModal.vue'

export default {
  name: 'Settings',
  components: {
    SpeciesFilterModal,
    AlertBanner,
    AppButton,
    UnsavedChangesModal,
    MigrationModal
  },
  setup() {
    // Composables
    const serviceRestart = useServiceRestart()
    const auth = useAuth()
    const unitSettings = useUnitSettings()

    // Dropdown options (static configuration)
    const recordingModeOptions = [
      { value: 'pulseaudio', label: 'Local Microphone' },
      { value: 'http_stream', label: 'HTTP Stream' },
      { value: 'rtsp', label: 'RTSP Stream' }
    ]
    const recordingLengthOptions = [
      { value: 9, label: '9 seconds' },
      { value: 12, label: '12 seconds' },
      { value: 15, label: '15 seconds' }
    ]
    const overlapOptions = [
      { value: 0.0, label: 'None' },
      { value: 0.5, label: '0.5s' },
      { value: 1.0, label: '1.0s' },
      { value: 1.5, label: '1.5s' },
      { value: 2.0, label: '2.0s' },
      { value: 2.5, label: '2.5s' }
    ]

    // State
    const loading = ref(false)
    const saveStatus = ref(null)
    const settingsSaveError = ref('')
    const recordingMode = ref('pulseaudio')
    const showUpdateConfirm = ref(false)

    // Storage state
    const storage = ref(null)

    // Export state
    const exporting = ref(false)

    // Species list (shared with SpeciesFilterModal)
    const speciesList = ref([])
    const speciesNameMap = ref({})

    // Advanced settings toggle
    const showAdvancedSettings = ref(false)

    // Migration modal state
    const showMigrationModal = ref(false)

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
    // Minimal settings skeleton - actual values loaded from API
    const settings = ref({
      location: {},
      detection: {},
      species_filter: { allowed_species: [], blocked_species: [] },
      audio: {},
      spectrogram: {},
      updates: {},
      display: {},
      birdweather: { id: null }
    })

    // Unsaved changes tracking
    const originalSettings = ref(null)
    const showUnsavedModal = ref(false)
    const navigationResolver = ref(null)

    // Extract only fields that require manual save (excludes auto-save toggles)
    const getComparableSettings = (s) => ({
      location: { latitude: s.location?.latitude, longitude: s.location?.longitude },
      audio: {
        recording_mode: s.audio?.recording_mode,
        stream_url: s.audio?.stream_url,
        rtsp_url: s.audio?.rtsp_url,
        recording_length: s.audio?.recording_length,
        overlap: s.audio?.overlap
      },
      detection: { sensitivity: s.detection?.sensitivity, cutoff: s.detection?.cutoff },
      species_filter: {
        allowed_species: s.species_filter?.allowed_species || [],
        blocked_species: s.species_filter?.blocked_species || []
      },
      birdweather: { id: s.birdweather?.id }
    })

    // Take snapshot of current settings for change detection
    const takeSnapshot = () => {
      originalSettings.value = JSON.parse(JSON.stringify(getComparableSettings(settings.value)))
    }

    // Check for unsaved changes
    const hasUnsavedChanges = computed(() => {
      if (!originalSettings.value) return false
      return JSON.stringify(getComparableSettings(settings.value)) !== JSON.stringify(originalSettings.value)
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

    // Load species list (shared with SpeciesFilterModal)
    const loadSpeciesList = async () => {
      try {
        const { data } = await api.get('/species/available')
        speciesList.value = data.species
        // Build name map for display
        const map = {}
        for (const species of data.species) {
          map[species.scientific_name] = species.common_name
        }
        speciesNameMap.value = map
      } catch (error) {
        console.error('Error loading species list:', error)
      }
    }

    // Get common name for a scientific name (fallback to scientific if not found)
    const getCommonName = (scientificName) => {
      return speciesNameMap.value[scientificName] || scientificName
    }

    // Load settings from API with retry and fallback to defaults
    const loadSettings = async (retryCount = 0) => {
      try {
        loading.value = true
        const { data } = await api.get('/settings')
        settings.value = data
        recordingMode.value = settings.value.audio?.recording_mode || 'pulseaudio'
        // Normalize old "stable" channel to "release" for backward compatibility
        if (settings.value.updates?.channel === 'stable') {
          settings.value.updates.channel = 'release'
        }
        // Ensure updates object exists
        if (!settings.value.updates) {
          settings.value.updates = { channel: 'release' }
        }
        // Ensure display object exists and sync with composable
        if (!settings.value.display) {
          settings.value.display = { use_metric_units: true }
        }
        unitSettings.setUseMetricUnits(settings.value.display.use_metric_units ?? true)
        if (saveStatus.value?.type === 'error') {
          saveStatus.value = null
        }
        // Take snapshot for unsaved changes tracking
        takeSnapshot()
      } catch (error) {
        console.error('Error loading settings:', error)
        if (retryCount < 2) {
          setTimeout(() => loadSettings(retryCount + 1), 2000)
        } else {
          // Fallback to defaults on failure
          try {
            const { data } = await api.get('/settings/defaults')
            settings.value = data
            recordingMode.value = data.audio?.recording_mode || 'pulseaudio'
            // Take snapshot for unsaved changes tracking
            takeSnapshot()
          } catch (defaultsErr) {
            console.error('Failed to load defaults:', defaultsErr)
            showStatus('error', 'Failed to load settings')
          }
        }
      } finally {
        loading.value = false
      }
    }

    // Save settings to API (returns true on success, false on failure)
    const saveSettingsOnly = async () => {
      // Validate stream URLs if using stream modes
      if (recordingMode.value === 'http_stream' && !settings.value.audio.stream_url?.trim()) {
        settingsSaveError.value = 'HTTP Stream requires a Stream URL'
        return false
      }
      if (recordingMode.value === 'rtsp' && !settings.value.audio.rtsp_url?.trim()) {
        settingsSaveError.value = 'RTSP Stream requires an RTSP URL'
        return false
      }

      try {
        loading.value = true
        settingsSaveError.value = ''
        settings.value.location.configured = true
        await api.put('/settings', settings.value)
        // Update snapshot after successful save
        takeSnapshot()
        return true
      } catch (error) {
        console.error('Error saving settings:', error)
        settingsSaveError.value = 'Failed to save settings. Please try again.'
        return false
      } finally {
        loading.value = false
      }
    }

    // Save settings and wait for restart (used by main Save button)
    const saveSettings = async () => {
      if (!hasUnsavedChanges.value) {
        return // Nothing changed, skip save and restart
      }
      const success = await saveSettingsOnly()
      if (success) {
        await serviceRestart.waitForRestart({ autoReload: true, message: 'Updating settings' })
      }
    }

    // Dismiss settings errors (save error or restart error)
    const dismissSettingsError = () => {
      settingsSaveError.value = ''
      serviceRestart.reset()
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

    // Toggle update channel between release and latest (saves immediately, no restart needed)
    const toggleUpdateChannel = async () => {
      try {
        // Toggle the channel
        if (!settings.value.updates) {
          settings.value.updates = { channel: 'release' }
        }
        const newChannel = settings.value.updates.channel === 'latest' ? 'release' : 'latest'

        // Save immediately via dedicated endpoint (no restart needed)
        await api.put('/settings/channel', { channel: newChannel })
        settings.value.updates.channel = newChannel
        showStatus('success', `Switched to ${newChannel === 'latest' ? 'latest' : 'release'} channel`)
      } catch (error) {
        console.error('Error saving channel setting:', error)
        showStatus('error', 'Failed to save channel setting')
      }
    }

    // Toggle metric/imperial units (saves immediately, no restart needed)
    const toggleMetricUnits = async () => {
      try {
        // Ensure display object exists
        if (!settings.value.display) {
          settings.value.display = { use_metric_units: true }
        }
        const newValue = settings.value.display.use_metric_units === false

        // Save immediately via dedicated endpoint (no restart needed)
        await api.put('/settings/units', { use_metric_units: newValue })
        settings.value.display.use_metric_units = newValue

        // Update the shared composable state so other components see the change
        unitSettings.setUseMetricUnits(newValue)

        showStatus('success', `Switched to ${newValue ? 'metric' : 'imperial'} units`)
      } catch (error) {
        console.error('Error saving units setting:', error)
        showStatus('error', 'Failed to save units setting')
      }
    }

    // Handle recording mode change - just update the mode, preserve all URLs
    const onRecordingModeChange = () => {
      settings.value.audio.recording_mode = recordingMode.value
    }

    // Handle BirdWeather ID update
    const updateBirdweatherId = (value) => {
      settings.value.birdweather.id = value || null
    }

    // Confirm and trigger system update
    const confirmUpdate = async () => {
      showUpdateConfirm.value = false
      window.scrollTo({ top: 0, behavior: 'smooth' })
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
      // Clear any restart error state so reopening shows fresh modal
      serviceRestart.reset()
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

    // Save species filter and trigger restart
    const saveSpeciesFilter = async (newList) => {
      // Update the settings with the new list
      updateFilterList(newList)

      // Save settings to API
      try {
        settings.value.location.configured = true
        await api.put('/settings', settings.value)
        // Update snapshot after successful save
        takeSnapshot()
        await serviceRestart.waitForRestart({ autoReload: true, message: 'Updating settings' })
      } catch (error) {
        console.error('Error saving species filter:', error)
        throw error
      }
    }

    // Export detections as CSV
    const exportCSV = async () => {
      try {
        exporting.value = true
        // Use long timeout (5 min) for large exports
        const longApi = createLongRequest()
        const response = await longApi.get('/detections/export', {
          responseType: 'blob'
        })

        // Create download link
        const blob = new Blob([response.data], { type: 'text/csv' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url

        // Extract filename from Content-Disposition header or use default
        const contentDisposition = response.headers['content-disposition']
        let filename = 'birdnet_detections.csv'
        if (contentDisposition) {
          const match = contentDisposition.match(/filename=(.+)/)
          if (match) {
            filename = match[1]
          }
        }

        link.setAttribute('download', filename)
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        window.URL.revokeObjectURL(url)
      } catch (error) {
        console.error('Error exporting CSV:', error)
        showStatus('error', 'Failed to export data')
      } finally {
        exporting.value = false
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

    // Browser beforeunload handler
    const handleBeforeUnload = (e) => {
      if (hasUnsavedChanges.value) {
        e.preventDefault()
        e.returnValue = '' // Required for Chrome
      }
    }

    // Unsaved changes modal handlers
    const handleUnsavedSave = async () => {
      const success = await saveSettingsOnly()
      if (success) {
        // Close modal, cancel navigation, show restart banner like regular save
        showUnsavedModal.value = false
        if (navigationResolver.value) {
          navigationResolver.value(false) // Cancel navigation - page will reload after restart
          navigationResolver.value = null
        }
        // Scroll to top to show restart progress banner
        window.scrollTo({ top: 0, behavior: 'smooth' })
        // Wait for restart with auto-reload (uses existing banner UI)
        await serviceRestart.waitForRestart({ autoReload: true, message: 'Updating settings' })
      }
      // On failure: modal stays open, error shown via settingsSaveError
    }

    const handleUnsavedDiscard = () => {
      showUnsavedModal.value = false
      if (navigationResolver.value) {
        navigationResolver.value(true)
        navigationResolver.value = null
      }
    }

    const handleUnsavedCancel = () => {
      showUnsavedModal.value = false
      if (navigationResolver.value) {
        navigationResolver.value(false)
        navigationResolver.value = null
      }
    }

    // Navigation guard - intercept route changes when there are unsaved changes
    onBeforeRouteLeave(() => {
      if (hasUnsavedChanges.value) {
        showUnsavedModal.value = true
        // Return a Promise - navigation blocked until resolved
        return new Promise((resolve) => {
          navigationResolver.value = resolve
        })
      }
      return true
    })

    // Load settings on component mount
    onMounted(() => {
      loadSettings()
      loadStorageInfo()
      loadSpeciesList()
      systemUpdate.loadVersionInfo()
      auth.checkAuthStatus()
      window.addEventListener('beforeunload', handleBeforeUnload)
    })

    // Cleanup on unmount
    onUnmounted(() => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    })

    return {
      settings,
      loading,
      saveStatus,
      recordingMode,
      showUpdateConfirm,
      storage,
      exporting,
      exportCSV,
      saveSettings,
      resetToDefaults,
      toggleUpdateChannel,
      toggleMetricUnits,
      onRecordingModeChange,
      limitDecimals,
      updateBirdweatherId,
      confirmUpdate,
      systemUpdate,
      serviceRestart,
      settingsSaveError,
      dismissSettingsError,
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
      speciesList,
      openFilterModal,
      closeFilterModal,
      updateFilterList,
      saveSpeciesFilter,
      getCommonName,
      // Dropdown options
      recordingModeOptions,
      recordingLengthOptions,
      overlapOptions,
      // Unsaved changes
      hasUnsavedChanges,
      showUnsavedModal,
      handleUnsavedSave,
      handleUnsavedDiscard,
      handleUnsavedCancel,
      // Migration
      showMigrationModal
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
