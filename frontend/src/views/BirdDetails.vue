<template>
  <div
    v-if="birdDetails"
    class="bird-details p-4"
  >
    <h1 class="text-2xl font-semibold mb-4 text-gray-800">
      {{ birdDetails.display_common_name || birdDetails.common_name }}
    </h1>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- Bird Image, Quick Stats, and Attribution -->
      <div class="bg-white rounded-lg shadow overflow-hidden lg:col-span-1">
        <div class="relative overflow-hidden w-full aspect-square max-h-[300px] bg-gray-200">
          <template v-if="hasCustomImage">
            <img
              :src="customImageSrc"
              :alt="birdDetails.display_common_name || birdDetails.common_name"
              class="absolute inset-0 w-full h-full object-cover"
              style="object-position: 50% 50%"
            >
          </template>
          <template v-else>
            <a
              :href="birdImageData.pageUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="block w-full h-full cursor-pointer"
              :title="`View ${birdDetails.display_common_name || birdDetails.common_name} on Wikimedia Commons`"
            >
              <img
                :src="birdImageData.imageUrl"
                :alt="birdDetails.display_common_name || birdDetails.common_name"
                class="absolute inset-0 w-full h-full object-cover transition-[opacity,transform] duration-200 hover:scale-110"
                :class="{ 'opacity-0': !imageReady, 'opacity-100': imageReady }"
                :style="{ objectPosition: imageFocalPoint }"
                @error="onWikimediaImageError"
              >
            </a>
          </template>
          <button
            class="group absolute bottom-2 right-2 bg-black/50 hover:bg-black/70 text-white rounded-full h-9 px-2 flex items-center justify-end overflow-hidden transition-colors"
            title="Customize image"
            @click="openImageModal"
          >
            <span
              class="max-w-0 group-hover:max-w-[12rem] group-hover:mr-2 overflow-hidden whitespace-nowrap text-sm transition-[max-width,margin] duration-300 ease-out"
            >
              Customize image
            </span>
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="w-5 h-5 shrink-0"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fill-rule="evenodd"
                d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 0 1-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 0 1 .947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 0 1 2.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 0 1 2.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 0 1 .947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 0 1-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 0 1-2.287-.947ZM10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
        </div>
        <div class="p-4 bg-gray-100 text-sm text-gray-600">
          <template v-if="hasCustomImage">
            <div class="flex items-center justify-between">
              <p>Custom image</p>
              <button
                class="text-blue-600 underline hover:text-blue-800"
                @click="revertToWikimedia"
              >
                Revert to default
              </button>
            </div>
          </template>
          <template v-else>
            <p>
              Photo by <a
                :href="birdImageData.authorUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="text-blue-600 underline"
              >{{
                birdImageData.authorName }}</a>, licensed under {{ birdImageData.licenseType }}
            </p>
          </template>
        </div>
        <div class="p-6 space-y-2">
          <p><span class="font-semibold text-gray-700">Total Detections:</span> {{ totalVisits }}</p>
          <p><span class="font-semibold text-gray-700">First Detected:</span> {{ formatDate(firstDetected) }}</p>
          <p><span class="font-semibold text-gray-700">Last Detected:</span> {{ formatDate(lastDetected) }}</p>
          <p><span class="font-semibold text-gray-700">Most Activity Time:</span> {{ peakActivityTime }}</p>
          <p v-if="birdDetails.ebird_code">
            <a
              :href="`https://ebird.org/species/${birdDetails.ebird_code}`"
              target="_blank"
              rel="noopener noreferrer"
              class="text-blue-600 hover:text-blue-800 font-semibold inline-flex items-center gap-1"
            >
              eBird
              <svg
                xmlns="http://www.w3.org/2000/svg"
                class="w-3.5 h-3.5"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fill-rule="evenodd"
                  d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.182a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.56l-5.22 5.22a.75.75 0 11-1.06-1.06l5.22-5.22h-2.19a.75.75 0 01-.75-.75z"
                  clip-rule="evenodd"
                />
              </svg>
            </a>
          </p>
        </div>
      </div>


      <!-- Detection Distribution -->
      <div class="bg-white rounded-lg shadow p-6 lg:col-span-2">
        <h2 class="text-lg font-semibold mb-2">
          Distribution
        </h2>
        
        <!-- Tab Navigation -->
        <div class="flex flex-wrap gap-2 mb-4">
          <button
            v-for="view in viewOptions"
            :key="view.value"
            :disabled="isUpdating"
            :class="[
              'h-9 px-4 rounded-md font-medium transition-colors duration-200 inline-flex items-center justify-center',
              view.value === '6month' || view.value === 'year' ? 'hidden sm:block' : '',
              selectedView === view.value 
                ? 'bg-green-600 text-white' 
                : isUpdating
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            ]"
            @click="changeView(view.value)"
          >
            {{ view.label }}
          </button>
        </div>
        
        <!-- Date Navigation -->
        <div class="flex items-center justify-between mb-4">
          <button
            :disabled="isUpdating"
            :class="[
              'h-9 flex items-center px-2 sm:px-3 text-xs sm:text-sm font-medium rounded-md border transition-colors',
              isUpdating
                ? 'text-gray-400 bg-gray-100 border-gray-200 cursor-not-allowed'
                : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            ]"
            @click="navigatePrevious"
          >
            <svg
              class="w-3 h-3 sm:w-4 sm:h-4 mr-1"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 19l-7-7 7-7"
              />
            </svg>
            <span class="hidden sm:inline">Previous</span>
            <span class="sm:hidden">Prev</span>
          </button>
          
          <span class="text-sm sm:text-lg font-medium text-gray-800 text-center px-2">{{ currentDateDisplay }}</span>
          
          <button
            :disabled="isNextDisabled || isUpdating"
            :class="[
              'h-9 flex items-center px-2 sm:px-3 text-xs sm:text-sm font-medium rounded-md border transition-colors',
              (isNextDisabled || isUpdating)
                ? 'text-gray-400 bg-gray-100 border-gray-200 cursor-not-allowed' 
                : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            ]"
            @click="navigateNext"
          >
            <span class="hidden sm:inline">Next</span>
            <span class="sm:hidden">Next</span>
            <svg
              class="w-3 h-3 sm:w-4 sm:h-4 ml-1"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>
        </div>
        
        <!-- Canvas Container with fixed aspect ratio for Safari -->
        <div class="relative w-full h-[300px]">
          <canvas
            ref="detectionChart"
            class="absolute inset-0 w-full h-full"
          />
        </div>
      </div>

      <!-- Recordings Section -->
      <div class="bg-white rounded-lg shadow p-6 lg:col-span-3">
        <!-- Header with Selector -->
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold">
            Recordings
          </h2>
          <div class="flex items-center bg-gray-100 rounded-full p-0.5">
            <button
              v-for="opt in recordingSortOptions"
              :key="opt.value"
              :class="[
                'px-3 py-1 text-xs font-medium rounded-full transition-all duration-200',
                recordingSort === opt.value
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              ]"
              @click="setRecordingSort(opt.value)"
            >
              <span class="sm:hidden">{{ opt.shortLabel }}</span>
              <span class="hidden sm:inline">{{ opt.label }}</span>
            </button>
          </div>
        </div>

        <!-- Recordings Grid (show 4 per page) -->
        <div
          v-if="currentPageRecordings.length > 0"
          class="grid grid-cols-1 md:grid-cols-2 gap-6"
        >
          <div
            v-for="(recording, index) in currentPageRecordings"
            :key="recording.id"
            class="bg-gray-50 p-4 rounded-lg shadow-sm"
          >
            <div class="space-y-2">
              <img
                :src="getSpectrogramUrl(recording.spectrogram_filename)"
                :alt="`Spectrogram ${index + 1}`"
                class="w-full rounded-lg bg-gray-900 cursor-pointer hover:opacity-90 transition-opacity"
                @click="openSpectrogram(recording.spectrogram_filename)"
              >
              <audio
                controls
                class="w-full rounded-lg shadow-sm"
              >
                <source
                  :src="getAudioUrl(recording.audio_filename)"
                  type="audio/mpeg"
                >
                Your browser does not support the audio element.
              </audio>
            </div>
          </div>
        </div>

        <!-- Empty state -->
        <div
          v-else
          class="text-center py-8 text-gray-500"
        >
          No recordings available for this species.
        </div>

        <!-- Pagination: 1 2 3 4 -->
        <div
          v-if="totalPages > 1"
          class="flex justify-center items-center gap-2 mt-6"
        >
          <button
            v-for="page in totalPages"
            :key="page"
            :class="[
              'w-10 py-1 rounded-md font-medium transition-colors text-center',
              page === currentPage
                ? 'bg-green-600 text-white'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            ]"
            @click="currentPage = page"
          >
            {{ page }}
          </button>
        </div>
      </div>
    </div>

    <!-- Spectrogram Modal -->
    <SpectrogramModal
      :is-visible="!!selectedSpectrogramUrl"
      :image-url="selectedSpectrogramUrl || ''"
      alt="Spectrogram"
      @close="closeSpectrogram"
    />

    <!-- Bird Image Customization Modal -->
    <BirdImageModal
      v-if="birdDetails"
      :is-visible="imageModalOpen"
      :species-name="birdDetails.common_name"
      :has-custom-image="hasCustomImage"
      :selected-file-title="selectedFileTitle"
      @close="imageModalOpen = false"
      @applied="onImageApplied"
    />
  </div>
