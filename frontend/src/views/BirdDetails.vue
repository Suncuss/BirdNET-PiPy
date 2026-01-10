<template>
  <div v-if="birdDetails" class="bird-details p-4">

    <h1 class="text-2xl font-semibold mb-4 text-gray-800">{{ birdDetails.common_name }}</h1>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

      <!-- Bird Image, Quick Stats, and Attribution -->
      <div class="bg-white rounded-lg shadow overflow-hidden lg:col-span-1">
        <div class="relative overflow-hidden w-full aspect-square max-h-[300px] bg-gray-200">
          <a :href="birdImageData.pageUrl" target="_blank" rel="noopener noreferrer"
            class="block w-full h-full cursor-pointer"
            :title="`View ${birdDetails.common_name} on Wikimedia Commons`">
            <img :src="birdImageData.imageUrl" :alt="birdDetails.common_name"
              class="absolute inset-0 w-full h-full object-cover transition-[opacity,transform] duration-200 hover:scale-110"
              :class="{ 'opacity-0': !imageReady, 'opacity-100': imageReady }"
              :style="{ objectPosition: imageFocalPoint }">
          </a>
        </div>
        <div class="p-4 bg-gray-100 text-sm text-gray-600">
          <p>
            Photo by <a :href="birdImageData.authorUrl" target="_blank" rel="noopener noreferrer" class="text-blue-600 underline">{{
              birdImageData.authorName }}</a>, licensed under {{ birdImageData.licenseType }}
          </p>
        </div>
        <div class="p-6 space-y-2">
          <p><span class="font-semibold text-gray-700">Total Detections:</span> {{ totalVisits }}</p>
          <p><span class="font-semibold text-gray-700">First Detected:</span> {{ formatDate(firstDetected) }}</p>
          <p><span class="font-semibold text-gray-700">Last Detected:</span> {{ formatDate(lastDetected) }}</p>
          <p><span class="font-semibold text-gray-700">Most Activity Time:</span> {{ peakActivityTime }}</p>
        </div>
      </div>


      <!-- Detection Distribution -->
      <div class="bg-white rounded-lg shadow p-6 lg:col-span-2">
        <h2 class="text-lg font-semibold mb-2">Distribution</h2>
        
        <!-- Tab Navigation -->
        <div class="flex flex-wrap gap-2 mb-4">
          <button v-for="view in viewOptions" :key="view.value"
            @click="changeView(view.value)"
            :disabled="isUpdating"
            :class="[
              'px-4 py-2 rounded-md font-medium transition-colors duration-200',
              view.value === '6month' || view.value === 'year' ? 'hidden sm:block' : '',
              selectedView === view.value 
                ? 'bg-green-600 text-white' 
                : isUpdating
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            ]">
            {{ view.label }}
          </button>
        </div>
        
        <!-- Date Navigation -->
        <div class="flex items-center justify-between mb-4">
          <button @click="navigatePrevious"
            :disabled="isUpdating"
            :class="[
              'flex items-center px-2 sm:px-3 py-2 text-xs sm:text-sm font-medium rounded-md border transition-colors',
              isUpdating
                ? 'text-gray-400 bg-gray-100 border-gray-200 cursor-not-allowed'
                : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            ]">
            <svg class="w-3 h-3 sm:w-4 sm:h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
            </svg>
            <span class="hidden sm:inline">Previous</span>
            <span class="sm:hidden">Prev</span>
          </button>
          
          <span class="text-sm sm:text-lg font-medium text-gray-800 text-center px-2">{{ currentDateDisplay }}</span>
          
          <button @click="navigateNext"
            :disabled="isNextDisabled || isUpdating"
            :class="[
              'flex items-center px-2 sm:px-3 py-2 text-xs sm:text-sm font-medium rounded-md border transition-colors',
              (isNextDisabled || isUpdating)
                ? 'text-gray-400 bg-gray-100 border-gray-200 cursor-not-allowed' 
                : 'text-gray-700 bg-white border-gray-300 hover:bg-gray-50'
            ]">
            <span class="hidden sm:inline">Next</span>
            <span class="sm:hidden">Next</span>
            <svg class="w-3 h-3 sm:w-4 sm:h-4 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
            </svg>
          </button>
        </div>
        
        <!-- Canvas Container with fixed aspect ratio for Safari -->
        <div class="relative w-full h-[300px]">
          <canvas ref="detectionChart" class="absolute inset-0 w-full h-full"></canvas>
        </div>
      </div>

      <!-- Recordings Section -->
      <div class="bg-white rounded-lg shadow p-6 lg:col-span-3">
        <!-- Header with Selector -->
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold">Recordings</h2>
          <select v-model="recordingSort" @change="onSortChange"
            class="px-3 py-2 border border-gray-300 rounded-md text-sm bg-white focus:outline-none focus:ring-2 focus:ring-green-500">
            <option value="recent">Most Recent</option>
            <option value="best">Best Recordings</option>
          </select>
        </div>

        <!-- Recordings Grid (show 4 per page) -->
        <div v-if="currentPageRecordings.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-6">
	          <div v-for="(recording, index) in currentPageRecordings" :key="recording.id"
	            class="bg-gray-50 p-4 rounded-lg shadow-sm">
	            <div class="space-y-2">
	              <img :src="getSpectrogramUrl(recording.spectrogram_filename)"
	                :alt="`Spectrogram ${index + 1}`"
	                class="w-full rounded-lg bg-gray-900 cursor-pointer hover:opacity-90 transition-opacity"
	                @click="openSpectrogram(recording.spectrogram_filename)">
	              <audio controls class="w-full rounded-lg shadow-sm">
	                <source :src="getAudioUrl(recording.audio_filename)" type="audio/mpeg">
	                Your browser does not support the audio element.
	              </audio>
	            </div>
	          </div>
        </div>

        <!-- Empty state -->
        <div v-else class="text-center py-8 text-gray-500">
          No recordings available for this species.
        </div>

        <!-- Pagination: 1 2 3 4 -->
        <div v-if="totalPages > 1" class="flex justify-center items-center gap-2 mt-6">
          <button v-for="page in totalPages" :key="page"
            @click="currentPage = page"
            :class="[
              'w-10 py-1 rounded-md font-medium transition-colors text-center',
              page === currentPage
                ? 'bg-green-600 text-white'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            ]">
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
  </div>
