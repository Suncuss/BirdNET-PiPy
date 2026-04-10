<template>
  <div class="settings p-4 max-w-4xl mx-auto">
    <div class="flex justify-between items-center mb-4">
      <div class="flex items-baseline gap-3 min-w-0">
        <h1 class="text-xl font-semibold text-gray-800 shrink-0">
          Settings
        </h1>
        <span
          v-if="saveStatus"
          :class="saveStatus.type === 'success' ? 'text-green-600' : 'text-red-600'"
          class="text-sm truncate"
        >
          {{ saveStatus.message }}
        </span>
      </div>
      <AppButton
        class="shrink-0 ml-4"
        :loading="loading"
        loading-text="Saving..."
        :disabled="serviceRestart.isRestarting.value || systemUpdate.isRestarting.value"
        @click="saveSettings"
      >
        Save
        <span
          v-if="hasUnsavedChanges"
          class="ml-1.5 w-2 h-2 bg-orange-500 rounded-full inline-block"
        />
      </AppButton>
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
        <span>{{ serviceRestart.restartMessage.value || systemUpdate.restartMessage.value }}</span>
      </div>
    </div>

    <!-- Update Timeout Banner (shown when update is taking longer than expected) -->
    <div
      v-else-if="systemUpdate.restartError.value"
      class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg"
    >
      <div class="flex items-center gap-2 text-amber-700 text-sm">
        <svg
          class="h-4 w-4 flex-shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
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
        <p class="text-sm font-medium text-blue-800">
          <a
            href="#system-updates"
            class="underline hover:text-blue-900"
          >System update</a> available
        </p>
        <button
          class="text-blue-400 hover:text-blue-600 p-1 -m-1"
          aria-label="Dismiss update reminder"
          @click="systemUpdate.dismissUpdate()"
        >
          <svg
            class="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>

    <div class="space-y-4">
      <!-- Location & Audio -->
      <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-base font-medium text-gray-800">
            Location & Audio
          </h2>
          <div
            v-if="recorderStatus"
            class="flex items-center gap-1.5"
          >
            <span
              class="w-1.5 h-1.5 rounded-full flex-shrink-0"
              :class="recorderDotClass"
            />
            <span
              class="text-xs font-medium"
              :class="recorderStateLabelClass"
            >{{ recorderStateLabel }}</span>
          </div>
        </div>
        <div class="flex gap-3">
          <div class="flex-1">
            <label
              for="latitude"
              class="block text-sm text-gray-600 mb-1"
            >Latitude</label>
            <input
              id="latitude"
              v-model.number="settings.location.latitude"
              type="text"
              inputmode="decimal"
              class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              placeholder="42.47"
              @input="limitDecimals"
            >
          </div>
          <div class="flex-1">
            <label
              for="longitude"
              class="block text-sm text-gray-600 mb-1"
            >Longitude</label>
            <input
              id="longitude"
              v-model.number="settings.location.longitude"
              type="text"
              inputmode="decimal"
              class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              placeholder="-76.45"
              @input="limitDecimals"
            >
          </div>
          <div
            v-if="settings.location.timezone"
            class="hidden sm:block flex-1"
          >
            <label class="block text-sm text-gray-600 mb-1">Timezone</label>
            <div class="px-3 py-2 text-sm text-gray-500 bg-gray-50 rounded-lg border border-gray-200">
              {{ settings.location.timezone }}
            </div>
          </div>
        </div>

        <hr class="my-3 border-gray-100">

        <!-- Audio sources -->
        <label class="block text-sm text-gray-600 mb-1">Sources<span v-if="hasInactiveSource" class="text-xs text-gray-400 font-normal"> — highlighted sources are active</span></label>
        <div class="flex flex-wrap gap-2">
          <!-- Source pills (click to edit) -->
          <button
            v-for="source in (settings.audio.sources || [])"
            :key="source.id"
            type="button"
            class="group inline-flex items-center rounded-full border cursor-pointer transition-all duration-200"
            :class="source.enabled
              ? 'border-blue-300 bg-blue-50 hover:bg-blue-100 shadow-sm'
              : 'border-gray-200 bg-gray-50 hover:bg-gray-100 opacity-50'"
            title="Click to edit"
            @click="openEditSource(source.id)"
          >
            <span
              class="px-3.5 py-1.5 text-sm font-medium truncate max-w-48 md:group-hover:pr-1 transition-[padding] duration-200"
              :class="source.enabled ? 'text-gray-800' : 'text-gray-600'"
              :title="source.type === 'rtsp' ? source.url : 'Local Microphone'"
            >{{ source.label || (source.type === 'rtsp' ? 'RTSP Stream' : 'Local Mic') }}</span>
            <!-- Edit icon: hover-reveal on desktop, always visible on mobile -->
            <span
              class="text-gray-400 group-hover:text-blue-600 flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out p-1 pr-2.5 md:max-w-0 md:p-0 md:pr-0 md:group-hover:max-w-8 md:group-hover:p-1 md:group-hover:pr-2.5"
            >
              <svg
                class="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487z"
                />
              </svg>
            </span>
          </button>

          <!-- Add source pill -->
          <button
            type="button"
            class="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-dashed border-gray-200 text-xs text-gray-400 hover:text-blue-600 hover:border-blue-300 hover:bg-blue-50 transition-colors"
            @click="openAddSource"
          >
            <svg
              class="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="2"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 4.5v15m7.5-7.5h-15"
              />
            </svg>
            Add
          </button>
        </div>

        <!-- Stream Source Modal -->
        <StreamSourceModal
          v-if="showStreamModal"
          :source="editingSource"
          :existing-sources="settings.audio.sources || []"
          @close="showStreamModal = false"
          @add="handleStreamAdd"
          @save="handleStreamSave"
          @delete="handleStreamDelete"
        />

        <!-- Error details (only when source is unhealthy) -->
        <details
          v-if="showRecorderError"
          open
          class="mt-2.5"
        >
          <summary class="text-xs text-gray-400 cursor-pointer hover:text-gray-600 select-none">
            <span class="show-label">Show error details</span>
            <span class="hide-label">Hide error details</span>
          </summary>
          <div class="mt-1 space-y-1.5 relative group">
            <div
              v-for="(err, idx) in sourceErrors"
              :key="idx"
            >
              <span
                class="text-xs font-medium"
                :class="err.state === RECORDER_STATES.STOPPED ? 'text-red-400' : 'text-amber-500'"
              >{{ err.label }}</span>
              <pre class="text-xs text-gray-500 bg-gray-50 rounded-md p-2 overflow-x-auto whitespace-pre-wrap break-words font-mono">{{ err.message }}</pre>
            </div>
            <button
              class="absolute top-0 right-0 p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors"
              title="Copy to clipboard"
              @click="copyErrorToClipboard"
            >
              <svg
                class="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  v-if="!errorCopied"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
                <path
                  v-else
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </button>
          </div>
        </details>
      </div>

      <!-- Storage -->
      <div
        v-if="storage"
        class="bg-white rounded-lg shadow-sm border border-gray-100 p-5"
      >
        <h2 class="text-base font-medium text-gray-800 mb-3">
          Storage
        </h2>
        <div class="flex justify-between items-center mb-2">
          <span class="text-sm text-gray-600">Disk Usage</span>
          <span class="text-sm font-medium text-gray-800">{{ storage.percent_used }}%</span>
        </div>
        <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="storage.percent_used >= 75 ? 'bg-orange-500' : 'bg-green-500'"
            :style="{ width: storage.percent_used + '%' }"
          />
        </div>
        <div class="flex justify-between mt-2 text-xs text-gray-500">
          <span>{{ storage.used_gb }}GB used</span>
          <span>{{ storage.free_gb }}GB free of {{ storage.total_gb }}GB</span>
        </div>
        <p class="text-xs text-gray-400 mt-3">
          Auto-cleanup removes oldest recordings when usage exceeds {{ settings.storage.trigger_percent }}%.
        </p>
      </div>

      <!-- Security (Collapsible) -->
      <CollapsibleSection
        title="Security"
        subtitle="Authentication and public access controls"
        body-class="border-t border-gray-100 p-5 space-y-4"
      >
        <!-- Auth Toggle -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm text-gray-600">Require Authentication</label>
            <p class="text-xs text-gray-400">
              Protect features with password
            </p>
          </div>
          <ToggleSwitch
            :model-value="auth.authStatus.value.authEnabled"
            :disabled="authLoading"
            @update:model-value="handleAuthToggle"
          />
        </div>

        <!-- Public Access Options (when auth enabled) -->
        <div
          v-if="auth.authStatus.value.authEnabled"
          class="bg-gray-50 rounded-lg p-3 space-y-2"
        >
          <p class="text-xs text-gray-500">
            Public access (no login required)
          </p>
          <div
            v-for="feature in accessFeatures"
            :key="feature.key"
            class="flex items-center justify-between"
          >
            <label class="text-sm text-gray-600">{{ feature.label }}</label>
            <ToggleSwitch
              :model-value="settings.access[feature.key]"
              size="sm"
              @update:model-value="toggleFeatureAccess(feature.key)"
            />
          </div>
        </div>

        <!-- Change Password (when auth enabled and setup complete) -->
        <button
          v-if="auth.authStatus.value.authEnabled && auth.authStatus.value.setupComplete"
          class="text-sm text-blue-600 hover:text-blue-800"
          @click="showChangePassword = true"
        >
          Change Password
        </button>

        <!-- Auth Error Message -->
        <div
          v-if="auth.error.value"
          class="p-2 bg-red-50 text-red-600 text-xs rounded-lg"
        >
          {{ auth.error.value }}
        </div>

        <!-- Password Reset Help -->
        <p class="text-xs text-gray-400">
          Forgot password? Create a file named <code class="bg-gray-100 px-1 rounded">RESET_PASSWORD</code>
          in <code class="bg-gray-100 px-1 rounded">data/config/</code> on your Pi to reset.
        </p>
      </CollapsibleSection>

      <!-- Detection (Collapsible) -->
      <CollapsibleSection
        title="Detection"
        subtitle="Model, sensitivity, and recording settings"
        body-class="border-t border-gray-100 p-5 space-y-6"
      >
        <!-- Model Selection -->
        <div>
          <label
            for="modelType"
            class="block text-sm text-gray-600 mb-1"
          >Detection Model</label>
          <select
            id="modelType"
            v-model="settings.model.type"
            class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
            @change="onModelTypeChange"
          >
            <option
              v-for="m in modelTypeOptions"
              :key="m.value"
              :value="m.value"
            >
              {{ m.label }}
            </option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            V3.0 is a developer preview with 11K species. Model will be downloaded on first use (~541 MB).
          </p>
        </div>

        <!-- Sensitivity, Confidence & Location Filter Threshold -->
        <div class="pt-4 border-t border-gray-100">
          <div
            class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          >
            <div>
              <div class="flex justify-between items-center mb-2">
                <label
                  for="sensitivity"
                  class="text-sm text-gray-600"
                >Sensitivity</label>
                <span class="text-sm font-medium text-gray-800">{{ settings.detection.sensitivity }}</span>
              </div>
              <input
                id="sensitivity"
                v-model.number="settings.detection.sensitivity"
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                class="w-full h-2 rounded-lg cursor-pointer"
              >
              <p class="text-xs text-gray-400 mt-1">
                Higher = more detections
              </p>
            </div>
            <div>
              <div class="flex justify-between items-center mb-2">
                <label
                  for="cutoff"
                  class="text-sm text-gray-600"
                >Confidence Threshold</label>
                <span class="text-sm font-medium text-gray-800">{{ settings.detection.cutoff }}</span>
              </div>
              <input
                id="cutoff"
                v-model.number="settings.detection.cutoff"
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                class="w-full h-2 rounded-lg cursor-pointer"
              >
              <p class="text-xs text-gray-400 mt-1">
                Minimum confidence to report
              </p>
            </div>
            <!-- Location Filter Threshold (V2.4 meta-model / V3.0 geomodel) -->
            <div>
              <div class="flex justify-between items-center mb-2">
                <label
                  for="speciesFilterThreshold"
                  class="text-sm text-gray-600"
                >
                  Location Filter
                </label>
                <span class="text-sm font-medium text-gray-800">
                  {{ settings.detection.species_filter_threshold }}
                </span>
              </div>
              <input
                id="speciesFilterThreshold"
                v-model.number="settings.detection.species_filter_threshold"
                type="range"
                min="0.01"
                :max="settings.model?.type === 'birdnet_v3' ? 0.30 : 0.10"
                step="0.01"
                class="w-full h-2 rounded-lg cursor-pointer"
              >
              <p class="text-xs text-gray-400 mt-1">
                Higher = stricter location filtering
              </p>
            </div>
          </div>
        </div>

        <!-- Recording Settings -->
        <div class="pt-4 border-t border-gray-100">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label
                for="recordingLength"
                class="block text-sm text-gray-600 mb-1"
              >Chunk Length</label>
              <select
                id="recordingLength"
                v-model.number="settings.audio.recording_length"
                class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              >
                <option
                  v-for="len in recordingLengthOptions"
                  :key="len.value"
                  :value="len.value"
                >
                  {{ len.label }}
                </option>
              </select>
            </div>
            <div>
              <label
                for="overlap"
                class="block text-sm text-gray-600 mb-1"
              >Overlap</label>
              <select
                id="overlap"
                v-model.number="settings.audio.overlap"
                class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              >
                <option
                  v-for="ov in overlapOptions"
                  :key="ov.value"
                  :value="ov.value"
                >
                  {{ ov.label }}
                </option>
              </select>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      <!-- Species Filter (Collapsible) -->
      <CollapsibleSection
        title="Species Filter"
        subtitle="Allowed and blocked species lists"
      >
        <div class="space-y-3">
          <!-- Allowed Species -->
          <div class="border border-gray-200 rounded-lg p-3">
            <div class="flex items-center justify-between">
              <div>
                <h4 class="text-sm font-medium text-gray-700">
                  Allowed Species
                </h4>
                <p class="text-xs text-gray-400">
                  Only detect these species (leave empty for all)
                </p>
              </div>
              <button
                class="px-3 py-1.5 text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors"
                @click="openFilterModal('allowed')"
              >
                Edit
              </button>
            </div>
            <div
              v-if="settings.species_filter?.allowed_species?.length"
              class="flex flex-wrap gap-1.5 mt-2"
            >
              <span
                v-for="species in settings.species_filter.allowed_species.slice(0, 5)"
                :key="species"
                class="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full"
              >
                {{ getCommonName(species) }}
              </span>
              <span
                v-if="settings.species_filter.allowed_species.length > 5"
                class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full"
              >
                +{{ settings.species_filter.allowed_species.length - 5 }} more
              </span>
            </div>
            <p
              v-else
              class="text-xs text-gray-400 mt-2 italic"
            >
              All species for your location
            </p>
          </div>

          <!-- Blocked Species -->
          <div class="border border-gray-200 rounded-lg p-3">
            <div class="flex items-center justify-between">
              <div>
                <h4 class="text-sm font-medium text-gray-700">
                  Blocked Species
                </h4>
                <p class="text-xs text-gray-400">
                  Never detect these species
                </p>
              </div>
              <button
                class="px-3 py-1.5 text-xs bg-red-50 text-red-600 hover:bg-red-100 rounded-lg transition-colors"
                @click="openFilterModal('blocked')"
              >
                Edit
              </button>
            </div>
            <div
              v-if="settings.species_filter?.blocked_species?.length"
              class="flex flex-wrap gap-1.5 mt-2"
            >
              <span
                v-for="species in settings.species_filter.blocked_species.slice(0, 5)"
                :key="species"
                class="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded-full"
              >
                {{ getCommonName(species) }}
              </span>
              <span
                v-if="settings.species_filter.blocked_species.length > 5"
                class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full"
              >
                +{{ settings.species_filter.blocked_species.length - 5 }} more
              </span>
            </div>
            <p
              v-else
              class="text-xs text-gray-400 mt-2 italic"
            >
              No species blocked
            </p>
          </div>
        </div>
      </CollapsibleSection>

      <!-- Notifications (Collapsible) -->
      <CollapsibleSection
        title="Notifications"
        subtitle="Get alerts when birds are detected"
      >
        <!-- Apprise URLs -->
        <div class="mb-4">
          <label class="block text-sm text-gray-600 mb-1">Notification Services</label>

          <!-- Service pills -->
          <div class="flex flex-wrap gap-2">
            <div
              v-for="(url, index) in (settings.notifications.apprise_urls || [])"
              :key="index"
              role="button"
              tabindex="0"
              class="group inline-flex items-center rounded-full border border-blue-200 bg-blue-50 cursor-pointer transition-colors"
              :title="maskAppriseUrl(url)"
              @click="openEditNotification(index)"
              @keydown.enter="openEditNotification(index)"
              @keydown.space.prevent="openEditNotification(index)"
            >
              <span
                class="pl-3.5 pr-3 py-1.5 text-sm font-medium text-gray-800 truncate max-w-48 md:group-hover:pr-1 transition-[padding] duration-200"
              >{{ appriseServiceName(url) }}</span>
              <button
                type="button"
                class="text-gray-400 hover:text-blue-600 flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out p-1 pr-2.5 md:max-w-0 md:p-0 md:pr-0 md:group-hover:max-w-8 md:group-hover:p-1 md:group-hover:pr-2.5"
                title="Edit"
                @click.stop="openEditNotification(index)"
              >
                <svg
                  class="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487z"
                  />
                </svg>
              </button>
            </div>

            <!-- Add Service pill -->
            <button
              type="button"
              class="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-dashed border-gray-200 text-xs text-gray-400 hover:text-blue-600 hover:border-blue-300 hover:bg-blue-50 transition-colors"
              @click="showAddNotificationModal = true"
            >
              <svg
                class="w-3.5 h-3.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M12 4.5v15m7.5-7.5h-15"
                />
              </svg>
              Add
            </button>
          </div>
          <p class="text-xs text-gray-400 mt-1">
            Powered by <a
              href="https://appriseit.com/"
              target="_blank"
              rel="noopener noreferrer"
              class="text-blue-500 hover:underline"
            >Apprise</a> — supports 100+ services
          </p>
        </div>

        <!-- Trigger: Every Detection -->
        <div class="flex items-center justify-between py-2 border-t border-gray-100">
          <div>
            <label class="text-sm text-gray-600">Every Detection</label>
            <p class="text-xs text-gray-400">
              Alert on each detection
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.notifications.every_detection"
            @update:model-value="toggleNotificationSetting('every_detection')"
          />
        </div>

        <!-- Rate Limit (visible when Every Detection is on) -->
        <div
          v-if="settings.notifications.every_detection"
          class="pl-4 pb-2"
        >
          <label class="block text-xs text-gray-500 mb-1.5">Cooldown per species</label>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="opt in rateLimitOptions"
              :key="opt.value"
              :class="settings.notifications.rate_limit_seconds === opt.value
                ? 'bg-blue-100 text-blue-700 border-blue-200'
                : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'"
              class="px-2.5 py-1 text-xs rounded-full border transition-colors"
              @click="setRateLimit(opt.value)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>

        <!-- Trigger: First of Day -->
        <div class="flex items-center justify-between py-2 border-t border-gray-100">
          <div>
            <label class="text-sm text-gray-600">First of Day</label>
            <p class="text-xs text-gray-400">
              First sighting of each species per day
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.notifications.first_of_day"
            @update:model-value="toggleNotificationSetting('first_of_day')"
          />
        </div>

        <!-- Trigger: New Species -->
        <div class="flex items-center justify-between py-2 border-t border-gray-100">
          <div>
            <label class="text-sm text-gray-600">New Species</label>
            <p class="text-xs text-gray-400">
              Species never seen before
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.notifications.new_species"
            @update:model-value="toggleNotificationSetting('new_species')"
          />
        </div>

        <!-- Trigger: Rare Species -->
        <div class="flex items-center justify-between py-2 border-t border-gray-100">
          <div>
            <label class="text-sm text-gray-600">Rare Species</label>
            <p class="text-xs text-gray-400">
              Uncommon species for your area
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.notifications.rare_species"
            @update:model-value="toggleNotificationSetting('rare_species')"
          />
        </div>

        <!-- Rare Species Options (visible when Rare Species is on) -->
        <div
          v-if="settings.notifications.rare_species"
          class="pl-4 pb-2 space-y-2"
        >
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Fewer than N sightings</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="opt in rareThresholdOptions"
                :key="opt"
                :class="settings.notifications.rare_threshold === opt
                  ? 'bg-blue-100 text-blue-700 border-blue-200'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'"
                class="px-2.5 py-1 text-xs rounded-full border transition-colors"
                @click="setRareThreshold(opt)"
              >
                {{ opt }}
              </button>
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">In the past</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="opt in rareWindowOptions"
                :key="opt.value"
                :class="settings.notifications.rare_window_days === opt.value
                  ? 'bg-blue-100 text-blue-700 border-blue-200'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'"
                class="px-2.5 py-1 text-xs rounded-full border transition-colors"
                @click="setRareWindow(opt.value)"
              >
                {{ opt.label }}
              </button>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      <!-- Integrations (Collapsible) -->
      <CollapsibleSection
        title="Integrations"
        subtitle="External service connections"
      >
        <!-- BirdWeather -->
        <div>
          <label
            for="birdweatherId"
            class="block text-sm text-gray-600 mb-1"
          >BirdWeather Station ID</label>
          <input
            id="birdweatherId"
            type="text"
            :value="settings.birdweather?.id || ''"
            class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
            placeholder="your-station-token"
            @input="updateBirdweatherId($event.target.value)"
          >
          <p class="text-xs text-gray-400 mt-1">
            Share detections with <a
              href="https://app.birdweather.com/account/stations"
              target="_blank"
              rel="noopener noreferrer"
              class="text-blue-500 hover:underline"
            >BirdWeather.com</a>
          </p>
        </div>
      </CollapsibleSection>

      <!-- Personalization (Collapsible) -->
      <CollapsibleSection
        title="Personalization"
        subtitle="Units and display preferences"
        body-class="border-t border-gray-100 p-5 space-y-6"
      >
        <div>
          <label
            for="stationName"
            class="block text-sm text-gray-600 mb-1"
          >Station Name</label>
          <input
            id="stationName"
            v-model="settings.display.station_name"
            type="text"
            maxlength="40"
            placeholder="e.g. Backyard, Cabin, Rooftop"
            class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
          >
          <p class="text-xs text-gray-400 mt-1">
            Shown in the navbar to identify this station. Save to apply.
          </p>
        </div>

        <div class="pt-4 border-t border-gray-100">
          <label
            for="birdNameLanguage"
            class="block text-sm text-gray-600 mb-1"
          >Bird Name Language</label>
          <select
            id="birdNameLanguage"
            v-model="settings.display.bird_name_language"
            class="block w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
          >
            <option
              v-for="option in birdNameLanguageOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            Used for bird names shown across the app. Save to apply.
          </p>
        </div>

        <div class="pt-4 border-t border-gray-100 flex items-center justify-between">
          <div>
            <label class="text-sm text-gray-600">Use Metric Units</label>
            <p class="text-xs text-gray-400">
              Show weather in °C, km/h, mm (off for °F, mph, in)
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.display?.use_metric_units !== false"
            :disabled="metricUnitsSaving"
            @update:model-value="toggleMetricUnits"
          />
        </div>
      </CollapsibleSection>

      <!-- Management (Collapsible) -->
      <CollapsibleSection
        title="Management"
        subtitle="System logs and service controls"
      >
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <!-- System Logs Button -->
          <button
            class="py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors"
            @click="showLogsModal = true"
          >
            System Logs
          </button>

          <!-- Restart Services Button -->
          <button
            class="py-2 text-sm text-gray-600 hover:text-gray-800 border border-gray-200 rounded-lg transition-colors"
            :class="serviceRestart.isRestarting.value
              ? 'opacity-50 cursor-not-allowed'
              : 'hover:text-red-600 hover:border-red-200 hover:bg-red-50'"
            :disabled="serviceRestart.isRestarting.value"
            @click="manualRestart"
          >
            {{ serviceRestart.isRestarting.value ? 'Restarting...' : 'Restart Services' }}
          </button>
        </div>
      </CollapsibleSection>

      <!-- Data Management -->
      <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-5">
        <h2 class="text-base font-medium text-gray-800 mb-1">
          Data
        </h2>
        <p class="text-sm text-gray-600 mb-3">
          Manage bird detection data.
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            class="py-2 text-sm text-center text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors"
            @click="showMigrationModal = true"
          >
            Import from BirdNET-Pi
          </button>
          <button
            :disabled="exporting"
            class="py-2 text-sm text-center text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors disabled:text-gray-400 disabled:hover:bg-transparent"
            @click="exportCSV"
          >
            {{ exporting ? 'Exporting...' : 'Export as CSV' }}
          </button>
        </div>
      </div>

      <!-- System -->
      <div
        id="system-updates"
        class="bg-white rounded-lg shadow-sm border border-gray-100 p-5"
      >
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-base font-medium text-gray-800">
            System
          </h2>
          <div
            v-if="systemUpdate.versionInfo.value"
            class="flex items-center gap-2 text-xs text-gray-500"
          >
            <span
              v-if="isHomeAssistantMode"
              class="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"
            >
              Mode: Home Assistant
            </span>
            <a
              v-if="systemUpdate.versionInfo.value"
              :href="versionChangelogUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="font-mono hover:text-blue-600 transition-colors"
            >
              {{ systemUpdate.versionInfo.value.version && systemUpdate.versionInfo.value.version !== 'unknown' ? `v${systemUpdate.versionInfo.value.version}` : '' }}
              <template v-if="!isHomeAssistantMode">({{ systemUpdate.versionInfo.value.current_commit }})</template>
              <template v-if="isHomeAssistantMode && systemUpdate.versionInfo.value.current_commit !== 'unknown'">({{ systemUpdate.versionInfo.value.current_commit.slice(0, 7) }})</template>
            </a>
            <span
              v-if="!isHomeAssistantMode && systemUpdate.versionInfo.value"
              class="px-1.5 py-0.5 bg-gray-100 rounded text-gray-600"
            >{{ systemUpdate.versionInfo.value.current_branch }}</span>
          </div>
        </div>

        <!-- Update Channel Toggle -->
        <div
          v-if="!isHomeAssistantMode"
          class="flex items-center justify-between mb-4"
        >
          <div>
            <label class="text-sm text-gray-600">Try Experimental Features</label>
            <p class="text-xs text-gray-400">
              Get newest features before stable release
            </p>
          </div>
          <ToggleSwitch
            :model-value="settings.updates?.channel === 'latest'"
            :disabled="updateChannelSaving"
            @update:model-value="toggleUpdateChannel"
          />
        </div>

        <!-- Update Available -->
        <div
          v-if="systemUpdate.updateAvailable.value && systemUpdate.updateInfo.value"
          class="mb-3 p-3 bg-blue-50 rounded-lg"
        >
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-blue-800">
                Update available
              </p>
              <p class="text-xs text-blue-600">
                {{ systemUpdate.updateInfo.value.fresh_sync ? 'Major version' :
                  systemUpdate.updateInfo.value.commits_behind === 0 ? `Switch to ${systemUpdate.updateInfo.value.channel} channel` :
                  `${systemUpdate.updateInfo.value.commits_behind} new commits` }}
              </p>
            </div>
            <button
              :disabled="systemUpdate.updating.value"
              class="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
              @click="showUpdateConfirm = true"
            >
              Update
            </button>
          </div>
          <!-- Commit preview - collapsible -->
          <details
            v-if="systemUpdate.updateInfo.value.preview_commits?.length > 0"
            class="mt-2"
          >
            <summary class="text-xs text-blue-600 cursor-pointer hover:text-blue-800">
              View changes
            </summary>
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
          v-if="!isHomeAssistantMode"
          :disabled="systemUpdate.checking.value || systemUpdate.updating.value"
          class="w-full py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors disabled:text-gray-400 disabled:hover:bg-transparent"
          @click="systemUpdate.checkForUpdates({ force: true })"
        >
          <span v-if="systemUpdate.checking.value">Checking...</span>
          <span v-else-if="systemUpdate.updating.value">Updating...</span>
          <span v-else>Check for Updates</span>
        </button>

        <!-- HA Addon GitHub Link (HA mode only) -->
        <a
          v-if="isHomeAssistantMode"
          href="https://github.com/alexbelgium/hassio-addons/tree/master/birdnet-pipy"
          target="_blank"
          rel="noopener noreferrer"
          class="w-full py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <svg
            class="w-4 h-4"
            viewBox="0 0 16 16"
            fill="currentColor"
          ><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>
          HA Addon Repository
        </a>

        <!-- GitHub Repository Link -->
        <a
          :href="repositoryUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-2 w-full py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-50 border border-gray-200 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <svg
            class="w-4 h-4"
            viewBox="0 0 16 16"
            fill="currentColor"
          ><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>
          BirdNET-PiPy Repository
        </a>

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
    <div
      v-if="showChangePassword"
      class="fixed inset-0 z-50 overflow-y-auto"
    >
      <div
        class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        @click="showChangePassword = false"
      />
      <div class="flex min-h-full items-center justify-center p-4">
        <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">
            Change Password
          </h3>

          <div
            v-if="changePasswordError"
            class="mb-4 p-2 bg-red-50 text-red-600 text-sm rounded-lg"
          >
            {{ changePasswordError }}
          </div>

          <form
            class="space-y-4"
            @submit.prevent="handleChangePassword"
          >
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
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                @click="showChangePassword = false"
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
    <div
      v-if="showSetupPassword"
      class="fixed inset-0 z-50 overflow-y-auto"
    >
      <div
        class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        @click="showSetupPassword = false"
      />
      <div class="flex min-h-full items-center justify-center p-4">
        <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-2">
            Set Up Authentication
          </h3>
          <p class="text-sm text-gray-600 mb-4">
            Create a password to protect your settings and audio stream.
          </p>

          <div
            v-if="setupPasswordError"
            class="mb-4 p-2 bg-red-50 text-red-600 text-sm rounded-lg"
          >
            {{ setupPasswordError }}
          </div>

          <form
            class="space-y-4"
            @submit.prevent="handleSetupPassword"
          >
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
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                @click="showSetupPassword = false"
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
    <div
      v-if="showUpdateConfirm"
      class="fixed inset-0 z-50 overflow-y-auto"
    >
      <div
        class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        @click="showUpdateConfirm = false"
      />
      <div class="flex min-h-full items-center justify-center p-4">
        <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-2">
            Update System?
          </h3>
          <p class="text-sm text-gray-600 mb-4">
            This will restart all services. Detection will pause briefly during the update.
          </p>
          <!-- Update Note from deployment/UPDATE_NOTES.json -->
          <div
            v-if="systemUpdate.updateInfo.value?.update_note"
            class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg"
          >
            <p class="text-sm text-amber-800 font-medium mb-1">
              Important
            </p>
            <p class="text-sm text-amber-700">
              {{ systemUpdate.updateInfo.value.update_note }}
            </p>
          </div>
          <div class="flex gap-3">
            <button
              class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              @click="showUpdateConfirm = false"
            >
              Cancel
            </button>
            <button
              class="flex-1 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              @click="confirmUpdate"
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
      v-model="speciesFilterModalConfig.list"
      :title="speciesFilterModalConfig.title"
      :description="speciesFilterModalConfig.description"
      :species-list="speciesList"
      :on-save="saveSpeciesFilter"
      :is-restarting="serviceRestart.isRestarting.value"
      :restart-message="serviceRestart.restartMessage.value"
      :restart-error="serviceRestart.restartError.value"
      @close="closeFilterModal"
      @update:model-value="updateFilterList"
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

    <!-- Add/Edit Notification Modal -->
    <AddNotificationModal
      v-if="showAddNotificationModal"
      :edit-url="editingNotificationUrl"
      @close="closeNotificationModal"
      @add="handleAddNotificationUrl"
      @save="handleSaveNotificationUrl"
      @delete="handleDeleteNotificationFromModal"
    />

    <!-- Confirm Remove Notification URL -->
    <ConfirmModal
      v-if="confirmRemoveIndex !== null"
      title="Remove Service?"
      message="This notification service will be removed. You can re-add it later."
      confirm-label="Remove"
      @confirm="confirmRemoveAppriseUrl"
      @cancel="cancelRemoveAppriseUrl"
    />

    <!-- System Logs Modal -->
    <LogsModal
      v-if="showLogsModal"
      @close="showLogsModal = false"
    />
  </div>
