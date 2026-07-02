<template>
  <div class="dashboard">
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
            v-if="hasLoadedOnce && !isDataEmpty && !detailedBirdActivityError"
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
        <CenteredMessage
          v-if="!hasLoadedOnce"
          variant="loading"
          container-class="h-[calc(100%-2rem)]"
        >
          Fetching the latest data...
        </CenteredMessage>
        <div
          v-else-if="!isDataEmpty && !detailedBirdActivityError"
          class="flex h-[calc(100%-2rem)]"
        >
          <div class="w-full lg:w-1/3 lg:pr-2 relative">
            <canvas
              ref="totalObservationsChart"
              class="h-full"
            />
            <SpeciesAxisLinks
              :ticks="speciesAxisLayout.ticks"
              :axis-left="speciesAxisLayout.axisLeft"
              :axis-width="speciesAxisLayout.axisWidth"
              :row-height="speciesAxisLayout.rowHeight"
            />
          </div>
          <div class="hidden lg:block lg:w-2/3 lg:pl-2 h-full">
            <!-- Inner wrapper is the positioning context: it has no padding,
                 so the absolute overlay's origin matches the canvas origin
                 (the chart's pixel coords are canvas-relative). -->
            <div class="h-full relative">
              <canvas
                ref="hourlyActivityHeatmap"
                class="h-full"
              />
              <TimeAxisLinks
                :ticks="timeAxisLayout.ticks"
                :axis-top="timeAxisLayout.axisTop"
                :axis-height="timeAxisLayout.axisHeight"
                :col-width="timeAxisLayout.colWidth"
                :date="timeAxisLayout.date"
              />
            </div>
          </div>
        </div>
        <CenteredMessage
          v-else-if="detailedBirdActivityError"
          variant="error"
          container-class="h-[calc(100%-2rem)]"
        >
          {{ detailedBirdActivityError }}
        </CenteredMessage>
        <CenteredMessage
          v-else
          variant="info"
          container-class="h-[calc(100%-2rem)]"
        >
          No bird activity recorded yet for today. Check back later!
        </CenteredMessage>
      </div>
      <!-- Latest Observation -->
      <div class="bg-white rounded-lg shadow p-4 lg:col-span-2 flex flex-col lg:h-[220px]">
        <h2 class="text-lg font-semibold mb-2 text-left">
          Latest Observation
        </h2>
        <CenteredMessage
          v-if="!hasLoadedOnce"
          variant="loading"
          container-class="flex-1"
        >
          Fetching the latest data...
        </CenteredMessage>
        <div
          v-else-if="latestObservationData && !latestObservationError"
          class="flex flex-col lg:flex-row items-center lg:items-stretch lg:space-x-6 w-full h-full"
        >
          <!-- Bird Profile -->
          <div
            class="flex flex-col items-center lg:flex-row lg:items-center space-y-1.5 lg:space-y-0 lg:space-x-3 lg:w-[250px] lg:pl-1 lg:pr-3 lg:h-full lg:relative lg:after:content-[''] lg:after:absolute lg:after:right-0 lg:after:top-4 lg:after:bottom-4 lg:after:w-px lg:after:bg-gray-200"
          >
            <router-link
              :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
              class="group flex-shrink-0"
            >
              <div class="relative">
                <img
                  :src="latestObservationimageUrl"
                  :alt="getDisplayCommonName(latestObservationData)"
                  class="w-[85px] h-[85px] object-cover rounded-full group-hover:opacity-80 transition-opacity duration-300"
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
            <div class="flex flex-col items-center lg:items-stretch lg:flex-1 lg:min-w-0 text-center lg:text-left">
              <router-link
                :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
                class="group block hover:text-blue-600 transition-colors duration-300"
              >
                <h3 class="text-[15px] font-medium group-hover:underline lg:line-clamp-2">
                  {{ getDisplayCommonName(latestObservationData) }}
                </h3>
              </router-link>
              <router-link
                :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
                class="group block transition-colors duration-300"
              >
                <p class="text-[13px] italic text-gray-600 group-hover:text-blue-600 group-hover:underline lg:line-clamp-2">
                  {{ latestObservationData.scientific_name }}
                </p>
              </router-link>
              <router-link
                :to="{ name: 'Table' }"
                class="text-[13px] text-gray-600 hover:text-blue-600 hover:underline transition-colors duration-300"
              >
                {{ formatTimestamp(latestObservationData.timestamp) }} {{ formatConfidence(latestObservationData.confidence) }}
              </router-link>
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
                class="bg-gray-200 h-12 lg:h-[110px] w-full rounded-lg overflow-hidden flex items-center justify-center"
              >
                <canvas
                  ref="spectrogramCanvas"
                  class="w-full h-full rounded-lg"
                  :class="{ 'cursor-pointer': latestObservationIsPlaying }"
                  @click="pauseLatestObservation"
                />
              </div>
            </div>
          </div>
        </div>
        <CenteredMessage
          v-else-if="latestObservationError"
          variant="error"
          container-class="flex-1"
        >
          {{ latestObservationError }}
        </CenteredMessage>
        <CenteredMessage
          v-else
          variant="info"
          container-class="flex-1"
        >
          No observations available yet.
        </CenteredMessage>
      </div>
      <!-- Observation Summary -->
      <div class="bg-white rounded-lg shadow p-4 flex flex-col">
        <h2 class="text-lg font-semibold mb-2">
          Observation Summary
        </h2>
        <CenteredMessage
          v-if="!hasLoadedOnce"
          variant="loading"
          container-class="flex-1"
        >
          Fetching the latest data...
        </CenteredMessage>
        <div
          v-else
          class="flex flex-col flex-1"
        >
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
                @click="selectSummaryPeriod(tab.value)"
              >
                {{ tab.label }}
              </button>
            </nav>
          </div>
          <CenteredMessage
            v-if="currentSummaryLoading"
            variant="loading"
            container-class="flex-1"
          >
            Fetching the latest data...
          </CenteredMessage>
          <ul
            v-else-if="!currentSummaryError && summaryEntries.length"
            class="space-y-1 text-sm"
          >
            <li
              v-for="entry in summaryEntries"
              :key="entry.key"
              class="flex items-baseline"
            >
              <span class="font-medium whitespace-nowrap mr-1">{{ formatSummaryKey(entry.key) }}:</span>
              <router-link
                v-if="(entry.key === 'mostCommonBird' || entry.key === 'rarestBird') && entry.value !== 'N/A'"
                :to="{ name: 'BirdDetails', params: { name: entry.value } }"
                :title="getSummaryBirdDisplay(currentPeriodSummary, entry.key)"
                class="font-medium hover:text-blue-600 hover:underline transition-colors duration-300 truncate min-w-0"
              >
                {{ getSummaryBirdDisplay(currentPeriodSummary, entry.key) }}
              </router-link>
              <span
                v-else
                class="truncate min-w-0"
              >{{ formatSummaryValue(entry.key, entry.value) }}</span>
            </li>
          </ul>
          <p
            v-else-if="!currentSummaryError"
            class="text-gray-500"
          >
            No summary data available for this period.
          </p>
          <CenteredMessage
            v-else
            variant="error"
            container-class="flex-1"
          >
            {{ currentSummaryError }}
          </CenteredMessage>
        </div>
      </div>

      <!-- Recent Observations -->
      <div class="bg-white rounded-lg shadow p-4 lg:col-span-2">
        <div class="flex items-center justify-between mb-2">
          <h2 class="text-lg font-semibold">
            Recent Observations
          </h2>
          <div class="flex items-center bg-gray-100 rounded-full p-0.5">
            <button
              v-for="opt in recentObsFilterOptions"
              :key="opt.label"
              :class="[
                'px-3 py-1 text-xs font-medium rounded-full transition-all duration-200',
                showUniqueSpecies === opt.value
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              ]"
              @click="toggleRecentObsFilter(opt.value)"
            >
              <span class="sm:hidden">{{ opt.shortLabel }}</span>
              <span class="hidden sm:inline">{{ opt.label }}</span>
            </button>
          </div>
        </div>
        <CenteredMessage
          v-if="!hasLoadedOnce"
          variant="loading"
          container-class="min-h-[200px]"
        >
          Fetching the latest data...
        </CenteredMessage>
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
                {{ getDisplayCommonName(observation) }}
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
                @click="showSpectrogram(observation.spectrogram_file_name, observation.spectrogram_sig)"
              >
                <SpectrogramIcon class="h-4 w-4" />
              </button>
            </div>
          </li>
        </ul>
        <CenteredMessage
          v-else-if="recentObservationsError"
          variant="error"
          container-class="min-h-[200px]"
        >
          {{ recentObservationsError }}
        </CenteredMessage>
        <CenteredMessage
          v-else
          variant="info"
          container-class="min-h-[200px]"
        >
          No recent observations available.
        </CenteredMessage>
      </div>


      <!-- Hourly Activity Chart -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-semibold mb-2">
          Hourly Activity
        </h2>
        <CenteredMessage
          v-if="!hasLoadedOnce"
          variant="loading"
          container-class="h-[220px]"
        >
          Fetching the latest data...
        </CenteredMessage>
        <div
          v-else-if="!hourlyBirdActivityError"
          class="relative h-[220px] w-full"
        >
          <canvas ref="hourlyActivityChart" />
        </div>
        <CenteredMessage
          v-else
          variant="error"
          container-class="h-[220px]"
        >
          {{ hourlyBirdActivityError }}
        </CenteredMessage>
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
import { faPlay, faPause, faCircleInfo } from '@fortawesome/free-solid-svg-icons';

	import { useFetchBirdData } from '@/composables/useFetchBirdData';
	import { useBirdCharts } from '@/composables/useBirdCharts';
	import { useChartHelpers } from '@/composables/useChartHelpers';
	import { useAudioPlayer } from '@/composables/useAudioPlayer';
	import { useAppStatus } from '@/composables/useAppStatus';