</template>


<script>
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import Chart from 'chart.js/auto'
import SpectrogramModal from '@/components/SpectrogramModal.vue'
import { useDateNavigation } from '@/composables/useDateNavigation'
import { useChartHelpers } from '@/composables/useChartHelpers'
import { useChartColors } from '@/composables/useChartColors'
import { useSmartCrop } from '@/composables/useSmartCrop'
import api from '@/services/api'
import { getAudioUrl, getSpectrogramUrl } from '@/services/media'

export default {
  name: 'BirdDetails',
  components: {
    SpectrogramModal
  },
  setup() {
    const route = useRoute()
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

    const birdImageData = ref({
      imageUrl: '/default_bird.webp',
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
      anchorDateString,
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

        birdImageData.value = imageData

        // Calculate focal point for smart cropping
        await updateFocalPoint(imageData.imageUrl)

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

    // Handle sort change - re-fetch with new sort, reset to page 1
    const onSortChange = () => {
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
        console.log(`Updating chart for view: ${selectedView.value}, date: ${localDateString}`)

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

        const ctx = detectionChart.value.getContext('2d')

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
            onResize: (chart, size) => {
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
      currentPage,
      totalPages,
      currentPageRecordings,
      onSortChange,
      // Spectrogram modal
      selectedSpectrogramUrl,
      openSpectrogram,
      closeSpectrogram,
    }
  }
}
</script>
