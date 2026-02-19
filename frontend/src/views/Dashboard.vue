<template>
  <div class="dashboard">
    <!-- Update FAB -->
    <router-link
      v-if="systemUpdate.showUpdateIndicator.value"
      to="/settings"
      class="fixed bottom-4 right-4 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-full shadow-lg hidden md:flex items-center gap-2 z-50 transition-colors"
      title="System update available"
    >
      <svg
        class="w-5 h-5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M5 10l7-7 7 7M12 3v18"
        />
      </svg>
      <span class="text-sm font-medium">Update Available</span>
    </router-link>

    <!-- Dashboard content (hidden during setup via locationConfigured check) -->
    <div
      v-if="locationConfigured !== false"
      class="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4"
    >
      <!-- Bird Activity Overview -->
      <div class="bg-white rounded-lg shadow p-4 lg:col-span-3 h-[300px] lg:h-[375px]">
        <div class="flex items-center justify-between mb-2">
          <h2 class="text-lg font-semibold">
            Bird Activity Overview
          </h2>
          <button
            class="hidden sm:inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            :disabled="isActivityUpdating"
            @click="toggleActivityOrder"
          >
            Reverse
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="h-3.5 w-3.5 transition-transform duration-200"
              :class="{ 'rotate-180': showLeastCommon }"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fill-rule="evenodd"
                d="M5.293 7.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L10 4.414l-3.293 3.293a1 1 0 01-1.414 0zM5.293 13.707a1 1 0 010-1.414L10 7.586l4.707 4.707a1 1 0 01-1.414 1.414L10 10.414l-3.293 3.293a1 1 0 01-1.414 0z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
        </div>
        <div
          v-if="!hasLoadedOnce"
          class="flex items-center justify-center h-[calc(100%-2rem)]"
        >
          <p class="text-lg text-gray-400">
            Fetching the latest data...
          </p>
        </div>
        <div
          v-else-if="!isDataEmpty && !detailedBirdActivityError"
          class="flex h-[calc(100%-2rem)]"
        >
          <div class="w-full lg:w-1/3 lg:pr-2">
            <canvas
              ref="totalObservationsChart"
              class="h-full"
            />
          </div>
          <div class="hidden lg:block lg:w-2/3 lg:pl-2 h-full">
            <canvas
              ref="hourlyActivityHeatmap"
              class="h-full"
            />
          </div>
        </div>
        <div
          v-else-if="detailedBirdActivityError"
          class="flex items-center justify-center h-[calc(100%-2rem)]"
        >
          <p class="text-lg text-gray-500">
            {{ detailedBirdActivityError }}
          </p>
        </div>
        <div
          v-else
          class="flex items-center justify-center h-[calc(100%-2rem)]"
        >
          <p class="text-lg text-gray-500">
            No bird activity recorded yet for today. Check back later!
          </p>
        </div>
      </div>
      <!-- Latest Observation -->
      <div class="bg-white rounded-lg shadow p-4 lg:col-span-2 flex flex-col lg:h-[220px]">
        <h2 class="text-lg font-semibold mb-2 text-left">
          Latest Observation
        </h2>
        <div
          v-if="!hasLoadedOnce"
          class="flex-1 flex items-center justify-center"
        >
          <p class="text-gray-400">
            Fetching the latest data...
          </p>
        </div>
        <div
          v-else-if="latestObservationData && !latestObservationError"
          class="flex flex-col lg:flex-row items-center lg:items-stretch lg:space-x-2 w-full h-full"
        >
          <!-- Bird Profile -->
          <div
            class="flex flex-col items-center lg:items-start justify-center lg:justify-start space-y-1.5 lg:w-[180px] lg:pl-3 lg:h-full"
          >
            <router-link
              :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
              class="group"
            >
              <div class="relative">
                <img
                  :src="latestObservationimageUrl"
                  :alt="latestObservationData.common_name"
                  class="w-[68px] h-[68px] object-cover rounded-full group-hover:opacity-80 transition-opacity duration-300"
                >
                <div
                  class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                >
                  <font-awesome-icon
                    icon="fas fa-info-circle"
                    class="text-white text-xl"
                  />
                </div>
              </div>
            </router-link>
            <div class="flex flex-col items-center lg:items-start text-center lg:text-left">
              <router-link
                :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
                class="group flex items-center hover:text-blue-600 transition-colors duration-300"
              >
                <h3 class="text-[15px] font-medium group-hover:underline lg:truncate lg:max-w-[160px]">
                  {{ latestObservationData.common_name
                  }}
                </h3>
                <font-awesome-icon
                  icon="fas fa-external-link-alt"
                  class="ml-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex-shrink-0 hidden lg:inline-block"
                />
              </router-link>
              <p class="text-[13px] text-gray-600 lg:truncate lg:max-w-[160px]">
                {{ latestObservationData.scientific_name }}
              </p>
              <p class="text-xs text-gray-600">
                {{ formatTimestamp(latestObservationData.timestamp) }}
              </p>
            </div>
          </div>
          <!-- Call Player -->
          <div
            ref="canvasContainer"
            class="w-full lg:flex-1 lg:h-full mt-3 lg:mt-0 flex items-center justify-center lg:pr-2"
          >
            <div class="w-full h-full relative flex items-center justify-center">
              <div
                v-show="!latestObservationIsPlaying"
                class="absolute inset-0 flex justify-center items-center z-10"
              >
                <button
                  class="bg-black bg-opacity-50 hover:bg-opacity-70 text-white rounded-full flex items-center justify-center w-10 h-10 lg:w-14 lg:h-14 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-blue-300"
                  @click="playLatestObservation"
                >
                  <font-awesome-icon
                    icon="fas fa-play"
                    class="text-lg lg:text-2xl"
                  />
                </button>
              </div>
              <div
                class="bg-gray-200 h-12 lg:h-24 w-full rounded-lg overflow-hidden flex items-center justify-center"
              >
                <canvas
                  ref="spectrogramCanvas"
                  class="w-full h-full rounded-lg"
                />
              </div>
            </div>
          </div>
        </div>
        <div
          v-else-if="latestObservationError"
          class="flex-1 flex items-center justify-center"
        >
          <p class="text-gray-500">
            {{ latestObservationError }}
          </p>
        </div>
        <div
          v-else
          class="flex-1 flex items-center justify-center"
        >
          <p class="text-gray-500">
            No observations available yet.
          </p>
        </div>
      </div>
      <!-- Observation Summary -->
      <div class="bg-white rounded-lg shadow p-4 flex flex-col">
        <h2 class="text-lg font-semibold mb-2">
          Observation Summary
        </h2>
        <div
          v-if="!hasLoadedOnce"
          class="flex-1 flex items-center justify-center"
        >
          <p class="text-gray-400">
            Fetching the latest data...
          </p>
        </div>
        <div v-else-if="!summaryError">
          <div class="mb-3">
            <nav
              class="flex space-x-1"
              aria-label="Tabs"
            >
              <button
                v-for="tab in summaryPeriods"
                :key="tab.value"
                :class="[
                  'px-2 py-1 text-xs font-medium rounded-md',
                  currentSummaryPeriod === tab.value
                    ? 'bg-blue-100 text-blue-700'
                    : 'text-gray-500 hover:text-gray-700'
                ]"
                @click="currentSummaryPeriod = tab.value"
              >
                {{ tab.label }}
              </button>
            </nav>
          </div>
          <ul
            v-if="currentPeriodSummary && Object.keys(currentPeriodSummary).length"
            class="space-y-1 text-sm"
          >
            <li
              v-for="(value, key) in currentPeriodSummary"
              :key="key"
            >
              <span class="font-medium">{{ formatSummaryKey(key) }}: </span> 
              <router-link
                v-if="(key === 'mostCommonBird' || key === 'rarestBird') && value !== 'N/A'"
                :to="{ name: 'BirdDetails', params: { name: value } }"
                class="font-medium hover:text-blue-600 hover:underline transition-colors duration-300"
              >
                {{ value }}
              </router-link>
              <span v-else>{{ formatSummaryValue(key, value) }}</span>
            </li>
          </ul>
          <p
            v-else
            class="text-gray-500"
          >
            No summary data available for this period.
          </p>
        </div>
        <div
          v-else
          class="flex-1 flex items-center justify-center"
        >
          <p class="text-gray-500">
            {{ summaryError }}
          </p>
        </div>
      </div>

      <!-- Recent Observations -->
      <div class="bg-white rounded-lg shadow p-4 lg:col-span-2">
        <h2 class="text-lg font-semibold mb-2">
          Recent Observations
        </h2>
        <div
          v-if="!hasLoadedOnce"
          class="flex items-center justify-center min-h-[200px]"
        >
          <p class="text-gray-400">
            Fetching the latest data...
          </p>
        </div>
        <ul
          v-else-if="recentObservationsData.length && !recentObservationsError"
          class="space-y-2"
        >
          <li
            v-for="observation in recentObservationsData"
            :key="observation.id"
            class="flex items-center justify-between"
          >
            <div>
              <router-link
                :to="{ name: 'BirdDetails', params: { name: observation.common_name } }"
                class="font-medium hover:text-blue-600 hover:underline transition-colors duration-300"
              >
                {{ observation.common_name }}
              </router-link>
              <span class="text-xs text-gray-500 ml-2">{{ formatTimestamp(observation.timestamp) }}</span>
              <span class="text-xs text-gray-500 ml-2 hidden lg:inline">
                {{ formatConfidence(observation.confidence) }}
              </span>
            </div>
            <div class="flex items-center space-x-2">
              <button
                class="text-blue-500 hover:text-blue-700"
                @click="togglePlayBirdCall(observation)"
              >
                <font-awesome-icon
                  :icon="currentPlayingId === observation.id ? ['fas', 'pause'] : ['fas', 'play']"
                  class="h-4 w-4"
                />
              </button>
              <button
                class="text-green-600 hover:text-green-700"
                @click="showSpectrogram(observation.spectrogram_file_name)"
              >
                <font-awesome-icon
                  :icon="['fas', 'circle-info']"
                  class="h-4 w-4"
                />
              </button>
            </div>
          </li>
        </ul>
        <div
          v-else-if="recentObservationsError"
          class="flex items-center justify-center min-h-[200px]"
        >
          <p class="text-gray-500">
            {{ recentObservationsError }}
          </p>
        </div>
        <div
          v-else
          class="flex items-center justify-center min-h-[200px]"
        >
          <p class="text-gray-500">
            No recent observations available.
          </p>
        </div>
      </div>


      <!-- Hourly Activity Chart -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">
          Hourly Activity
        </h2>
        <div
          v-if="!hasLoadedOnce"
          class="flex items-center justify-center h-[220px]"
        >
          <p class="text-gray-400">
            Fetching the latest data...
          </p>
        </div>
        <div
          v-else-if="!hourlyBirdActivityError"
          class="relative h-[220px] w-full"
        >
          <canvas ref="hourlyActivityChart" />
        </div>
        <div
          v-else
          class="flex items-center justify-center h-[220px]"
        >
          <p class="text-gray-500">
            {{ hourlyBirdActivityError }}
          </p>
        </div>
      </div>
    </div>

    <!-- Spectrogram Modal -->
    <SpectrogramModal
      :is-visible="isSpectrogramModalVisible"
      :image-url="currentSpectrogramUrl"
      alt="Spectrogram"
      @close="isSpectrogramModalVisible = false"
    />
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, computed, watch, nextTick } from 'vue'
import Chart from 'chart.js/auto'
import { MatrixController, MatrixElement } from 'chartjs-chart-matrix'

