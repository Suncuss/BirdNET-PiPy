<template>
  <div class="p-4">
    <!-- Header -->
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-2xl font-semibold text-gray-800">Detections</h1>
      <span v-if="totalItems > 0" class="text-sm text-gray-500">
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
              @change="applyFilters"
              size="large"
            />
          </div>

          <!-- To Date -->
          <div class="flex-1 sm:flex-none">
            <label class="block text-xs font-medium text-gray-600 mb-1">To</label>
            <AppDatePicker
              v-model="localEndDate"
              @change="applyFilters"
              size="large"
            />
          </div>
        </div>

        <!-- Species Filter -->
        <div class="w-full sm:flex-1 sm:min-w-[200px] relative" ref="speciesDropdownRef">
          <label class="block text-xs font-medium text-gray-600 mb-1">Species</label>
          <div class="relative">
	            <input
	              type="text"
	              v-model="speciesSearchQuery"
	              @focus="showSpeciesDropdown = true"
	              :placeholder="selectedSpecies || 'All species'"
	              class="w-full h-10 px-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent pr-8"
	            />
            <button
              v-if="selectedSpecies"
              @click="clearSpeciesFilter"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
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
              @mousedown.prevent="selectSpecies(species)"
              class="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 transition-colors"
            >
              <span class="font-medium text-gray-800">{{ species.common_name }}</span>
              <span class="text-xs text-gray-500 italic ml-2">{{ species.scientific_name }}</span>
            </button>
          </div>
        </div>

        <!-- Clear Filters -->
        <button
          v-if="hasActiveFilters"
          @click="handleClearFilters"
          class="w-full sm:w-auto h-10 px-4 text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
        >
          Clear
        </button>
      </div>
    </div>

    <!-- Content Area -->
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <!-- Loading -->
      <div v-if="isLoading" class="flex items-center justify-center py-16">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600"></div>
        <span class="ml-3 text-gray-600">Loading...</span>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="flex flex-col items-center justify-center py-16 px-4">
        <svg class="w-12 h-12 text-red-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p class="text-gray-600 mb-4">{{ error }}</p>
        <button
          @click="fetchDetections"
          class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
        >
          Try Again
        </button>
      </div>

      <!-- Empty State -->
      <div v-else-if="detections.length === 0" class="flex flex-col items-center justify-center py-16 px-4">
        <svg class="w-16 h-16 text-gray-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
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
            @click="toggleSort(sort.field)"
            class="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 inline-flex items-center gap-1"
            :class="sortField === sort.field
              ? 'bg-green-600 text-white shadow-sm ring-1 ring-green-600'
              : 'bg-white text-gray-600 border border-gray-300 hover:bg-gray-50 hover:border-gray-400'"
          >
            <span>{{ sort.label }}</span>
            <span v-if="sortField === sort.field" class="text-[10px]">
              {{ sortOrder === 'desc' ? '▼' : '▲' }}
            </span>
          </button>
        </div>

        <!-- Batch Action Bar -->
        <div
          v-if="selectedCount > 0"
          class="flex items-center justify-between px-4 py-3 bg-blue-50 border-b border-blue-200"
        >
          <span class="text-sm font-medium text-blue-800">
            {{ selectedCount }} item{{ selectedCount === 1 ? '' : 's' }} selected
          </span>
          <div class="flex items-center gap-2">
            <button
              @click="clearSelection"
              class="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
            >
              Clear
            </button>
            <button
              @click="confirmBatchDelete"
              class="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-md hover:bg-red-700 transition-colors"
            >
              Delete Selected
            </button>
          </div>
        </div>
	
	        <div
	          v-if="actionError"
	          class="flex items-start justify-between gap-3 px-4 py-3 bg-red-50 border-b border-red-100"
	        >
	          <p class="text-sm text-red-700">{{ actionError }}</p>
	          <button
	            type="button"
	            class="text-red-700 hover:text-red-900 transition-colors"
	            title="Dismiss"
	            @click="clearActionError"
	          >
	            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
	              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
	            </svg>
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
                type="checkbox"
                :checked="isSelected(detection.id)"
                @change="toggleSelection(detection.id)"
                class="mt-1 h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
              />
              <div class="flex-1 min-w-0 flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <router-link
                    :to="{ name: 'BirdDetails', params: { name: detection.common_name } }"
                    class="font-medium text-gray-900 hover:text-green-600 transition-colors"
                  >
                    {{ detection.common_name }}
                  </router-link>
                  <p class="text-xs text-gray-500 italic">{{ detection.scientific_name }}</p>
                  <p class="text-xs text-gray-500 mt-1">
                    {{ formatDateTime(detection.timestamp) }}
                  </p>
                </div>
              <div class="flex flex-col items-end gap-2">
                <span
                  class="text-sm font-bold"
                  :class="getConfidenceColor(detection.confidence)"
                >
                  {{ formatConfidence(detection.confidence) }}
                </span>
                <DetectionActions
                  :detection="detection"
                  :is-playing="currentPlayingId === detection.id"
                  @toggle-play="togglePlayAudio"
                  @spectrogram="showSpectrogram"
                  @show-info="showDetectionInfo"
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
                <th class="w-12 px-4 py-3">
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    @change="toggleSelectAll"
                    class="h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
                  />
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
                <td class="w-12 px-4 py-4">
                  <input
                    type="checkbox"
                    :checked="isSelected(detection.id)"
                    @change="toggleSelection(detection.id)"
                    class="h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500"
                  />
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm text-gray-900">{{ formatDate(detection.timestamp) }}</div>
                  <div class="text-xs text-gray-500">{{ formatTime(detection.timestamp) }}</div>
                </td>
                <td class="px-6 py-4">
                  <router-link
                    :to="{ name: 'BirdDetails', params: { name: detection.common_name } }"
                    class="group"
                  >
                    <div class="text-sm font-medium text-gray-900 group-hover:text-green-600 transition-colors">
                      {{ detection.common_name }}
                    </div>
                    <div class="text-xs text-gray-500 italic">{{ detection.scientific_name }}</div>
                  </router-link>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <span
                    class="text-sm font-bold"
                    :class="getConfidenceColor(detection.confidence)"
                  >
                    {{ formatConfidence(detection.confidence) }}
                  </span>
                </td>
	                <td class="px-6 py-4 whitespace-nowrap text-right">
	                  <DetectionActions
	                    :detection="detection"
	                    :is-playing="currentPlayingId === detection.id"
	                    container-class="justify-end w-full"
	                    @toggle-play="togglePlayAudio"
	                    @spectrogram="showSpectrogram"
	                    @show-info="showDetectionInfo"
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
	            class="px-2 py-1 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-green-500"
	          >
	            <option :value="25">25</option>
	            <option :value="50">50</option>
	            <option :value="100">100</option>
          </select>

          <div class="flex items-center gap-1">
            <button
              @click="goToPage(1)"
              :disabled="currentPage === 1"
              class="p-2 rounded-md transition-colors"
              :class="currentPage === 1 ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>
            <button
              @click="prevPage"
              :disabled="!hasPrevPage"
              class="p-2 rounded-md transition-colors"
              :class="!hasPrevPage ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
              </svg>
            </button>

            <span class="px-3 py-1 text-sm text-gray-700">
              {{ currentPage }} / {{ totalPages }}
            </span>

            <button
              @click="nextPage"
              :disabled="!hasNextPage"
              class="p-2 rounded-md transition-colors"
              :class="!hasNextPage ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
            </button>
            <button
              @click="goToPage(totalPages)"
              :disabled="currentPage === totalPages"
              class="p-2 rounded-md transition-colors"
              :class="currentPage === totalPages ? 'text-gray-300' : 'text-gray-600 hover:bg-gray-200'"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- Spectrogram Modal -->
    <SpectrogramModal
      :is-visible="isSpectrogramModalVisible"
      :image-url="currentSpectrogramUrl"
      alt="Spectrogram"
      @close="isSpectrogramModalVisible = false"
    />

    <!-- Detection Info Modal -->
    <DetectionInfoModal
      :is-visible="isInfoModalVisible"
      :detection="detectionForInfo"
      @close="isInfoModalVisible = false"
    />

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div
        v-if="showDeleteModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        <div class="fixed inset-0 bg-black/50" @click="handleDeleteBackdropClick"></div>
        <div class="relative bg-white rounded-lg shadow-xl max-w-sm w-full p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-2">
            {{ isBatchDelete ? 'Delete Detections' : 'Delete Detection' }}
          </h3>
          <p class="text-gray-600 mb-6">
            <template v-if="isBatchDelete">
              Delete <strong>{{ selectedCount }}</strong> selected detection{{ selectedCount === 1 ? '' : 's' }}? This cannot be undone.
            </template>
            <template v-else>
              Delete this <strong>{{ detectionToDelete?.common_name }}</strong> detection from {{ formatDate(detectionToDelete?.timestamp) }}?
            </template>
          </p>
	          <div class="flex justify-end gap-3">
	            <button
	              @click="cancelDelete"
	              :disabled="isDeleting"
	              class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
	              :class="isDeleting ? 'opacity-50 cursor-not-allowed hover:bg-gray-100' : ''"
	            >
	              Cancel
	            </button>
	            <button
	              @click="executeDelete"
	              :disabled="isDeleting"
              class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors disabled:opacity-50"
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
	import { ref, onMounted, onUnmounted, computed } from 'vue'
	import { library } from '@fortawesome/fontawesome-svg-core'
	import { faPlay, faPause, faCircleInfo, faTrashAlt, faDatabase } from '@fortawesome/free-solid-svg-icons'
	
	import api from '@/services/api'
	import { getAudioUrl, getSpectrogramUrl } from '@/services/media'
	import { useTableData } from '@/composables/useTableData'
	import { useAudioPlayer } from '@/composables/useAudioPlayer'
	import DetectionActions from '@/components/DetectionActions.vue'
	import SpectrogramModal from '@/components/SpectrogramModal.vue'