import { useTimeFormat } from '@/composables/useTimeFormat';
import SpectrogramModal from '@/components/SpectrogramModal.vue';
import SpectrogramIcon from '@/components/icons/SpectrogramIcon.vue';
import CenteredMessage from '@/components/CenteredMessage.vue';
import SpeciesAxisLinks from '@/components/SpeciesAxisLinks.vue';
import TimeAxisLinks from '@/components/TimeAxisLinks.vue';
import { getAudioUrl, getSpectrogramUrl } from '@/services/media'
import { getDisplayCommonName } from '@/utils/birdNames'
import { formatConfidence } from '@/utils/format'
import { createScrollPacer } from '@/utils/scrollPacer'
import { SPECTROGRAM_MAX_HZ } from '@/utils/spectrogram'

library.add(faPlay, faPause, faCircleInfo);
Chart.register(MatrixController, MatrixElement)

export default {
    name: 'Dashboard',
    components: {
        FontAwesomeIcon,
        SpectrogramModal,
        SpectrogramIcon,
        CenteredMessage,
        SpeciesAxisLinks,
        TimeAxisLinks
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
            summaryLoading,
            summaryErrors,

            // Loading state
            hasLoadedOnce,

            // Methods
            fetchDashboardData,
            fetchSummaryData,
            setActivityOrder,
            setRecentObsMode
        } = useFetchBirdData();

        // Audio state
        let audioCtx, audioAnalyser, source, frequencyDataArray, prevFrequencyDataArray, animationId;
        let spectrogramCanvasCtx, canvasWidth, canvasHeight;
        let signalStarted = false; // Latch: hold the scroll until the first non-silent frame (see drawSpectrogram)
        let audioClockRunning = false; // Tracks 'playing' vs 'waiting'/'pause' — gates scrolling on real playback progress
        const SPECTROGRAM_SUPERSAMPLE = 2; // Render at 2x internal resolution; browser downscales for smoother edges
        // Scroll speed in CSS px per second of wall-clock. 240 matches the look this
        // view had on a 120 Hz display when it stepped a fixed 2 CSS px per animation
        // frame — but now it's the same on every browser and refresh rate, instead of
        // tracking the rAF cadence (2x faster at 120 Hz than 60 Hz, slower on frame
        // drops), which made the same call render wider or narrower per display.
        const SPECTROGRAM_SCROLL_PX_PER_SEC = 240;
        // Wall-clock scroll pacing (see @/utils/scrollPacer). Paced in CSS px; the
        // backing store is SPECTROGRAM_SUPERSAMPLE× denser, so multiply when drawing.
        const scrollPacer = createScrollPacer(SPECTROGRAM_SCROLL_PX_PER_SEC);
        // Fixed dB window (not a per-playback peak), matching the Live Feed view:
        // floor -110 dBFS up to -30 dBFS — an 80 dB span. Brightness stays stable
        // instead of auto-gaining to the loudest recent bin.
        const SPEC_DB_FLOOR = -110;
        const SPEC_DB_RANGE = 80;
        // Gamma <1 brightens midtones without shifting the dark floor or white peak — keeps
        // the Greens_r identity but lifts the bulk of typical bin values up the ramp.
        const SPEC_BRIGHTNESS_GAMMA = 0.8;
        // matplotlib Greens_r: ColorBrewer 9-class Greens reversed (dark → light) and linearly
        // interpolated to 256 entries — same construction matplotlib uses for the saved spectrogram.
        const SPECTROGRAM_COLOR_LUT = (() => {
            const stops = [
                [0x00, 0x44, 0x1b], [0x00, 0x6d, 0x2c], [0x23, 0x8b, 0x45],
                [0x41, 0xab, 0x5d], [0x74, 0xc4, 0x76], [0xa1, 0xd9, 0x9b],
                [0xc7, 0xe9, 0xc0], [0xe5, 0xf5, 0xe0], [0xf7, 0xfc, 0xf5],
            ];
            const segs = stops.length - 1;
            return Array.from({ length: 256 }, (_, i) => {
                const x = (i / 255) * segs;
                const idx = Math.min(segs - 1, Math.floor(x));
                const f = x - idx;
                const a = stops[idx], b = stops[idx + 1];
                const r = Math.round(a[0] + (b[0] - a[0]) * f);
                const g = Math.round(a[1] + (b[1] - a[1]) * f);
                const bl = Math.round(a[2] + (b[2] - a[2]) * f);
                return `rgb(${r},${g},${bl})`;
            });
        })();
        // Idle background — pale green for an inviting "ready to play" look. Once playback
        // starts, the canvas scrolls fresh dark-green silence in from the right.
        const SPECTROGRAM_BG_COLOR = '#E8F5E9';
        const dbToLutIndex = (db) => {
            if (!Number.isFinite(db)) return 0;
            const t = (db - SPEC_DB_FLOOR) / SPEC_DB_RANGE;
            if (t <= 0) return 0;
            if (t >= 1) return 255;
            return Math.round(Math.pow(t, SPEC_BRIGHTNESS_GAMMA) * 255);
        };
        let audioElement;

        // Polling state (Fix 1: single merged interval)
        const POLL_INTERVAL = 9000
        let pollInterval;

        // Keep-alive state
        let isActive = true
        let hasBeenDeactivated = false
        let activationId = 0

        // Visibility change handler
        let visibilityHandler = null

        const currentSummaryPeriod = ref('today')
        const showLeastCommon = ref(false)
        const isActivityUpdating = ref(false)

        // Recent observations filter: false = All, true = Unique (one per species)
        const showUniqueSpecies = ref(
            localStorage.getItem('birdnet_recent_unique') === 'true'
        )
        const recentObsFilterOptions = [
            { label: 'All', shortLabel: 'All', value: false },
            { label: 'Unique', shortLabel: 'Uniq', value: true }
        ]

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
            createHourlyActivityChart: createHourlyChart,
            speciesAxisLayout,
            timeAxisLayout
        } = useBirdCharts()
        const { getLocalDateString } = useChartHelpers()

        // App status for coordinating with setup flow
        const { locationConfigured } = useAppStatus()

        // User-configurable time-format helper
        const { formatTime: formatTimeOfDay, formatHourLabel } = useTimeFormat()

        const currentOrder = () => showLeastCommon.value ? 'least' : 'most'
        const recentMode = () => showUniqueSpecies.value ? 'unique' : 'all'

        const toggleRecentObsFilter = (value) => {
            if (showUniqueSpecies.value === value) return
            showUniqueSpecies.value = value
            localStorage.setItem('birdnet_recent_unique', String(value))
            setRecentObsMode(recentMode())
        }

        const refreshDashboardData = async () => {
            // fetchDashboardData drops non-today summary periods; re-seed the
            // visible one so its tab keeps showing data through the refetch.
            const period = currentSummaryPeriod.value
            const staleSummary = period !== 'today' ? summaryData.value?.[period] : undefined
            await fetchDashboardData(currentOrder(), { recentMode: recentMode() })
            if (period !== 'today') {
                if (staleSummary) {
                    summaryData.value = { ...summaryData.value, [period]: staleSummary }
                }
                await fetchSummaryData(period, { force: true })
            }
        }

        const selectSummaryPeriod = async (period) => {
            currentSummaryPeriod.value = period
            if (!summaryData.value?.[period]) {
                await fetchSummaryData(period)
            }
        }

        // Single-in-flight poll loop: waits for the current fetch to
        // finish before scheduling the next one, so slow responses never
        // pile up and get discarded by the race guard.
        const startPolling = () => {
            if (pollInterval) return
            const poll = async () => {
                await refreshDashboardData()
                if (!isActive) return
                redrawCharts()
                pollInterval = setTimeout(poll, POLL_INTERVAL)
            }
            pollInterval = setTimeout(poll, POLL_INTERVAL)
        }

        const stopPolling = () => {
            if (pollInterval) {
                clearTimeout(pollInterval)
                pollInterval = null
            }
        }

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
                        await refreshDashboardData()
                        if (!isActive) return
                        redrawCharts()
                        startPolling()
                    }
                }
                document.addEventListener('visibilitychange', visibilityHandler)
            }

            await refreshDashboardData();
            if (!isActive) return  // Deactivated while fetching — bail out
            startPolling()

            // Wait for DOM to render canvas elements (they're behind v-if="!isDataEmpty")
            await nextTick()

            if (!hourlyBirdActivityError.value) {
                createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate: initialLoad.value });
            }
            if (!isDataEmpty.value) {
                createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: initialLoad.value, title: null });
                createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: initialLoad.value, title: null, date: getLocalDateString() });
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
            if (configured === true && !pollInterval) {
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

            pauseLatestObservation()

            if (audioCtx) {
                audioCtx.close()
                audioCtx = null
            }

            if (audioElement) {
                audioElement.src = ''
                audioElement = null
            }

            // Note: currentAudioElement cleanup for togglePlayBirdCall is handled by useAudioPlayer composable

            // Clean up other audio resources
            source = null
            audioAnalyser = null
            frequencyDataArray = null
            prevFrequencyDataArray = null
            signalStarted = false
            audioClockRunning = false
        })

        onDeactivated(() => {
            hasBeenDeactivated = true
            isActive = false
            stopPolling()

            pauseLatestObservation()

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
                await refreshDashboardData()
                if (!isActive || myActivation !== activationId) return
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

        const currentSummaryLoading = computed(() => (
            !!summaryLoading.value?.[currentSummaryPeriod.value]
        ))

        const currentSummaryError = computed(() => (
            summaryErrors.value?.[currentSummaryPeriod.value] || summaryError.value
        ))

        const summaryEntries = computed(() => (
            Object.entries(currentPeriodSummary.value || {})
                // Hide *Display variants (rendered separately via getSummaryBirdDisplay)
                // and *ScientificName fields (backend-only stable key used by
                // _localize_summary, not a user-visible summary entry).
                .filter(([key]) => !key.endsWith('Display') && !key.endsWith('ScientificName'))
                .map(([key, value]) => ({ key, value }))
        ))

        const isDataEmpty = computed(() =>
            detailedBirdActivityData.value.length === 0 ||
            detailedBirdActivityData.value.every(bird => bird.hourlyActivity.every(count => count === 0))
        )

        // Methods
        const drawSpectrogram = (nowMs) => {
            animationId = requestAnimationFrame(drawSpectrogram);

            // Only draw while the media clock is running ('playing' → 'waiting'/'pause') —
            // otherwise startup latency and buffering stalls scroll in blank (silent) columns.
            // Reset the pacer while stopped so a resume starts fresh rather than jumping
            // forward by the elapsed time.
            if (!audioClockRunning) { scrollPacer.reset(); return; }

            const frequencyResolution = audioCtx.sampleRate / audioAnalyser.fftSize;
            const minIndex = 0;
            const maxIndex = Math.min(
                Math.floor(SPECTROGRAM_MAX_HZ / frequencyResolution),
                audioAnalyser.frequencyBinCount - 1
            );
            const binSpan = maxIndex - minIndex;

            audioAnalyser.getFloatFrequencyData(frequencyDataArray);

            // 'playing' fires on the media element slightly before decoded samples reach the
            // analyser, which would scroll in a blank lead-in. Hold the scroll until the first
            // real signal: getFloatFrequencyData reports -Infinity for every bin during the
            // silent lead-in, so latch once the first finite bin appears.
            if (!signalStarted) {
                for (let i = minIndex; i <= maxIndex; i++) {
                    if (Number.isFinite(frequencyDataArray[i])) { signalStarted = true; break; }
                }
                if (!signalStarted) return;
            }

            // Columns (CSS px) to advance this frame from elapsed wall-clock time, scaled
            // to the supersampled backing store. 0 until a full column is due, and 0 after
            // a stall (e.g. a backgrounded tab) so we resume cleanly instead of smearing
            // one spectrum across the missed gap.
            const cols = scrollPacer.tick(nowMs);
            if (cols < 1) return;
            const stepX = cols * SPECTROGRAM_SUPERSAMPLE;

            // Scroll left by stepX. (Guarded against a zero-width copy.)
            if (stepX < canvasWidth) {
                const imageData = spectrogramCanvasCtx.getImageData(stepX, 0, canvasWidth - stepX, canvasHeight);
                spectrogramCanvasCtx.putImageData(imageData, 0, 0);
            }

            let index = 0;
            for (let i = minIndex; i <= maxIndex; i++) {
                const nextIndex = i < maxIndex
                    ? Math.floor(((i + 1 - minIndex) / binSpan) * canvasHeight)
                    : canvasHeight;
                const binHeight = Math.max(1, nextIndex - index);

                // Horizontal gradient interpolates each row's color from the previous frame's
                // intensity to the current — smooths the time axis without a post-process blur.
                const grad = spectrogramCanvasCtx.createLinearGradient(canvasWidth - stepX, 0, canvasWidth, 0);
                grad.addColorStop(0, SPECTROGRAM_COLOR_LUT[dbToLutIndex(prevFrequencyDataArray[i])]);
                grad.addColorStop(1, SPECTROGRAM_COLOR_LUT[dbToLutIndex(frequencyDataArray[i])]);
                spectrogramCanvasCtx.fillStyle = grad;
                spectrogramCanvasCtx.fillRect(canvasWidth - stepX, canvasHeight - index - binHeight, stepX, binHeight);

                index = nextIndex;
            }

            prevFrequencyDataArray.set(frequencyDataArray);
        };

        const initializeCanvas = () => {
            const canvas = spectrogramCanvas.value;
            if (canvas) {
                spectrogramCanvasCtx = canvas.getContext('2d', { willReadFrequently: true });
                canvasWidth = canvas.width = canvas.offsetWidth * SPECTROGRAM_SUPERSAMPLE;
                canvasHeight = canvas.height = canvas.offsetHeight * SPECTROGRAM_SUPERSAMPLE;

                spectrogramCanvasCtx.fillStyle = SPECTROGRAM_BG_COLOR;
                spectrogramCanvasCtx.fillRect(0, 0, canvasWidth, canvasHeight);
            } else {
                console.warn('Spectrogram canvas not found. Skipping canvas initialization.');
            }
        };

        const pauseLatestObservation = () => {
            if (!latestObservationIsPlaying.value || !audioElement) return;
            audioElement.pause();
            if (animationId) {
                cancelAnimationFrame(animationId);
                animationId = null;
            }
            latestObservationIsPlaying.value = false;
        };

        const playLatestObservation = () => {
            // Preserves position and rolling-max calibration vs. tearing down the audio element.
            if (audioElement && audioElement.currentTime > 0 && !audioElement.ended) {
                if (audioCtx?.state === 'suspended') audioCtx.resume();
                audioElement.play().catch((err) => {
                    console.warn('Failed to resume audio:', err);
                });
                animationId = requestAnimationFrame(drawSpectrogram);
                latestObservationIsPlaying.value = true;
                return;
            }

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
            audioAnalyser.fftSize = 1024;
            audioAnalyser.smoothingTimeConstant = 0.2; // Light temporal averaging — softens per-frame
                                                       // grain while keeping transients responsive
            frequencyDataArray = new Float32Array(audioAnalyser.frequencyBinCount);
            prevFrequencyDataArray = new Float32Array(audioAnalyser.frequencyBinCount);
            // Initialize prev far below the floor so the first frame's left edge starts dark.
            prevFrequencyDataArray.fill(-200);
            signalStarted = false;
            audioClockRunning = false;
	            const latestAudioUrl = getAudioUrl(latestObservationData.value?.bird_song_file_name, latestObservationData.value?.audio_sig)
	            if (!latestAudioUrl) return
	            audioElement = new Audio(latestAudioUrl);
	            audioElement.crossOrigin = "anonymous";
            source = audioCtx.createMediaElementSource(audioElement);
            source.connect(audioAnalyser);
            audioAnalyser.connect(audioCtx.destination);

            audioElement.addEventListener('ended', pauseLatestObservation);
            // 'playing' fires once frames actually advance (initial start, post-buffer, resume);
            // 'waiting'/'pause' mark buffering stalls and pauses. Covers resume latency too.
            audioElement.addEventListener('playing', () => { audioClockRunning = true; });
            audioElement.addEventListener('waiting', () => { audioClockRunning = false; });
            audioElement.addEventListener('pause', () => { audioClockRunning = false; });

	            audioElement.play().catch((err) => {
	                console.warn('Failed to play audio:', err)
	                latestObservationIsPlaying.value = false
	            });
	            animationId = requestAnimationFrame(drawSpectrogram);
	            latestObservationIsPlaying.value = true;
	        };

        const togglePlayBirdCall = (observation) => {
            if (!observation?.id) return
            const audioUrl = getAudioUrl(observation?.bird_song_file_name, observation?.audio_sig)
            if (!audioUrl) return
            audioTogglePlay(observation.id, audioUrl)
        };

        const formatTimestamp = (dateString) => {
            return formatTimeOfDay(dateString)
        }

        const formatSummaryKey = (key) => {
            return key.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase())
        }

        const formatSummaryValue = (key, value) => {
            if (key === 'mostActiveHour') {
                // Backend returns "H:00" or "N/A" — let the helper reformat per preference
                return value === 'N/A' ? value : formatHourLabel(value)
            }
            return typeof value === 'number' ? value.toLocaleString() : value
        }

        const getSummaryBirdDisplay = (summary, key) => {
            return summary?.[`${key}Display`] || summary?.[key] || ''
        }

	        const showSpectrogram = (spectrogramFileName, sig) => {
	            currentSpectrogramUrl.value = getSpectrogramUrl(spectrogramFileName, sig)
	            isSpectrogramModalVisible.value = true
	        }

        const toggleActivityOrder = async () => {
            if (isActivityUpdating.value) return
            showLeastCommon.value = !showLeastCommon.value
            isActivityUpdating.value = true
            try {
                setActivityOrder(currentOrder())
                await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: true, title: null })
                await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: true, title: null, date: getLocalDateString() })
            } finally {
                isActivityUpdating.value = false
            }
        }

        // Redraw charts function using composable methods
        const redrawCharts = async (animate = false) => {
            initialLoad.value = false;
            await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate, title: null });
            await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate, title: null, date: getLocalDateString() });
            await createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate });
        };

        return {
            locationConfigured,
            latestObservationData,
            recentObservationsData,
            currentSummaryPeriod,
            summaryPeriods,
            currentPeriodSummary,
            currentSummaryLoading,
            currentSummaryError,
            summaryEntries,
            hourlyActivityChart,
            isSpectrogramModalVisible,
            currentSpectrogramUrl,
            formatTimestamp,
            formatSummaryKey,
            formatSummaryValue,
            getDisplayCommonName,
            getSummaryBirdDisplay,
            formatConfidence,
            showSpectrogram,
            hourlyBirdActivityData,
            totalObservationsChart,
            speciesAxisLayout,
            timeAxisLayout,
            hourlyActivityHeatmap,
            isDataEmpty,
            latestObservationIsPlaying,
            spectrogramCanvas,
            playLatestObservation,
            pauseLatestObservation,
            detailedBirdActivityError,
            latestObservationError,
            summaryError,
            recentObservationsError,
            hourlyBirdActivityError,
            togglePlayBirdCall,
            currentPlayingId,
            latestObservationimageUrl,
            showLeastCommon,
            toggleActivityOrder,
            isActivityUpdating,
            hasLoadedOnce,
            showUniqueSpecies,
            recentObsFilterOptions,
            toggleRecentObsFilter,
            selectSummaryPeriod
        }
    }
}
</script>
