<template>
  <div class="p-4">
    <!-- Header -->
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-2xl font-semibold text-gray-800">
        Detections
      </h1>
      <span
        v-if="totalItems > 0"
        class="text-sm text-gray-500"
      >
        {{ totalItems.toLocaleString() }} total
      </span>
    </div>

    <!-- Filters -->
    <div class="bg-white rounded-lg shadow p-4 mb-4">
      <div class="flex flex-col sm:flex-row sm:flex-wrap sm:items-end gap-3">
        <!-- Date Range -->
        <div class="flex gap-3 w-full sm:w-auto">
          <!-- From Date -->
          <div class="flex-1 sm:flex-none">
            <label class="block text-xs font-medium text-gray-600 mb-1">From</label>
            <AppDatePicker
              v-model="localStartDate"
              :max="todayDate"
              size="large"
              fluid
              @change="applyFilters"
            />
          </div>

          <!-- To Date -->
          <div class="flex-1 sm:flex-none">
            <label class="block text-xs font-medium text-gray-600 mb-1">To</label>
            <AppDatePicker
              v-model="localEndDate"
              :min="localStartDate || undefined"
              :max="todayDate"
              size="large"
              fluid
              @change="applyFilters"
            />
          </div>
        </div>

        <!-- Hour Filter (desktop only — the filter row is too tight on mobile) -->
        <div
          ref="hourDropdownRef"
          class="hidden lg:block lg:flex-none lg:w-32 relative"
        >
          <label class="block text-xs font-medium text-gray-600 mb-1">Hour</label>
          <div class="relative">
            <button
              type="button"
              class="flex items-center w-full h-10 pl-3 pr-8 text-sm text-left border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
              @click="showHourDropdown = !showHourDropdown"
            >
              {{ selectedHour === null ? '' : formatHour(selectedHour) }}
            </button>
            <button
              v-if="selectedHour !== null"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              @click.stop="clearHourFilter"
            >
              <CloseIcon class="w-4 h-4" />
            </button>
          </div>
          <!-- Dropdown -->
          <div
            v-show="showHourDropdown"
            class="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg max-h-60 overflow-y-auto"
          >
            <button
              v-for="h in 24"
              :key="h - 1"
              class="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 transition-colors"
              @mousedown.prevent="selectHour(h - 1)"
            >
              {{ formatHour(h - 1) }}
            </button>
          </div>
        </div>

        <!-- Species Filter -->
        <div
          ref="speciesDropdownRef"
          class="w-full sm:flex-1 sm:min-w-[200px] relative"
        >
          <label class="block text-xs font-medium text-gray-600 mb-1">Species</label>
          <div class="relative">
            <input
              v-model="speciesSearchQuery"
              type="text"
              :placeholder="selectedSpeciesLabel || 'All species'"
              class="w-full h-10 px-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent pr-8"
              @focus="showSpeciesDropdown = true"
            >
            <button
              v-if="selectedSpecies"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              @click="clearSpeciesFilter"
            >
              <CloseIcon class="w-4 h-4" />
            </button>
          </div>
          <!-- Dropdown -->
          <div
            v-show="showSpeciesDropdown && filteredSpeciesList.length > 0"
            class="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg max-h-60 overflow-y-auto"
          >
            <button
              v-for="species in filteredSpeciesList"
              :key="species.common_name"
              class="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 transition-colors"
              @mousedown.prevent="selectSpecies(species)"
            >
              <span class="font-medium text-gray-800">{{ getDisplayCommonName(species) }}</span>
              <span class="text-xs text-gray-500 italic ml-2">{{ species.scientific_name }}</span>
            </button>
          </div>
        </div>

        <!-- Clear Filters -->
        <button
          v-if="hasActiveFilters"
          class="w-full sm:w-auto h-10 px-4 text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
          @click="handleClearFilters"
        >
          Clear
        </button>
      </div>
    </div>

    <!-- Content Area -->
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <!-- Loading -->
      <div
        v-if="isLoading"
        class="flex items-center justify-center py-16"
      >
        <Spinner class="h-8 w-8 text-green-600" />
        <span class="ml-3 text-gray-600">Loading...</span>
      </div>

      <!-- Error -->
      <div
        v-else-if="error"
        class="flex flex-col items-center justify-center py-16 px-4"
      >
        <WarningIcon class="w-12 h-12 text-red-400 mb-4" />
        <p class="text-gray-600 mb-4">
          {{ error }}
        </p>
        <button
          class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
          @click="fetchDetections"
        >
          Try Again
        </button>
      </div>

      <!-- Empty State -->
      <div
        v-else-if="detections.length === 0"
        class="flex flex-col items-center justify-center py-16 px-4"
      >
        <svg
          class="w-16 h-16 text-gray-300 mb-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.5"
            d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
          />
        </svg>
        <h3 class="text-lg font-medium text-gray-700 mb-2">
          {{ hasActiveFilters ? 'No matching detections' : 'No detections yet' }}
        </h3>
        <p class="text-gray-500 text-center max-w-md">
          {{ hasActiveFilters
            ? 'Try adjusting your filters.'
            : 'Bird detections will appear here once recording starts.'
          }}
        </p>
      </div>

      <!-- Data -->
      <template v-else>
        <!-- Sort Controls -->
        <div class="flex items-center gap-2 px-4 py-3 bg-gray-50 border-b border-gray-200">
          <button
            v-for="sort in SORT_OPTIONS"
            :key="sort.field"
            class="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 inline-flex items-center gap-1"
            :class="sortField === sort.field
              ? 'bg-green-600 text-white shadow-sm ring-1 ring-green-600'
              : 'bg-white text-gray-600 border border-gray-300 hover:bg-gray-50 hover:border-gray-400'"
            @click="toggleSort(sort.field)"
          >
            <span>{{ sort.label }}</span>
            <span
              v-if="sortField === sort.field"
              class="text-[10px]"
            >
              {{ sortOrder === 'desc' ? '▼' : '▲' }}
            </span>
          </button>
        </div>

        <!-- Batch Action Bar -->
        <div
          v-if="isAuthenticated && selectedCount > 0"
          class="flex items-center justify-between px-4 py-3 bg-blue-50 border-b border-blue-200"
        >
          <span class="text-sm font-medium text-blue-800">
            {{ selectedCount }} item{{ selectedCount === 1 ? '' : 's' }} selected
          </span>
          <div class="flex items-center gap-2">
            <button
              class="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
              @click="clearSelection"
            >
              Clear
            </button>
            <button
              class="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-md hover:bg-red-700 transition-colors"
              @click="confirmBatchDelete"
            >
              Delete Selected
            </button>
          </div>
        </div>
	
        <div
          v-if="actionError"
          class="flex items-start justify-between gap-3 px-4 py-3 bg-red-50 border-b border-red-100"
        >
          <p class="text-sm text-red-700">
            {{ actionError }}
          </p>
          <button
            type="button"
            class="text-red-700 hover:text-red-900 transition-colors"
            title="Dismiss"
            @click="clearActionError"
          >
            <CloseIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- Mobile: Card List -->
        <div class="lg:hidden divide-y divide-gray-100">
          <div
            v-for="detection in detections"
            :key="detection.id"
            class="p-4 hover:bg-gray-50 transition-colors"
            :class="{ 'bg-blue-50': isSelected(detection.id) }"
          >
            <div class="flex items-start gap-3">
              <input
                v-if="isAuthenticated"
                type="checkbox"
                :checked="isSelected(detection.id)"
                class="mt-1 h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
                @change="toggleSelection(detection.id)"
              >
              <div class="flex-1 min-w-0 flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <router-link
                    :to="{ name: 'BirdDetails', params: { name: detection.common_name } }"
                    class="font-medium text-gray-900 hover:text-green-600 transition-colors"
                  >
                    {{ getDisplayCommonName(detection) }}
                  </router-link>
                  <p class="text-xs text-gray-500 italic">
                    {{ detection.scientific_name }}
                  </p>
                  <p class="text-xs text-gray-500 mt-1">
                    {{ formatDateTime(detection.timestamp) }}
                  </p>
                </div>
                <div class="flex flex-col items-end gap-2">
                  <span
                    class="text-sm font-bold"
                    :class="confidenceColorClass(detection.confidence)"
                  >
                    {{ formatConfidence(detection.confidence) }}
                  </span>
                  <DetectionActions
                    :detection="detection"
                    :is-playing="currentPlayingId === detection.id"
                    :hide-delete="!isAuthenticated"
                    @toggle-play="togglePlayAudio"
                    @spectrogram="showSpectrogram"
                    @show-detail="showDetectionDetail"
                    @delete="confirmDelete"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Desktop: Table -->
        <div class="hidden lg:block overflow-x-auto">
          <table class="min-w-full">
            <thead class="bg-gray-50 border-b border-gray-200">
              <tr>
                <th
                  v-if="isAuthenticated"
                  class="w-12 px-4 py-3"
                >
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    class="h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
                    @change="toggleSelectAll"
                  >
                </th>
                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Date & Time
                </th>
                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Species
                </th>
                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Confidence
                </th>
                <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr
                v-for="detection in detections"
                :key="detection.id"
                class="hover:bg-gray-50 transition-colors"
                :class="{ 'bg-blue-50': isSelected(detection.id) }"
              >
                <td
                  v-if="isAuthenticated"
                  class="w-12 px-4 py-4"
                >
                  <input
                    type="checkbox"
                    :checked="isSelected(detection.id)"
                    class="h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
                    @change="toggleSelection(detection.id)"
                  >
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm text-gray-900">
                    {{ formatDate(detection.timestamp) }}
                  </div>
                  <div class="text-xs text-gray-500">
                    {{ formatTime(detection.timestamp) }}
                  </div>
                </td>
                <td class="px-6 py-4">
                  <router-link
                    :to="{ name: 'BirdDetails', params: { name: detection.common_name } }"
                    class="group"
                  >
                    <div class="text-sm font-medium text-gray-900 group-hover:text-green-600 transition-colors">
                      {{ getDisplayCommonName(detection) }}
                    </div>
                    <div class="text-xs text-gray-500 italic">
                      {{ detection.scientific_name }}
                    </div>
                  </router-link>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <span
                    class="text-sm font-bold"
                    :class="confidenceColorClass(detection.confidence)"
                  >
                    {{ formatConfidence(detection.confidence) }}
                  </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-right">
                  <DetectionActions
                    :detection="detection"
                    :is-playing="currentPlayingId === detection.id"
                    :hide-delete="!isAuthenticated"
                    container-class="justify-end w-full"
                    @toggle-play="togglePlayAudio"
                    @spectrogram="showSpectrogram"
                    @show-detail="showDetectionDetail"
                    @delete="confirmDelete"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div class="flex items-center justify-between px-4 py-3 bg-gray-50 border-t border-gray-200">
          <select
            v-model="perPageModel"
            class="h-9 px-2 py-1 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-green-500"
          >
            <option :value="25">
              25
            </option>
            <option :value="50">
              50
            </option>
            <option :value="100">
              100
            </option>
            <option :value="200">
              200
            </option>
          </select>

          <div class="flex items-center gap-1">
            <button
              :disabled="currentPage === 1"
              class="p-2 rounded-md transition-colors"
              :class="currentPage === 1 ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
              @click="goToPage(1)"
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
                  d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
                />
              </svg>
            </button>
            <button
              :disabled="!hasPrevPage"
              class="p-2 rounded-md transition-colors"
              :class="!hasPrevPage ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
              @click="prevPage"
            >
              <ChevronIcon
                direction="left"
                class="w-4 h-4"
              />
            </button>

            <span class="px-3 py-1 text-sm text-gray-700">
              {{ currentPage }} / {{ totalPages }}
            </span>

            <button
              :disabled="!hasNextPage"
              class="p-2 rounded-md transition-colors"
              :class="!hasNextPage ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
              @click="nextPage"
            >
              <ChevronIcon
                direction="right"
                class="w-4 h-4"
              />
            </button>
            <button
              :disabled="currentPage === totalPages"
              class="p-2 rounded-md transition-colors"
              :class="currentPage === totalPages ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
              @click="goToPage(totalPages)"
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
                  d="M13 5l7 7-7 7M5 5l7 7-7 7"
                />
              </svg>
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- Scroll to Top FAB -->
    <ScrollToTopButton />

    <!-- Spectrogram Modal -->
    <SpectrogramModal
      :is-visible="isSpectrogramModalVisible"
      :image-url="currentSpectrogramUrl"
      alt="Spectrogram"
      @close="isSpectrogramModalVisible = false"
    />

    <!-- Detection Detail Modal — the per-row info action opens the full player
         here instead of navigating, so the table keeps its place. -->
    <DetectionModal
      :id="detailDetection?.id"
      :is-visible="isDetailModalVisible"
      :name="detailDetection?.common_name"
      @close="isDetailModalVisible = false"
    />

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div
        v-if="showDeleteModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        <div
          class="fixed inset-0 bg-black/50"
          @click="requestDeleteDismiss"
        />
        <div class="relative bg-white rounded-lg shadow-xl max-w-sm w-full p-6">
          <button
            v-if="!isDeleting"
            class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
            title="Close"
            @click="requestDeleteDismiss"
          >
            <CloseIcon class="w-5 h-5" />
          </button>
          <h3 class="text-lg font-semibold text-gray-900 mb-2">
            {{ isBatchDelete ? 'Delete Detections' : 'Delete Detection' }}
          </h3>
          <p class="text-gray-600 mb-6">
            <template v-if="isBatchDelete">
              Delete <strong>{{ selectedCount }}</strong> selected detection{{ selectedCount === 1 ? '' : 's' }}? This cannot be undone.
            </template>
            <template v-else>
              Delete this <strong>{{ getDisplayCommonName(detectionToDelete) }}</strong> detection from {{ formatDate(detectionToDelete?.timestamp) }}?
            </template>
          </p>
          <div class="flex justify-end gap-3">
            <button
              :disabled="isDeleting"
              class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
              :class="isDeleting ? 'opacity-50 cursor-not-allowed hover:bg-gray-100' : ''"
              @click="cancelDelete"
            >
              Cancel
            </button>
            <button
              :disabled="isDeleting"
              class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors disabled:opacity-50"
              @click="executeDelete"
            >
              {{ isDeleting ? 'Deleting...' : 'Delete' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

	<script setup>
	import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import { library } from '@fortawesome/fontawesome-svg-core'
	import { faPlay, faPause, faCircleInfo, faTrashAlt } from '@fortawesome/free-solid-svg-icons'
	
	import api from '@/services/api'
	import { getAudioUrl, getSpectrogramUrl } from '@/services/media'
	import { useTableData } from '@/composables/useTableData'
	import { useAudioPlayer } from '@/composables/useAudioPlayer'
	import { useAuth } from '@/composables/useAuth'
	import { useTimeFormat } from '@/composables/useTimeFormat'
	import { useModalDismiss } from '@/composables/useModalDismiss'
	import { getDisplayCommonName, matchesBirdQuery } from '@/utils/birdNames'
	import { normalizeHour } from '@/utils/inputHelpers'
	import { formatConfidence, confidenceColorClass } from '@/utils/format'
	import DetectionActions from '@/components/DetectionActions.vue'
	import SpectrogramModal from '@/components/SpectrogramModal.vue'
import DetectionModal from '@/components/DetectionModal.vue'
import CloseIcon from '@/components/icons/CloseIcon.vue'
import WarningIcon from '@/components/icons/WarningIcon.vue'
import ChevronIcon from '@/components/icons/ChevronIcon.vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import Spinner from '@/components/Spinner.vue'
import ScrollToTopButton from '@/components/ScrollToTopButton.vue'

// --- Icons Setup ---
library.add(faPlay, faPause, faCircleInfo, faTrashAlt)

	// --- Constants ---
	const SORT_OPTIONS = [
	  { field: 'timestamp', label: 'Date' },
	  { field: 'common_name', label: 'Species' },
	  { field: 'confidence', label: 'Confidence' }
	]

// --- Composables ---
const {
  detections,
  currentPage,
  perPage,
  totalItems,
  totalPages,
  isLoading,
  error,
  actionError,
  startDate,
  endDate,
  selectedSpecies,
  selectedHour,
  hasActiveFilters,
  sortField,
  sortOrder,
  selectedCount,
  allSelected,
  hasNextPage,
  hasPrevPage,
  fetchDetections,
  deleteDetection,
  deleteSelected,
  toggleSelection,
  isSelected,
  toggleSelectAll,
  clearSelection,
  clearActionError,
  goToPage,
  nextPage,
  prevPage,
  setFilters,
  clearFilters,
  toggleSort,
  setPerPage
} = useTableData()

// Audio playback composable
const {
  currentPlayingId,
  togglePlay
} = useAudioPlayer()

const { isAuthenticated } = useAuth()

const route = useRoute()
const router = useRouter()

// --- State ---

// Filters
	const localStartDate = ref('')
	const localEndDate = ref('')
	const todayDate = computed(() => {
	  const today = new Date()
	  const year = today.getFullYear()
	  const month = String(today.getMonth() + 1).padStart(2, '0')
	  const day = String(today.getDate()).padStart(2, '0')
	  return `${year}-${month}-${day}`
	})
	const perPageModel = computed({
	  get: () => perPage.value,
	  set: (value) => setPerPage(value)
	})

	// Species Filter
	const speciesSearchQuery = ref('')
	const showSpeciesDropdown = ref(false)
	const speciesList = ref([])
	const speciesDropdownRef = ref(null)
	const showHourDropdown = ref(false)
	const hourDropdownRef = ref(null)
	const filteredSpeciesList = computed(() => {
	  const query = speciesSearchQuery.value.trim().toLowerCase()
	  if (!query) return speciesList.value

	  return speciesList.value.filter(species => matchesBirdQuery(species, query))
	})
	const selectedSpeciesLabel = computed(() => {
	  if (!selectedSpecies.value) return ''
	  const species = speciesList.value.find(item => item.common_name === selectedSpecies.value)
	  return getDisplayCommonName(species) || selectedSpecies.value
	})

// Modals
const isSpectrogramModalVisible = ref(false)
const currentSpectrogramUrl = ref('')
// Detection detail modal. detailDetection is kept (not nulled) on close so the
// player props stay stable through the leave transition; only the visibility
// flag toggles.
const isDetailModalVisible = ref(false)
const detailDetection = ref(null)
const showDeleteModal = ref(false)
const detectionToDelete = ref(null)
const isDeleting = ref(false)
const isBatchDelete = ref(false)

// --- Helper Functions: Formatting ---

const formatDate = (timestamp) => {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const { formatTime: formatTimeOfDay, formatHour } = useTimeFormat()

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  return formatTimeOfDay(timestamp)
}

const formatDateTime = (timestamp) => {
  if (!timestamp) return ''
  return `${formatDate(timestamp)} at ${formatTime(timestamp)}`
}

// --- Helper Functions: Species Filter ---

	const fetchSpeciesList = async () => {
	  try {
	    const response = await api.get('/species/all')
	    const list = Array.isArray(response.data) ? response.data : []
	    list.sort((a, b) => getDisplayCommonName(a).localeCompare(getDisplayCommonName(b)))
	    speciesList.value = list
	  } catch (err) {
	    console.error('Failed to fetch species list:', err)
	    speciesList.value = []
	  }
	}

const selectSpecies = (species) => {
  selectedSpecies.value = species.common_name
  speciesSearchQuery.value = ''
  showSpeciesDropdown.value = false
  applyFilters()
}

	const clearSpeciesFilter = () => {
	  selectedSpecies.value = null
	  speciesSearchQuery.value = ''
	  showSpeciesDropdown.value = false
	  applyFilters()
	}

const selectHour = (h) => {
  selectedHour.value = h
  showHourDropdown.value = false
  applyFilters()
}

const clearHourFilter = () => {
  selectedHour.value = null
  showHourDropdown.value = false
  applyFilters()
}

const handleClickOutside = (event) => {
  if (speciesDropdownRef.value && !speciesDropdownRef.value.contains(event.target)) {
    showSpeciesDropdown.value = false
  }
  if (hourDropdownRef.value && !hourDropdownRef.value.contains(event.target)) {
    showHourDropdown.value = false
  }
}

// --- Event Handlers ---

const applyFilters = () => {
  setFilters({
    startDate: localStartDate.value || null,
    endDate: localEndDate.value || null,
    species: selectedSpecies.value,
    hour: selectedHour.value
  })
}

const handleClearFilters = () => {
  localStartDate.value = ''
  localEndDate.value = ''
  speciesSearchQuery.value = ''
  // Resets the composable filters + page; the query-sync watcher then strips the
  // matching keys from the URL so a later refresh / back-forward doesn't
  // resurrect the just-cleared filters.
  clearFilters()
}

const togglePlayAudio = (detection) => {
  if (!detection?.id) return
  const audioUrl = getAudioUrl(detection.audio_filename)
  if (!audioUrl) return
  togglePlay(detection.id, audioUrl)
}

const showSpectrogram = (detection) => {
	  currentSpectrogramUrl.value = getSpectrogramUrl(detection.spectrogram_filename)
	  isSpectrogramModalVisible.value = true
	}

const showDetectionDetail = (detection) => {
  detailDetection.value = detection
  isDetailModalVisible.value = true
}

// --- Delete Logic ---

const confirmDelete = (detection) => {
  isBatchDelete.value = false
  detectionToDelete.value = detection
  showDeleteModal.value = true
}

const confirmBatchDelete = () => {
  if (selectedCount.value === 0) return
  isBatchDelete.value = true
  detectionToDelete.value = null
  showDeleteModal.value = true
}

const cancelDelete = () => {
  if (isDeleting.value) return
  showDeleteModal.value = false
  detectionToDelete.value = null
  isBatchDelete.value = false
}

const { requestDismiss: requestDeleteDismiss } = useModalDismiss(
  showDeleteModal,
  cancelDelete,
  { canDismiss: () => !isDeleting.value }
)

const executeDelete = async () => {
  isDeleting.value = true

  if (isBatchDelete.value) {
    const result = await deleteSelected()
    isDeleting.value = false
    if (result.success) {
      showDeleteModal.value = false
      isBatchDelete.value = false
    }
  } else {
    if (!detectionToDelete.value) {
      isDeleting.value = false
      return
    }
    const success = await deleteDetection(detectionToDelete.value.id)
    isDeleting.value = false
    if (success) {
      showDeleteModal.value = false
      detectionToDelete.value = null
    }
  }
}

// --- Lifecycle & Watchers ---

// Seed the full table view (filters + pagination + sort) from the route query so
// a shared/bookmarked URL, a chart deep-link, or a back-navigation restores the
// exact view. Chart deep-links send { date, hour, species }; this also reads the
// page/sort/per_page that syncQueryToRoute writes back. Sets the composable state
// directly rather than via setFilters() — which would reset the page to 1 — and
// the caller fetches once afterwards.
const isDateStr = (value) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)

const seedStateFromQuery = () => {
  const { date, start, end, hour, species, page, sort, order, per_page: perPageParam } = route.query

  // `date` is the single-day form (chart deep-links, and how a single-day filter
  // is written below); `start`/`end` carry an open-ended or multi-day range.
  const startStr = isDateStr(start) ? start : (isDateStr(date) ? date : null)
  const endStr = isDateStr(end) ? end : (isDateStr(date) ? date : null)
  if (startStr) {
    localStartDate.value = startStr
    startDate.value = startStr
  }
  if (endStr) {
    localEndDate.value = endStr
    endDate.value = endStr
  }

  const h = normalizeHour(hour)
  if (h !== null) selectedHour.value = h

  const trimmedSpecies = typeof species === 'string' ? species.trim() : ''
  if (trimmedSpecies) selectedSpecies.value = trimmedSpecies

  const p = Number.parseInt(page, 10)
  if (Number.isInteger(p) && p > 1) currentPage.value = p

  if (typeof sort === 'string' && SORT_OPTIONS.some(o => o.field === sort)) {
    sortField.value = sort
    sortOrder.value = order === 'asc' ? 'asc' : 'desc'
  }

  const pp = Number.parseInt(perPageParam, 10)
  if ([25, 50, 100, 200].includes(pp)) perPage.value = pp
}

// Build the URL query from the current table state. Defaults (page 1, newest-first
// sort, 25/page, empty filters) are omitted to keep the URL clean. A single day
// (start === end) uses the compact `date` key — matching chart deep-links so they
// aren't rewritten; any other range uses independent `start`/`end` keys so an
// open-ended "from X onwards" filter round-trips without being narrowed.
const buildTableQuery = () => {
  const query = {}
  if (startDate.value && startDate.value === endDate.value) {
    query.date = startDate.value
  } else {
    if (startDate.value) query.start = startDate.value
    if (endDate.value) query.end = endDate.value
  }
  if (selectedHour.value !== null) query.hour = selectedHour.value
  if (selectedSpecies.value) query.species = selectedSpecies.value
  if (currentPage.value > 1) query.page = currentPage.value
  if (sortField.value !== 'timestamp' || sortOrder.value !== 'desc') {
    query.sort = sortField.value
    query.order = sortOrder.value
  }
  if (perPage.value !== 25) query.per_page = perPage.value
  return query
}

// Compare two query objects by their stringified values (route.query values are
// always strings; ours may be numbers), so we skip redundant navigations.
const sameQuery = (a, b) => {
  const ak = Object.keys(a)
  const bk = Object.keys(b)
  if (ak.length !== bk.length) return false
  return ak.every(k => String(a[k]) === String(b[k]))
}

// Reflect table state into the URL (replace, not push, so paging/filtering does
// not pollute the back stack). Wrapped in Promise.resolve so a redundant-navigation
// rejection is swallowed and a non-promise (test mock) is tolerated.
const syncQueryToRoute = () => {
  const query = buildTableQuery()
  if (sameQuery(query, route.query)) return
  Promise.resolve(router.replace({ query })).catch(() => {})
}

watch(
  [startDate, endDate, selectedHour, selectedSpecies, currentPage, sortField, sortOrder, perPage],
  syncQueryToRoute
)

	onMounted(() => {
	  seedStateFromQuery()
	  fetchDetections()
	  fetchSpeciesList()
	  document.addEventListener('click', handleClickOutside)
	})

	onUnmounted(() => {
	  document.removeEventListener('click', handleClickOutside)
	  // Audio cleanup is handled automatically by useAudioPlayer composable
	})
	</script>