import DetectionInfoModal from '@/components/DetectionInfoModal.vue'
import AppDatePicker from '@/components/AppDatePicker.vue'

// --- Icons Setup ---
library.add(faPlay, faPause, faCircleInfo, faTrashAlt, faDatabase)

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
  selectedSpecies,
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

// --- State ---

// Filters
	const localStartDate = ref('')
	const localEndDate = ref('')
	const perPageModel = computed({
	  get: () => perPage.value,
	  set: (value) => setPerPage(value)
	})

	// Species Filter
	const speciesSearchQuery = ref('')
	const showSpeciesDropdown = ref(false)
	const speciesList = ref([])
	const speciesDropdownRef = ref(null)
	const filteredSpeciesList = computed(() => {
	  const query = speciesSearchQuery.value.trim().toLowerCase()
	  if (!query) return speciesList.value

	  return speciesList.value.filter((species) => {
	    const commonName = (species?.common_name || '').toLowerCase()
	    const scientificName = (species?.scientific_name || '').toLowerCase()
	    return commonName.includes(query) || scientificName.includes(query)
	  })
	})

// Modals
const isSpectrogramModalVisible = ref(false)
const currentSpectrogramUrl = ref('')
const isInfoModalVisible = ref(false)
const detectionForInfo = ref(null)
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

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatDateTime = (timestamp) => {
  if (!timestamp) return ''
  return `${formatDate(timestamp)} at ${formatTime(timestamp)}`
}