</template>

  <script>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { io } from 'socket.io-client'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { requestRestart, useServiceRestart } from '@/composables/useServiceRestart'
import { useAuth } from '@/composables/useAuth'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { useAppStatus } from '@/composables/useAppStatus'
import { limitDecimals } from '@/utils/inputHelpers'
import { RECORDER_STATES } from '@/utils/recorderStates'
import api, { createLongRequest } from '@/services/api'
import SpeciesFilterModal from '@/components/SpeciesFilterModal.vue'
import AlertBanner from '@/components/AlertBanner.vue'
import AppButton from '@/components/AppButton.vue'
import UnsavedChangesModal from '@/components/UnsavedChangesModal.vue'
import MigrationModal from '@/components/MigrationModal.vue'
import AddNotificationModal from '@/components/AddNotificationModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import StreamSourceModal from '@/components/StreamSourceModal.vue'
import CollapsibleSection from '@/components/CollapsibleSection.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import LogsModal from '@/components/LogsModal.vue'
import { SCHEME_TO_SERVICE_NAME } from '@/utils/notificationServices'

const DEFAULT_REPOSITORY_URL = 'https://github.com/Suncuss/BirdNET-PiPy'

export default {
  name: 'Settings',
  components: {
    SpeciesFilterModal,
    AlertBanner,
    AppButton,
    UnsavedChangesModal,
    MigrationModal,
    AddNotificationModal,
    ConfirmModal,
    StreamSourceModal,
    CollapsibleSection,
    ToggleSwitch,
    LogsModal
  },
  setup() {
    // Composables
    const serviceRestart = useServiceRestart()
    const auth = useAuth()
    const unitSettings = useUnitSettings()
    const appStatus = useAppStatus()

    // Dropdown options (static configuration)
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
    const modelTypeOptions = [
      { value: 'birdnet', label: 'BirdNET v2.4 (6K species)' },
      { value: 'birdnet_v3', label: 'BirdNET v3.0 (11K species, preview)' }
    ]
    const FILTER_DEFAULTS = { birdnet: 0.03, birdnet_v3: 0.15 }
    const onModelTypeChange = () => {
      settings.value.detection.species_filter_threshold =
        FILTER_DEFAULTS[settings.value.model.type] ?? 0.03
    }

    // Notification pill options
    const rateLimitOptions = [
      { value: 0, label: 'None' },
      { value: 60, label: '1 min' },
      { value: 300, label: '5 min' },
      { value: 900, label: '15 min' },
      { value: 3600, label: '1 hr' }
    ]
    const rareThresholdOptions = [1, 2, 3, 5, 10]
    const rareWindowOptions = [
      { value: 7, label: '7 days' },
      { value: 14, label: '14 days' },
      { value: 30, label: '30 days' },
      { value: 90, label: '90 days' }
    ]

    // State
    const loading = ref(false)
    const saveStatus = ref(null)
    const settingsSaveError = ref('')
    const showUpdateConfirm = ref(false)
    const showLogsModal = ref(false)

    // Storage state
    const storage = ref(null)

    // Recorder health status (populated via WebSocket + REST)
    const recorderStatus = ref(null)
    const errorCopied = ref(false)
    let settingsSocket = null

    // Stream source modal state
    const showStreamModal = ref(false)
    const editingSource = ref(null)

    const hasMicSource = computed(() =>
      (settings.value.audio.sources || []).some(s => s.type === 'pulseaudio')
    )

    const hasInactiveSource = computed(() => {
      const sources = settings.value.audio?.sources || []
      return sources.length > 1 && sources.some(s => !s.enabled)
    })

    const sourceErrors = computed(() => {
      const sources = recorderStatus.value?.sources
      if (!sources) return []
      return Object.values(sources)
        .filter(s => s.state !== RECORDER_STATES.RUNNING && s.last_error_message)
        .map(s => ({ label: s.label, state: s.state, message: s.last_error_message }))
    })

    const showRecorderError = computed(() => {
      if (!recorderStatus.value) return false
      if (serviceRestart.isRestarting.value) return false
      if (recorderStatus.value.state === RECORDER_STATES.RUNNING) return false
      return sourceErrors.value.length > 0
    })

    const recorderDotClass = computed(() => {
      if (serviceRestart.isRestarting.value) return 'bg-gray-300'
      const state = recorderStatus.value?.state
      if (state === RECORDER_STATES.RUNNING) return 'bg-green-500 animate-pulse'
      if (state === RECORDER_STATES.DEGRADED) return 'bg-amber-500'
      if (state === RECORDER_STATES.STOPPED) return 'bg-red-500'
      return 'bg-gray-300'
    })

    const recorderStateLabel = computed(() => {
      if (serviceRestart.isRestarting.value) return 'Unavailable'
      const state = recorderStatus.value?.state
      if (state === RECORDER_STATES.RUNNING) return 'Audio Healthy'
      if (state === RECORDER_STATES.DEGRADED) return 'Audio Degraded'
      if (state === RECORDER_STATES.STOPPED) return 'Audio Stopped'
      return 'Audio Unknown'
    })

    const recorderStateLabelClass = computed(() => {
      if (serviceRestart.isRestarting.value) return 'text-gray-400'
      const state = recorderStatus.value?.state
      if (state === RECORDER_STATES.RUNNING) return 'text-green-600'
      if (state === RECORDER_STATES.DEGRADED) return 'text-amber-600'
      if (state === RECORDER_STATES.STOPPED) return 'text-red-600'
      return 'text-gray-400'
    })

    let errorCopiedTimer = null

    const copyErrorToClipboard = async () => {
      const errors = sourceErrors.value
      if (!errors.length) return
      const msg = errors.map(e => `[${e.label}] ${e.message}`).join('\n\n')
      try {
        // navigator.clipboard requires HTTPS; fall back for plain HTTP
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(msg)
        } else {
          const ta = document.createElement('textarea')
          ta.value = msg
          ta.style.position = 'fixed'
          ta.style.left = '-9999px'
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
        }
        errorCopied.value = true
        if (errorCopiedTimer) clearTimeout(errorCopiedTimer)
        errorCopiedTimer = setTimeout(() => { errorCopied.value = false }, 2000)
      } catch (err) {
        console.warn('Clipboard copy failed:', err)
      }
    }

    // Export state
    const exporting = ref(false)

    // Species list (shared with SpeciesFilterModal)
    const speciesList = ref([])
    const speciesNameMap = ref({})

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
    const birdNameLanguageOptions = [
      { value: 'en', label: 'English (US)' },
      { value: 'en_uk', label: 'English (UK)' },
      { value: 'de', label: 'German' },
      { value: 'fr', label: 'French' },
      { value: 'es', label: 'Spanish' },
      { value: 'it', label: 'Italian' },
      { value: 'nl', label: 'Dutch' },
      { value: 'pt', label: 'Portuguese' },
      { value: 'sv', label: 'Swedish' },
      { value: 'da', label: 'Danish' },
      { value: 'no', label: 'Norwegian' },
      { value: 'fi', label: 'Finnish' },
      { value: 'pl', label: 'Polish' },
      { value: 'cs', label: 'Czech' },
      { value: 'sk', label: 'Slovak' },
      { value: 'sl', label: 'Slovenian' },
      { value: 'hu', label: 'Hungarian' },
      { value: 'ro', label: 'Romanian' },
      { value: 'ru', label: 'Russian' },
      { value: 'uk', label: 'Ukrainian' },
      { value: 'tr', label: 'Turkish' },
      { value: 'af', label: 'Afrikaans' },
      { value: 'ar', label: 'Arabic' },
      { value: 'ja', label: 'Japanese' },
      { value: 'ko', label: 'Korean' },
      { value: 'th', label: 'Thai' },
      { value: 'zh', label: 'Chinese' }
    ]

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

    // Notification modal state
    const showAddNotificationModal = ref(false)
    const editingNotificationIndex = ref(null)
    const editingNotificationUrl = computed(() =>
      editingNotificationIndex.value !== null
        ? settings.value.notifications.apprise_urls?.[editingNotificationIndex.value] ?? null
        : null
    )
    const confirmRemoveIndex = ref(null)

    // Last successfully saved notification settings — used as rollback target on failed autosave
    const confirmedNotifications = ref({ apprise_urls: [] })
    const cloneNotif = () => JSON.parse(JSON.stringify(settings.value.notifications))
    let notifSaveSeq = 0
    let notifAppliedSeq = 0
    let notifSaveInFlight = 0
    const updateChannelSaving = ref(false)
    const metricUnitsSaving = ref(false)

    // Minimal settings skeleton - actual values loaded from API
    const settings = ref({
      location: {},
      detection: {},
      species_filter: { allowed_species: [], blocked_species: [] },
      audio: {},
      spectrogram: {},
      storage: { auto_cleanup_enabled: true, trigger_percent: 85, target_percent: 80 },
      updates: {},
      model: { type: 'birdnet' },
      display: {},
      birdweather: { id: null },
      notifications: { apprise_urls: [] },
      access: { charts_public: false, table_public: false, live_feed_public: false }
    })

    // Unsaved changes tracking
    const originalSettings = ref(null)
    const showUnsavedModal = ref(false)
    const navigationResolver = ref(null)

    // Extract only fields that require manual save (excludes auto-save toggles)
    const getComparableSettings = (s) => ({
      location: { latitude: s.location?.latitude, longitude: s.location?.longitude },
      audio: {
        sources: JSON.parse(JSON.stringify(s.audio?.sources || [])),
        next_source_id: s.audio?.next_source_id || 0,
        recording_length: s.audio?.recording_length,
        overlap: s.audio?.overlap
      },
      detection: { sensitivity: s.detection?.sensitivity, cutoff: s.detection?.cutoff, species_filter_threshold: s.detection?.species_filter_threshold },
      species_filter: {
        allowed_species: s.species_filter?.allowed_species || [],
        blocked_species: s.species_filter?.blocked_species || []
      },
      model: { type: s.model?.type },
      display: { bird_name_language: s.display?.bird_name_language || 'en', station_name: s.display?.station_name || '' },
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
    const isHomeAssistantMode = computed(
      () => systemUpdate?.versionInfo?.value?.runtime_mode === 'ha'
    )
    const repositoryUrl = computed(() => {
      if (isHomeAssistantMode.value) {
        return DEFAULT_REPOSITORY_URL
      }
      return systemUpdate.versionInfo.value?.remote_url || DEFAULT_REPOSITORY_URL
    })
    const versionChangelogUrl = computed(() => {
      const info = systemUpdate.versionInfo.value
      if (!info) return repositoryUrl.value
      if (isHomeAssistantMode.value) {
        return repositoryUrl.value
      }
      const branch = info.current_branch || 'main'
      return `${repositoryUrl.value}/blob/${branch}/CHANGELOG.md`
    })

    // Load storage info
    const loadStorageInfo = async () => {
      try {
        const { data } = await api.get('/system/storage')
        storage.value = data
      } catch (error) {
        console.error('Error loading storage info:', error)
      }
    }

    const loadRecorderStatus = async () => {
      try {
        const { data } = await api.get('/recorder/status')
        if (data && typeof data === 'object' && 'state' in data) {
          recorderStatus.value = data
        }
      } catch (error) {
        console.warn('Recorder status fetch failed:', error)
      }
    }

    // Initialize WebSocket for live recorder status updates.
    // The REST fetch above provides an initial/fallback value if the socket
    // handshake is delayed or unavailable behind a proxy.
    const initSettingsSocket = () => {
      settingsSocket = io()

      settingsSocket.on('connect_error', (error) => {
        console.warn('Recorder status WebSocket connection failed:', error)
        loadRecorderStatus()
      })

      settingsSocket.on('recorder_status', (status) => {
        recorderStatus.value = status
      })
    }

    // Load species list (shared with SpeciesFilterModal)
    const loadSpeciesList = async () => {
      try {
        const { data } = await api.get('/species/available')
        const species = Array.isArray(data?.species) ? data.species : []
        speciesList.value = species
        // Build name map for display
        const map = {}
        for (const speciesItem of species) {
          map[speciesItem.scientific_name] = speciesItem.display_common_name || speciesItem.common_name
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

    // Ensure settings data has all required objects with sensible defaults
    const normalizeSettingsData = (data) => {
      if (!data.updates) data.updates = { channel: 'release' }
      if (!data.display) data.display = { use_metric_units: true, bird_name_language: 'en', station_name: '' }
      if (data.display.use_metric_units === undefined) data.display.use_metric_units = true
      if (!data.display.bird_name_language) data.display.bird_name_language = 'en'
      if (data.display.station_name === undefined) data.display.station_name = ''
      if (!data.model) data.model = { type: 'birdnet' }
      if (!data.notifications) data.notifications = {}
      if (!data.access) data.access = { charts_public: false, table_public: false, live_feed_public: false }
      if (data.updates.channel === 'stable') data.updates.channel = 'release'
      if (!data.audio) data.audio = {}

      // Migrate old audio format to sources array
      if (!Array.isArray(data.audio.sources)) {
        const sources = []
        let nextId = 0
        const mode = data.audio.recording_mode || 'pulseaudio'
        const activeRtsp = data.audio.rtsp_url
        const rtspUrls = data.audio.rtsp_urls || []
        const rtspLabels = data.audio.rtsp_labels || {}

        // Only create a mic source if the user was actually using pulseaudio mode.
        // RTSP users made a deliberate choice — no need to inject an unused mic.
        if (mode === 'pulseaudio') {
          sources.push({
            id: `source_${nextId}`,
            type: 'pulseaudio',
            device: 'default',
            label: 'Local Mic',
            enabled: true
          })
          nextId++
        }

        const validRtspUrls = rtspUrls.filter(u => u)
        const multiRtsp = validRtspUrls.length > 1
        validRtspUrls.forEach((url, i) => {
          const defaultLabel = multiRtsp ? `RTSP Stream ${i + 1}` : 'RTSP Stream'
          sources.push({
            id: `source_${nextId}`,
            type: 'rtsp',
            url,
            label: rtspLabels[url] || defaultLabel,
            enabled: mode === 'rtsp' && url === activeRtsp
          })
          nextId++
        })

        if (mode === 'rtsp' && activeRtsp && !validRtspUrls.includes(activeRtsp)) {
          sources.push({
            id: `source_${nextId}`,
            type: 'rtsp',
            url: activeRtsp,
            label: rtspLabels[activeRtsp] || 'RTSP Stream',
            enabled: true
          })
          nextId++
        }

        data.audio.sources = sources
        data.audio.next_source_id = nextId

        // Clean up old keys
        delete data.audio.recording_mode
        delete data.audio.rtsp_url
        delete data.audio.rtsp_urls
        delete data.audio.rtsp_labels
        delete data.audio.pulseaudio_source
        delete data.audio.stream_url
      }

      // Self-healing: ensure next_source_id exists
      if (data.audio.next_source_id === undefined) {
        const maxSuffix = data.audio.sources.reduce((max, s) => {
          const num = parseInt(s.id?.split('_')[1], 10)
          return isNaN(num) ? max : Math.max(max, num)
        }, -1)
        data.audio.next_source_id = maxSuffix + 1
      }
    }

    // Load settings from API with retry and fallback to defaults
    const loadSettings = async (retryCount = 0) => {
      try {
        loading.value = true
        const { data } = await api.get('/settings')
        normalizeSettingsData(data)
        settings.value = data
        unitSettings.setUseMetricUnits(settings.value.display.use_metric_units ?? true)
        if (saveStatus.value?.type === 'error') {
          saveStatus.value = null
        }
        // Take snapshot for unsaved changes tracking
        takeSnapshot()
        confirmedNotifications.value = cloneNotif()
      } catch (error) {
        console.error('Error loading settings:', error)
        if (retryCount < 2) {
          setTimeout(() => loadSettings(retryCount + 1), 2000)
        } else {
          // Fallback to defaults on failure
          try {
            const { data } = await api.get('/settings/defaults')
            normalizeSettingsData(data)
            settings.value = data
            // Take snapshot for unsaved changes tracking
            takeSnapshot()
            confirmedNotifications.value = JSON.parse(JSON.stringify(data.notifications || {}))
          } catch (defaultsErr) {
            console.error('Failed to load defaults:', defaultsErr)
            showStatus('error', 'Failed to load settings')
          }
        }
      } finally {
        loading.value = false
      }
    }

    // Save settings to API (returns response payload on success, null on failure)
    const saveSettingsOnly = async () => {
      // Validate RTSP sources have valid URLs
      const sources = settings.value.audio.sources || []
      const invalidRtsp = sources.find(s => s.type === 'rtsp' && !s.url?.trim())
      if (invalidRtsp) {
        settingsSaveError.value = `RTSP source "${invalidRtsp.label || invalidRtsp.id}" requires a URL`
        return false
      }

      try {
        loading.value = true
        settingsSaveError.value = ''
        settings.value.location.configured = true
        const { data } = await api.put('/settings', settings.value)
        // Apply server-computed fields (e.g. timezone from coordinates)
        if (data.settings) {
          settings.value = data.settings
        }
        // Update snapshot after successful save
        takeSnapshot()
        confirmedNotifications.value = cloneNotif()
        return data
      } catch (error) {
        console.error('Error saving settings:', error)
        settingsSaveError.value = 'Failed to save settings. Please try again.'
        return null
      } finally {
        loading.value = false
      }
    }

    // Trigger backend restart + wait flow when required by changed settings.
    const triggerRestartIfRequired = async (result, message = 'Applying settings changes') => {
      const needsFullRestart = result?.changes?.full_restart_required === true
      if (!needsFullRestart) {
        return false
      }

      settingsSaveError.value = ''

      try {
        await requestRestart()
        await serviceRestart.waitForRestart({
          autoReload: true,
          message
        })
      } catch (error) {
        console.error('Error triggering restart after settings save:', error)
        settingsSaveError.value = 'Settings saved, but restart did not complete. Please refresh or restart services.'
      }

      return true
    }

    // Persist current settings to backend, handle restart if needed, show status
    const persistAndRestart = async (statusMessage = 'Settings applied.') => {
      const result = await saveSettingsOnly()
      if (result) {
        appStatus.setStationName(settings.value.display?.station_name)
        const restartTriggered = await triggerRestartIfRequired(result, 'Applying settings changes')
        if (!restartTriggered) {
          if (result?.changes?.changed_paths?.includes('display.bird_name_language')) {
            await loadSpeciesList()
          }
          showStatus('success', result?.message || statusMessage)
        }
      }
    }

    // Save settings and wait for restart (used by main Save button)
    const saveSettings = async () => {
      if (!hasUnsavedChanges.value) {
        return // Nothing changed, skip save and restart
      }
      await persistAndRestart()
    }

    // Manual restart triggered from Management section
    const manualRestart = async () => {
      if (serviceRestart.isRestarting.value) return
      try {
        await requestRestart()
        window.scrollTo({ top: 0, behavior: 'smooth' })
        await serviceRestart.waitForRestart({
          autoReload: true,
          message: 'Restarting services'
        })
      } catch (error) {
        console.error('Manual restart failed:', error)
        settingsSaveError.value = 'Restart did not complete. Please refresh or restart services.'
      }
    }

    // Dismiss settings errors (save error or restart error)
    const dismissSettingsError = () => {
      settingsSaveError.value = ''
      serviceRestart.reset()
    }

    // Show status message
    const showStatus = (type, message) => {
      saveStatus.value = { type, message }
      setTimeout(() => { saveStatus.value = null }, 5000)
    }

    // Toggle update channel between release and latest (saves immediately, no restart needed)
    const toggleUpdateChannel = async () => {
      if (updateChannelSaving.value) return
      try {
        updateChannelSaving.value = true
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
      } finally {
        updateChannelSaving.value = false
      }
    }

    // Toggle metric/imperial units (saves immediately, no restart needed)
    const toggleMetricUnits = async () => {
      if (metricUnitsSaving.value) return
      try {
        metricUnitsSaving.value = true
        normalizeSettingsData(settings.value)
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
      } finally {
        metricUnitsSaving.value = false
      }
    }

    // Stream source modal actions
    const openAddSource = () => {
      editingSource.value = null
      showStreamModal.value = true
    }

    const openEditSource = (sourceId) => {
      const sources = settings.value.audio.sources || []
      const source = sources.find(s => s.id === sourceId)
      if (source) {
        editingSource.value = { ...source }
      }
      showStreamModal.value = true
    }

    const handleStreamAdd = async (source) => {
      if (!settings.value.audio.sources) {
        settings.value.audio.sources = []
      }
      const nextId = settings.value.audio.next_source_id || 0
      source.id = `source_${nextId}`
      source.enabled = true
      settings.value.audio.sources.push(source)
      settings.value.audio.next_source_id = nextId + 1
      showStreamModal.value = false
      await persistAndRestart('Source added')
    }

    const handleStreamSave = async ({ id, updates }) => {
      const sources = settings.value.audio.sources || []
      const source = sources.find(s => s.id === id)
      if (source) {
        Object.assign(source, updates)
      }
      showStreamModal.value = false
      await persistAndRestart('Source updated')
    }

    const handleStreamDelete = async (sourceId) => {
      const sources = settings.value.audio.sources || []
      const index = sources.findIndex(s => s.id === sourceId)
      if (index !== -1) {
        sources.splice(index, 1)
      }
      showStreamModal.value = false
      await persistAndRestart('Source removed')
    }

    // Handle BirdWeather ID update
    const updateBirdweatherId = (value) => {
      settings.value.birdweather.id = value || null
    }

    const openEditNotification = (index) => {
      editingNotificationIndex.value = index
      showAddNotificationModal.value = true
    }

    const closeNotificationModal = () => {
      showAddNotificationModal.value = false
      editingNotificationIndex.value = null
    }

    // Handle URL added from the notification modal (test already succeeded)
    const handleAddNotificationUrl = (url) => {
      if (!settings.value.notifications.apprise_urls) {
        settings.value.notifications.apprise_urls = []
      }
      if (!settings.value.notifications.apprise_urls.includes(url)) {
        settings.value.notifications.apprise_urls.push(url)
      }
      closeNotificationModal()
      saveNotificationSettings()
    }

    // Handle URL updated from the edit modal (test already succeeded)
    const handleSaveNotificationUrl = (url) => {
      const index = editingNotificationIndex.value
      const urls = settings.value.notifications.apprise_urls
      if (index !== null && urls) {
        const duplicate = urls.findIndex((u, i) => u === url && i !== index)
        if (duplicate !== -1) {
          // URL already exists at another position — remove that duplicate, keep the edited slot
          urls.splice(duplicate, 1)
        }
        // Update the edited entry (adjust index if the removed duplicate was before it)
        const adjusted = duplicate !== -1 && duplicate < index ? index - 1 : index
        urls[adjusted] = url
      }
      closeNotificationModal()
      saveNotificationSettings()
    }

    // Handle delete triggered from edit modal — delegate to confirm modal
    const handleDeleteNotificationFromModal = () => {
      const index = editingNotificationIndex.value
      closeNotificationModal()
      if (index !== null) {
        confirmRemoveIndex.value = index
      }
    }

    // Notification autosave — persists to dedicated endpoint, no restart needed
    const persistNotificationSettings = async (payload, seq) => {
      notifSaveInFlight += 1
      try {
        await api.put('/settings/notifications', payload)
        if (seq > notifAppliedSeq) {
          notifAppliedSeq = seq
          confirmedNotifications.value = JSON.parse(JSON.stringify(payload))
        }
      } catch {
        if (seq === notifSaveSeq) {
          settings.value.notifications = JSON.parse(JSON.stringify(confirmedNotifications.value))
          showStatus('error', 'Failed to save notification settings')
        }
      } finally {
        notifSaveInFlight -= 1
      }
    }

    const saveNotificationSettings = () => {
      const payload = cloneNotif()
      const seq = ++notifSaveSeq
      return persistNotificationSettings(payload, seq)
    }

    // Toggle a notification boolean and autosave
    const toggleNotificationSetting = (field) => {
      settings.value.notifications[field] = !settings.value.notifications[field]
      saveNotificationSettings()
    }

    // Notification pill setters (save immediately on click)
    const setRateLimit = (value) => {
      settings.value.notifications.rate_limit_seconds = value
      saveNotificationSettings()
    }
    const setRareThreshold = (value) => {
      settings.value.notifications.rare_threshold = value
      saveNotificationSettings()
    }
    const setRareWindow = (value) => {
      settings.value.notifications.rare_window_days = value
      saveNotificationSettings()
    }

    const confirmRemoveAppriseUrl = () => {
      const index = confirmRemoveIndex.value
      confirmRemoveIndex.value = null
      if (index !== null) {
        settings.value.notifications.apprise_urls.splice(index, 1)
        saveNotificationSettings()
      }
    }

    const cancelRemoveAppriseUrl = () => {
      confirmRemoveIndex.value = null
    }

    const appriseServiceName = (url) => {
      const scheme = url.split('://')[0]?.toLowerCase() || ''
      return SCHEME_TO_SERVICE_NAME[scheme] || scheme.toUpperCase()
    }

    // Mask sensitive parts of URL, showing only scheme and last few chars
    const maskAppriseUrl = (url) => {
      const parts = url.split('://')
      if (parts.length < 2 || !parts[1]) return ''
      const rest = parts[1]
      if (rest.length <= 8) return rest
      return rest.slice(0, 4) + '****' + rest.slice(-4)
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

    // Save species filter immediately (and restart if required)
    const saveSpeciesFilter = async (newList) => {
      // Update the settings with the new list
      updateFilterList(newList)

      const result = await saveSettingsOnly()
      if (!result) {
        throw new Error('Failed to save species filter')
      }

      const restartTriggered = await triggerRestartIfRequired(result, 'Applying species filter changes')
      if (!restartTriggered) {
        showStatus('success', result?.message || 'Settings applied.')
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
    const accessFeatures = [
      { key: 'charts_public', label: 'Charts' },
      { key: 'table_public', label: 'Table' },
      { key: 'live_feed_public', label: 'Live Feed' }
    ]

    const toggleFeatureAccess = async (featureKey) => {
      const newValue = !settings.value.access[featureKey]
      settings.value.access[featureKey] = newValue
      const success = await auth.saveAccessSettings({ [featureKey]: newValue })
      if (!success) {
        settings.value.access[featureKey] = !newValue
      }
    }

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
      if (hasUnsavedChanges.value || notifSaveInFlight > 0) {
        e.preventDefault()
        e.returnValue = '' // Required for Chrome
      }
    }

    // Unsaved changes modal handlers
    const handleUnsavedSave = async () => {
      const result = await saveSettingsOnly()
      if (result) {
        const needsFullRestart = result?.changes?.full_restart_required === true

        // Save succeeded; close modal.
        showUnsavedModal.value = false

        if (needsFullRestart) {
          // Keep user on this page so restart progress can be shown (same path as direct Save).
          if (navigationResolver.value) {
            navigationResolver.value(false)
            navigationResolver.value = null
          }
          await triggerRestartIfRequired(result, 'Applying settings changes')
        } else {
          // No restart required: proceed with the original pending navigation.
          if (navigationResolver.value) {
            navigationResolver.value(true)
            navigationResolver.value = null
          }
          showStatus('success', result?.message || 'Settings applied.')
        }
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
    onBeforeRouteLeave(async () => {
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
      loadRecorderStatus()
      loadSpeciesList()
      systemUpdate.loadVersionInfo()
      auth.checkAuthStatus()
      initSettingsSocket()
      window.addEventListener('beforeunload', handleBeforeUnload)
    })

    // Cleanup on unmount
    onUnmounted(() => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      if (errorCopiedTimer) clearTimeout(errorCopiedTimer)
      if (settingsSocket) {
        settingsSocket.disconnect()
        settingsSocket = null
      }
    })

    return {
      settings,
      loading,
      saveStatus,
      showUpdateConfirm,
      showLogsModal,
      manualRestart,
      storage,
      exporting,
      exportCSV,
      saveSettings,
      toggleUpdateChannel,
      isHomeAssistantMode,
      repositoryUrl,
      versionChangelogUrl,
      toggleMetricUnits,
      showRecorderError,
      limitDecimals,
      updateBirdweatherId,
      confirmUpdate,
      systemUpdate,
      serviceRestart,
      settingsSaveError,
      dismissSettingsError,
      updateChannelSaving,
      metricUnitsSaving,
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
      accessFeatures,
      toggleFeatureAccess,
      // Species filter
      showSpeciesFilterModal,
      speciesFilterModalConfig,
      speciesList,
      birdNameLanguageOptions,
      openFilterModal,
      closeFilterModal,
      updateFilterList,
      saveSpeciesFilter,
      getCommonName,
      // Recorder health
      recorderStatus,
      recorderDotClass,
      recorderStateLabel,
      recorderStateLabelClass,
      hasInactiveSource,
      sourceErrors,
      errorCopied,
      copyErrorToClipboard,
      RECORDER_STATES,
      // Audio source management
      hasMicSource,
      showStreamModal,
      editingSource,
      openAddSource,
      openEditSource,
      handleStreamAdd,
      handleStreamSave,
      handleStreamDelete,
      // Dropdown options
      recordingLengthOptions,
      overlapOptions,
      modelTypeOptions,
      onModelTypeChange,
      // Unsaved changes
      hasUnsavedChanges,
      showUnsavedModal,
      handleUnsavedSave,
      handleUnsavedDiscard,
      handleUnsavedCancel,
      // Migration
      showMigrationModal,
      // Notifications
      showAddNotificationModal,
      editingNotificationUrl,
      openEditNotification,
      closeNotificationModal,
      handleAddNotificationUrl,
      handleSaveNotificationUrl,
      handleDeleteNotificationFromModal,
      confirmRemoveIndex,
      confirmRemoveAppriseUrl,
      cancelRemoveAppriseUrl,
      appriseServiceName,
      maskAppriseUrl,
      toggleNotificationSetting,
      rateLimitOptions,
      rareThresholdOptions,
      rareWindowOptions,
      setRateLimit,
      setRareThreshold,
      setRareWindow
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

  /* Toggle show/hide label based on details open state */
  details .hide-label { display: none; }
  details .show-label { display: inline; }
  details[open] .hide-label { display: inline; }
  details[open] .show-label { display: none; }
  </style>