</template>


<script>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import Chart from 'chart.js/auto'
import SpectrogramModal from '@/components/SpectrogramModal.vue'
import BirdImageModal from '@/components/BirdImageModal.vue'
import { useAuth } from '@/composables/useAuth'
import { useDateNavigation } from '@/composables/useDateNavigation'
import { useChartHelpers } from '@/composables/useChartHelpers'
import { useChartColors } from '@/composables/useChartColors'
import { useSmartCrop } from '@/composables/useSmartCrop'
import api from '@/services/api'
import {
  getAudioUrl,
  getBirdImageUrl,
  getDefaultBirdImageUrl,
  getSpectrogramUrl,
  isDefaultBirdImageUrl
} from '@/services/media'

export default {
  name: 'BirdDetails',
  components: {
    SpectrogramModal,
    BirdImageModal
  },
  setup() {
    const route = useRoute()
    const { needsLogin } = useAuth()
    const birdDetails = ref(null)
    const totalVisits = ref(0)
    const firstDetected = ref(null)
    const lastDetected = ref(null)
    const detectionChart = ref(null)
    const detectionChartInstance = ref(null)
    const averageConfidence = ref(0)
    const peakActivityTime = ref('')
    const seasonality = ref('')
    // Recordings state
    const allRecordings = ref([])       // Store all 16 fetched recordings
    const recordingSort = ref('recent') // Default to most recent
    const currentPage = ref(1)
    const recordingsPerPage = 4
    const isLoadingRecordings = ref(false)
    const selectedSpectrogramUrl = ref(null)

    const hasCustomImage = ref(false)
    const customImageSrc = ref(getBirdImageUrl(route.params.name))
    const selectedFileTitle = ref(null)
    const imageModalOpen = ref(false)
    const wikimediaRetried = ref(false)

    const birdImageData = ref({
      imageUrl: getDefaultBirdImageUrl(),
      pageUrl: '',
      authorName: 'N/A',
      authorUrl: '',
      licenseType: 'N/A'
    })

	    const openSpectrogram = (filename) => {
	      selectedSpectrogramUrl.value = getSpectrogramUrl(filename)
	    }

    const closeSpectrogram = () => {
      selectedSpectrogramUrl.value = null
    }

    // Use date navigation composable
    const {
      selectedView,
      anchorDate: currentAnchorDate,
      isUpdating,
      dateDisplay: currentDateDisplay,
      canGoForward,
      navigatePrevious: navPrevious,
      navigateNext: navNext,
      changeView: changeViewBase,
      getLocalDateString
    } = useDateNavigation({ initialView: 'month' })

    const { destroyChart } = useChartHelpers()
    const { colorPalette } = useChartColors()
    const { useFocalPoint } = useSmartCrop()
    const { focalPoint: imageFocalPoint, isReady: imageReady, updateFocalPoint } = useFocalPoint()

    // Detect mobile portrait mode and return appropriate tick limits
    const getMaxTicksLimit = (view) => {
      const isMobilePortrait = window.innerWidth < 640 && window.innerHeight > window.innerWidth

      if (isMobilePortrait) {
        // Reduced tick density for mobile portrait
        switch (view) {
          case 'day': return 8      // Show every 3rd hour
          case 'week': return 7     // Show all days
          case 'month': return 10   // Show ~every 3rd day
          case '6month': return 6   // Show one per month
          case 'year': return 6     // Show every other month
          default: return 10
        }
      }

      // Default tick density for larger screens
      switch (view) {
        case 'day': return 24
        case 'week': return 7
        case 'month': return 31
        case '6month': return 12
        case 'year': return 12
        default: return 12
      }
    }

    // Update queue for chart updates
    const updateQueue = ref([])

    const viewOptions = [
      { value: 'day', label: 'Day' },
      { value: 'week', label: 'Week' },
      { value: 'month', label: 'Month' },
      { value: '6month', label: '6 Month' },
      { value: 'year', label: 'Year' }
    ]

    // Inverted logic for template compatibility
    const isNextDisabled = computed(() => !canGoForward.value)

    // Recordings pagination computed properties
    const totalPages = computed(() => Math.ceil(allRecordings.value.length / recordingsPerPage))

    const currentPageRecordings = computed(() => {
      const start = (currentPage.value - 1) * recordingsPerPage
      const end = start + recordingsPerPage
      return allRecordings.value.slice(start, end)
    })

    const fetchBirdDetails = async () => {
      try {
        const { data } = await api.get(`/bird/${route.params.name}`)
        birdDetails.value = data
        totalVisits.value = data.total_visits
        firstDetected.value = new Date(data.first_detected)
        lastDetected.value = new Date(data.last_detected)
        averageConfidence.value = data.average_confidence
        peakActivityTime.value = data.peak_activity_time
        seasonality.value = data.seasonality

        const { data: imageData } = await api.get('/wikimedia_image', {
          params: { species: birdDetails.value.common_name }
        })

        // Always store wikimedia data for revert fallback
        if (imageData.imageUrl) {
          birdImageData.value = imageData
          wikimediaRetried.value = false
        }
        selectedFileTitle.value = imageData.fileTitle ?? null

        if (imageData.hasCustomImage) {
          hasCustomImage.value = true
        } else {
          // Calculate focal point for smart cropping
          await updateFocalPoint(imageData.imageUrl)
        }

        // Fetch recordings
        await fetchRecordings()

        // Initial chart load
        updateChart()
      } catch (error) {
        console.error('Error fetching bird details:', error)
      }
    }

    // Fetch recordings with current sort option
    const fetchRecordings = async () => {
      isLoadingRecordings.value = true
      try {
        const { data } = await api.get(
          `/bird/${route.params.name}/recordings`,
          { params: { sort: recordingSort.value, limit: 16 } }
        )
        allRecordings.value = data
        currentPage.value = 1  // Reset to page 1
      } catch (error) {
        console.error('Error fetching recordings:', error)
        allRecordings.value = []
      } finally {
        isLoadingRecordings.value = false
      }
    }

    const recordingSortOptions = [
      { label: 'Most Recent', shortLabel: 'Recent', value: 'recent' },
      { label: 'Best Recordings', shortLabel: 'Best', value: 'best' }
    ]

    // Handle sort change - re-fetch with new sort, reset to page 1
    const setRecordingSort = (value) => {
      if (value === recordingSort.value) return
      recordingSort.value = value
      fetchRecordings()
    }

    // Clean chart update function following Chart.js best practices
    const updateChart = async () => {
      // If already updating, queue this update
      if (isUpdating.value) {
        updateQueue.value.push({ view: selectedView.value, date: new Date(currentAnchorDate.value) })
        return
      }

      isUpdating.value = true

      try {
        const localDateString = getLocalDateString(currentAnchorDate.value)

        const { data: chartData } = await api.get(`/bird/${route.params.name}/detection_distribution`, {
          params: {
            view: selectedView.value,
            date: localDateString
          }
        })

        // Wait for Vue to update DOM
        await nextTick()

        // Check if canvas exists
        if (!detectionChart.value) {
          console.error('Chart canvas element not found')
          return
        }

        // Destroy existing chart using composable helper
        destroyChart(detectionChart)

        // Create new chart
        detectionChartInstance.value = new Chart(detectionChart.value, {
          type: 'bar',
          data: {
            labels: chartData.labels,
            datasets: [{
              label: 'Detections',
              data: chartData.data,
              backgroundColor: colorPalette.secondary,
              borderColor: colorPalette.primary,
              borderWidth: 1
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            // Explicitly handle resize for Safari
            onResize: (chart, _size) => {
              // Force redraw on resize
              chart.update('none')
            },
            animation: {
              duration: 300
            },
            interaction: {
              intersect: false
            },
            layout: {
              padding: {
                left: 0,
                right: 0,
                top: 0,
                bottom: 0
              }
            },
            scales: {
              y: {
                beginAtZero: true,
                title: {
                  display: true,
                  text: 'Number of Detections',
                  color: colorPalette.text,
                  padding: 2
                },
                ticks: {
                  color: colorPalette.text,
                  padding: 2,
                  callback: (value) => {
                    const numericValue = Number(value)
                    return Number.isInteger(numericValue) ? numericValue.toString() : ''
                  }
                },
                grid: {
                  color: 'rgba(0, 0, 0, 0.1)',
                  lineWidth: 1
                }
              },
              x: {
                title: {
                  display: true,
                  text: 'Time Period',
                  color: colorPalette.text,
                  padding: 2
                },
                ticks: {
                  color: colorPalette.text,
                  maxRotation: 45,
                  minRotation: 45,
                  autoSkip: true,
                  maxTicksLimit: getMaxTicksLimit(selectedView.value),
                  padding: 2
                },
                grid: {
                  color: 'rgba(0, 0, 0, 0.05)',
                  lineWidth: 1
                }
              }
            },
            plugins: {
              legend: { display: false }
            }
          }
        })

      } catch (error) {
        console.error('Error updating chart:', error)
      } finally {
        isUpdating.value = false
        
        // Process queued updates
        if (updateQueue.value.length > 0) {
          const next = updateQueue.value.shift()
          selectedView.value = next.view
          currentAnchorDate.value = next.date
          // Small delay to prevent rapid updates
          setTimeout(() => updateChart(), 100)
        }
      }
    }
    
    // Wrapped navigation functions that trigger chart updates
    const changeView = (newView) => {
      changeViewBase(newView)
      updateChart()
    }

    const navigatePrevious = () => {
      navPrevious()
      updateChart()
    }

    const navigateNext = () => {
      navNext()
      updateChart()
    }

    const openImageModal = () => {
      if (needsLogin.value) {
        window.dispatchEvent(new CustomEvent('auth:required'))
        return
      }
      imageModalOpen.value = true
    }

    const refreshWikimediaImage = async () => {
      const { data: imageData } = await api.get('/wikimedia_image', {
        params: { species: birdDetails.value.common_name }
      })
      if (imageData.imageUrl) {
        birdImageData.value = imageData
        wikimediaRetried.value = false
      }
      selectedFileTitle.value = imageData.fileTitle ?? null
      if (!isDefaultBirdImageUrl(imageData.imageUrl)) {
        await updateFocalPoint(imageData.imageUrl)
      }
    }

    const onImageApplied = async (payload) => {
      if (payload.kind === 'upload') {
        hasCustomImage.value = true
        customImageSrc.value = `${getBirdImageUrl(route.params.name)}?t=${Date.now()}`
        return
      }
      if (payload.kind === 'wikimedia') {
        hasCustomImage.value = false
        birdImageData.value = {
          imageUrl: payload.candidate.imageUrl,
          pageUrl: payload.candidate.pageUrl,
          authorName: payload.candidate.authorName,
          authorUrl: payload.candidate.authorUrl,
          licenseType: payload.candidate.licenseType
        }
        selectedFileTitle.value = payload.candidate.fileTitle
        wikimediaRetried.value = false
        await updateFocalPoint(payload.candidate.imageUrl)
        return
      }
      if (payload.kind === 'reset') {
        hasCustomImage.value = false
        await refreshWikimediaImage()
      }
    }

    const onWikimediaImageError = async () => {
      // Link rot fallback: if a saved Wikimedia URL goes 404, silently swap to top-of-search.
      // The stale sidecar persists until the user re-opens the modal and picks again.
      if (wikimediaRetried.value || !birdDetails.value) return
      wikimediaRetried.value = true
      try {
        const { data } = await api.get('/wikimedia_image/candidates', {
          params: { species: birdDetails.value.common_name, limit: 1 }
        })
        const top = Array.isArray(data?.candidates) ? data.candidates[0] : null
        if (top && top.imageUrl !== birdImageData.value.imageUrl) {
          birdImageData.value = {
            imageUrl: top.imageUrl,
            pageUrl: top.pageUrl,
            authorName: top.authorName,
            authorUrl: top.authorUrl,
            licenseType: top.licenseType
          }
          await updateFocalPoint(top.imageUrl)
        }
      } catch (err) {
        console.error('Wikimedia fallback failed:', err)
      }
    }

    // Quick "Revert to default" link in the attribution panel — deletes only the
    // custom upload, leaving any saved Wikimedia choice (sidecar) intact. Distinct
    // from the modal's full reset, which deletes both. Per our precedence
    // (custom > sidecar > top-of-search), this surfaces the sidecar if one exists.
    const revertToWikimedia = async () => {
      if (needsLogin.value) {
        window.dispatchEvent(new CustomEvent('auth:required'))
        return
      }
      try {
        await api.delete(`/bird/${route.params.name}/image`)
        hasCustomImage.value = false
        if (birdImageData.value.imageUrl && !isDefaultBirdImageUrl(birdImageData.value.imageUrl)) {
          await updateFocalPoint(birdImageData.value.imageUrl)
        }
      } catch (error) {
        console.error('Error reverting to default image:', error)
      }
    }

    const formatDate = (date) => {
      return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
    }

    // Handle window resize for Safari and orientation changes
    let resizeTimeout
    let lastWidth = typeof window !== 'undefined' ? window.innerWidth : 0
    const handleResize = () => {
      clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(() => {
        const currentWidth = window.innerWidth
        const widthChanged = Math.abs(currentWidth - lastWidth) > 100

        if (detectionChartInstance.value) {
          // If significant width change (orientation change), rebuild chart for new tick density
          if (widthChanged) {
            lastWidth = currentWidth
            updateChart()
          } else {
            detectionChartInstance.value.resize()
          }
        }
      }, 250)
    }

    onMounted(() => {
      fetchBirdDetails()
      window.addEventListener('resize', handleResize)
    })
    
    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)

      // Clean up chart using composable helper
      destroyChart(detectionChart)
    })

    return {
      birdDetails,
      totalVisits,
      firstDetected,
      lastDetected,
      birdImageData,
      imageFocalPoint,
      imageReady,
      hasCustomImage,
      customImageSrc,
      selectedFileTitle,
      imageModalOpen,
      openImageModal,
      onImageApplied,
      onWikimediaImageError,
      revertToWikimedia,
      averageConfidence,
      peakActivityTime,
      seasonality,
      formatDate,
	      detectionChart,
	      getAudioUrl,
	      getSpectrogramUrl,
	      selectedView,
      currentAnchorDate,
      viewOptions,
      currentDateDisplay,
      isNextDisabled,
      isUpdating,
      changeView,
      navigatePrevious,
      navigateNext,
      // Recordings section
      recordingSort,
      recordingSortOptions,
      currentPage,
      totalPages,
      currentPageRecordings,
      setRecordingSort,
      // Spectrogram modal
      selectedSpectrogramUrl,
      openSpectrogram,
      closeSpectrogram,
    }
  }
}
</script>