import { library } from '@fortawesome/fontawesome-svg-core';
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome';
import { faPlay, faPause, faCircleInfo, faExternalLinkAlt } from '@fortawesome/free-solid-svg-icons';

	import { useFetchBirdData } from '@/composables/useFetchBirdData';
	import { useBirdCharts } from '@/composables/useBirdCharts';
	import { useAudioPlayer } from '@/composables/useAudioPlayer';
	import { useAppStatus } from '@/composables/useAppStatus';
	import { useSystemUpdate } from '@/composables/useSystemUpdate';
	import SpectrogramModal from '@/components/SpectrogramModal.vue';
	import { getAudioUrl, getSpectrogramUrl } from '@/services/media'

library.add(faPlay, faPause, faCircleInfo, faExternalLinkAlt);
Chart.register(MatrixController, MatrixElement)

export default {
    name: 'Dashboard',
    components: {
        FontAwesomeIcon,
        SpectrogramModal
    },
    setup() {
        const {
            // Dashboard data state
            hourlyBirdActivityData,
            detailedBirdActivityData,
            latestObservationData,
            recentObservationsData,
            summaryData,
            latestObservationimageUrl,

            // Dashboard error state
            hourlyBirdActivityError,
            detailedBirdActivityError,
            latestObservationError,
            recentObservationsError,
            summaryError,

            // Loading state
            hasLoadedOnce,

            // Methods
            fetchDashboardData,
            setActivityOrder
        } = useFetchBirdData();


        const currentSummaryPeriod = ref('today')
        const showLeastCommon = ref(false)
        const isActivityUpdating = ref(false)

        const isSpectrogramModalVisible = ref(false)
        const currentSpectrogramUrl = ref('')
        const hourlyActivityChart = ref(null)

        const totalObservationsChart = ref(null)
        const hourlyActivityHeatmap = ref(null)

        const latestObservationIsPlaying = ref(false)
        const initialLoad = ref(true)
        const spectrogramCanvas = ref(null)

        // Audio player composable for simple play/stop in Recent Observations list
        const {
            currentPlayingId,
            togglePlay: audioTogglePlay,
            stopAudio
        } = useAudioPlayer()

        const summaryPeriods = [
            { label: 'Today', value: 'today' },
            { label: '7-Day', value: 'week' },
            { label: '30-Day', value: 'month' },
            { label: 'All Time', value: 'allTime' }
        ]

        // Use bird charts composable for chart creation
        const {
            freezeChart,
            createTotalObservationsChart: createTotalObsChart,
            createHourlyActivityHeatmap: createHeatmap,
            createHourlyActivityChart: createHourlyChart
        } = useBirdCharts()

        // App status for coordinating with setup flow
        const { locationConfigured } = useAppStatus()

        // System update composable for silent auto-check
        const systemUpdate = useSystemUpdate()

        const currentOrder = () => showLeastCommon.value ? 'least' : 'most'

        // Idempotent polling helpers
        const startPolling = () => {
            if (!dataFetchInterval) {
                dataFetchInterval = setInterval(async () => {
                    await fetchDashboardData()
                    setActivityOrder(currentOrder())
                }, 9000)
            }
            if (!chartUpdateInterval) {
                chartUpdateInterval = setInterval(redrawCharts, 9000)
            }
        }

        const stopPolling = () => {
            if (dataFetchInterval) {
                clearInterval(dataFetchInterval)
                dataFetchInterval = null
            }
            if (chartUpdateInterval) {
                clearInterval(chartUpdateInterval)
                chartUpdateInterval = null
            }
        }

        // Visibility change handler
        let visibilityHandler = null

        // Start data fetching and charts
        const startDashboard = async () => {
            // Register visibility handler before any await so it's never
            // skipped if the component is deactivated mid-fetch (idempotent)
            if (!visibilityHandler) {
                visibilityHandler = async () => {
                    if (!isActive) return
                    if (document.hidden) {
                        stopPolling()
                    } else {
                        await fetchDashboardData()
                        if (!isActive) return
                        setActivityOrder(currentOrder())
                        redrawCharts()
                        startPolling()
                    }
                }
                document.addEventListener('visibilitychange', visibilityHandler)
            }

            await fetchDashboardData();
            if (!isActive) return  // Deactivated while fetching — bail out
            setActivityOrder(currentOrder());
            startPolling()

            // Silent auto-check for updates (no status messages, uses backend cache)
            systemUpdate.checkForUpdates({ silent: true }).catch(() => {})

            // Wait for DOM to render canvas elements (they're behind v-if="!isDataEmpty")
            await nextTick()

            if (!hourlyBirdActivityError.value) {
                createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate: initialLoad.value });
            }
            if (!isDataEmpty.value) {
                createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: initialLoad.value, title: null });
                createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: initialLoad.value, title: null });
            }

            // Initialize spectrogram canvas after DOM updates with new data
            nextTick(() => {
                initializeCanvas();
            });
        }

        // Lifecycle hooks
        onMounted(async () => {
            // Only start fetching if location is already configured
            if (locationConfigured.value === true) {
                await startDashboard();
            }
        });

        // Watch for location to become configured (after setup modal)
        watch(locationConfigured, async (configured) => {
            if (configured === true && !dataFetchInterval) {
                await startDashboard();
            }
        });

        onUnmounted(() => {
            // Clear intervals
            stopPolling()

            // Remove visibility handler
            if (visibilityHandler) {
                document.removeEventListener('visibilitychange', visibilityHandler)
                visibilityHandler = null
            }

            // Cancel animation frame
            if (animationId) {
                cancelAnimationFrame(animationId)
                animationId = null
            }

            // Clean up audio context and related resources
            if (audioCtx) {
                audioCtx.close()
                audioCtx = null
            }

            // Pause and clean up audio elements (for playLatestObservation with AudioContext)
            if (audioElement) {
                audioElement.pause()
                audioElement.src = ''
                audioElement = null
            }

            // Note: currentAudioElement cleanup for togglePlayBirdCall is handled by useAudioPlayer composable

            // Clean up other audio resources
            source = null
            audioAnalyser = null
            frequencyDataArray = null
        })

        onDeactivated(() => {
            hasBeenDeactivated = true
            isActive = false
            stopPolling()

            // Stop any playing audio (latest observation AudioContext player)
            if (audioElement) {
                audioElement.pause()
                cancelAnimationFrame(animationId)
                animationId = null
                latestObservationIsPlaying.value = false
            }

            // Suspend AudioContext to free browser resources while cached
            if (audioCtx && audioCtx.state === 'running') {
                audioCtx.suspend()
            }

            // Stop any playing audio (Recent Observations list player)
            stopAudio()
        })

        onActivated(async () => {
            isActive = true
            const myActivation = ++activationId
            if (hasBeenDeactivated && locationConfigured.value === true) {
                // Freeze old charts so ResizeObserver renders instantly
                // (no animation) when keep-alive re-inserts the DOM.
                freezeChart(totalObservationsChart)
                freezeChart(hourlyActivityHeatmap)
                freezeChart(hourlyActivityChart)

                // Immediately redraw with stale data + animation to give
                // the impression of fresh content while we fetch.
                await nextTick()
                await redrawCharts(true)

                // Fetch new data in background, then silently update.
                await fetchDashboardData()
                if (!isActive || myActivation !== activationId) return
                setActivityOrder(currentOrder())
                startPolling()
                await nextTick()
                await redrawCharts(false)
            }
        })

        // Computed properties
        const currentPeriodSummary = computed(() => {
            return summaryData.value && summaryData.value[currentSummaryPeriod.value]
                ? summaryData.value[currentSummaryPeriod.value]
                : {}
        })

        const isDataEmpty = computed(() =>
            detailedBirdActivityData.value.length === 0 ||
            detailedBirdActivityData.value.every(bird => bird.hourlyActivity.every(count => count === 0))
        )

        // Audio 
        let audioCtx, audioAnalyser, source, frequencyDataArray, animationId;
        let spectrogramCanvasCtx, canvasWidth, canvasHeight;
        let audioElement;

        // Interval
        let dataFetchInterval;
        let chartUpdateInterval;

        // Keep-alive state
        let isActive = true
        let hasBeenDeactivated = false
        let activationId = 0

        // Methods
        const drawSpectrogram = () => {
            const sampleRate = audioCtx.sampleRate; // Get the sample rate of the audio context
            const minFrequency = 2000; // 2kHz cutoff
            const maxFrequency = 12000; // 12kHz cutoff
            const fftSize = audioAnalyser.fftSize;
            const frequencyResolution = sampleRate / fftSize; // Frequency resolution per bin
            const minIndex = Math.floor(minFrequency / frequencyResolution); // Index corresponding to 2kHz
            const maxIndex = Math.floor(maxFrequency / frequencyResolution); // Index corresponding to 12kHz

            const useLogScale = false; // Use log scale on mobile, linear scale on desktop

            animationId = requestAnimationFrame(drawSpectrogram);

            audioAnalyser.getByteFrequencyData(frequencyDataArray);

            let imageData = spectrogramCanvasCtx.getImageData(1, 0, canvasWidth - 1, canvasHeight);
            spectrogramCanvasCtx.putImageData(imageData, 0, 0);

            const logScale = (value, max) => {
                const maxLog = Math.log(max + 1);
                return (Math.log(value + 1) / maxLog) * canvasHeight;
            };

            for (let i = minIndex; i <= maxIndex; i++) { // Only process frequencies between minIndex and maxIndex
                let value = frequencyDataArray[i];
                let ratio = value / 255;
                let hue = Math.round((1 - ratio) * 120); // Green to blue hues
                let sat = '60%';
                let lit = 30 + (70 * ratio) + '%';
                let index = useLogScale ? Math.floor(logScale(i, maxIndex)) : Math.floor(((i - minIndex) / (maxIndex - minIndex)) * canvasHeight);

                spectrogramCanvasCtx.beginPath();
                spectrogramCanvasCtx.strokeStyle = `hsl(${hue}, ${sat}, ${lit})`;
                spectrogramCanvasCtx.moveTo(canvasWidth - 1, canvasHeight - index);
                spectrogramCanvasCtx.lineTo(canvasWidth - 1, canvasHeight - index - 1);
                spectrogramCanvasCtx.stroke();
            }
        };

        const initializeCanvas = () => {
            const canvas = spectrogramCanvas.value;
            if (canvas) {
                spectrogramCanvasCtx = canvas.getContext('2d', { willReadFrequently: true });
                canvasWidth = canvas.width = canvas.offsetWidth;
                canvasHeight = canvas.height = canvas.offsetHeight;

                spectrogramCanvasCtx.fillStyle = '#E8F5E9';
                spectrogramCanvasCtx.fillRect(0, 0, canvasWidth, canvasHeight);
            } else {
                console.warn('Spectrogram canvas not found. Skipping canvas initialization.');
            }
        };

        const playLatestObservation = () => {
            // If already playing, stop and clean up
            if (latestObservationIsPlaying.value && audioElement) {
                audioElement.pause();
                cancelAnimationFrame(animationId);
                latestObservationIsPlaying.value = false;
                return;
            }

            // Clean up previous audio element if exists
            if (audioElement) {
                audioElement.pause();
                audioElement.src = '';
            }

            // Reuse or create AudioContext
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }

            // Resume context if suspended (browser autoplay policy)
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }

            audioAnalyser = audioCtx.createAnalyser();
            audioAnalyser.fftSize = 2048;
            frequencyDataArray = new Uint8Array(audioAnalyser.frequencyBinCount);
	            const latestAudioUrl = getAudioUrl(latestObservationData.value?.bird_song_file_name)
	            if (!latestAudioUrl) return
	            audioElement = new Audio(latestAudioUrl);
	            audioElement.crossOrigin = "anonymous";
            source = audioCtx.createMediaElementSource(audioElement);
            source.connect(audioAnalyser);
            audioAnalyser.connect(audioCtx.destination);

            audioElement.addEventListener('ended', () => {
                latestObservationIsPlaying.value = false;
                cancelAnimationFrame(animationId);
            });

	            audioElement.play().catch((err) => {
	                console.warn('Failed to play audio:', err)
	                latestObservationIsPlaying.value = false
	            });
	            drawSpectrogram();
	            latestObservationIsPlaying.value = true;
	        };

        const togglePlayBirdCall = (observation) => {
            if (!observation?.id) return
            const audioUrl = getAudioUrl(observation?.bird_song_file_name)
            if (!audioUrl) return
            audioTogglePlay(observation.id, audioUrl)
        };

        const formatTimestamp = (dateString) => {
            const date = new Date(dateString);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        const formatConfidence = (confidence) => {
            return `${Math.round(confidence * 100)}%`;
        }

        const formatSummaryKey = (key) => {
            return key.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase())
        }

        const formatSummaryValue = (key, value) => {
            if (key === 'mostActiveHour') return value
            return typeof value === 'number' ? value.toLocaleString() : value
        }

	        const showSpectrogram = (spectrogramFileName) => {
	            currentSpectrogramUrl.value = getSpectrogramUrl(spectrogramFileName)
	            isSpectrogramModalVisible.value = true
	        }

        const toggleActivityOrder = async () => {
            if (isActivityUpdating.value) return
            showLeastCommon.value = !showLeastCommon.value
            isActivityUpdating.value = true
            try {
                setActivityOrder(currentOrder())
                await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: true, title: null })
                await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: true, title: null })
            } finally {
                isActivityUpdating.value = false
            }
        }

        // Redraw charts function using composable methods
        const redrawCharts = async (animate = false) => {
            initialLoad.value = false;
            await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate, title: null });
            await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate, title: null });
            await createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate });
        };

        return {
            locationConfigured,
            latestObservationData,
            recentObservationsData,
            currentSummaryPeriod,
            summaryPeriods,
            currentPeriodSummary,
            hourlyActivityChart,
            isSpectrogramModalVisible,
            currentSpectrogramUrl,
            formatTimestamp,
            formatSummaryKey,
            formatSummaryValue,
            formatConfidence,
            showSpectrogram,
            hourlyBirdActivityData,
            totalObservationsChart,
            hourlyActivityHeatmap,
            isDataEmpty,
            latestObservationIsPlaying,
            spectrogramCanvas,
            playLatestObservation,
            detailedBirdActivityError,
            latestObservationError,
            summaryError,
            recentObservationsError,
            hourlyBirdActivityError,
            togglePlayBirdCall,
            currentPlayingId,
            latestObservationimageUrl,
            systemUpdate,
            showLeastCommon,
            toggleActivityOrder,
            isActivityUpdating,
            hasLoadedOnce
        }
    }
}
</script>