const formatConfidence = (confidence) => {
  return `${Math.round(confidence * 100)}%`
}

const getConfidenceColor = (confidence) => {
  if (confidence >= 0.9) return 'text-green-600'
  if (confidence >= 0.7) return 'text-green-500'
  if (confidence >= 0.5) return 'text-yellow-600'
  return 'text-orange-500'
}

// --- Helper Functions: Species Filter ---

	const fetchSpeciesList = async () => {
	  try {
	    const response = await api.get('/species/all')
	    const list = Array.isArray(response.data) ? response.data : []
	    list.sort((a, b) => (a?.common_name || '').localeCompare(b?.common_name || ''))
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

const handleClickOutside = (event) => {
  if (speciesDropdownRef.value && !speciesDropdownRef.value.contains(event.target)) {
    showSpeciesDropdown.value = false
  }
}

// --- Event Handlers ---

const applyFilters = () => {
  setFilters({
    startDate: localStartDate.value || null,
    endDate: localEndDate.value || null,
    species: selectedSpecies.value
  })
}

const handleClearFilters = () => {
  localStartDate.value = ''
  localEndDate.value = ''
  selectedSpecies.value = null
  speciesSearchQuery.value = ''
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

const showDetectionInfo = (detection) => {
  detectionForInfo.value = detection
  isInfoModalVisible.value = true
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

const handleDeleteBackdropClick = () => {
  if (isDeleting.value) return
  cancelDelete()
}

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

	onMounted(() => {
	  fetchDetections()
	  fetchSpeciesList()
	  document.addEventListener('click', handleClickOutside)
	})

	onUnmounted(() => {
	  document.removeEventListener('click', handleClickOutside)
	  // Audio cleanup is handled automatically by useAudioPlayer composable
	})
	</script>
