<template>
    <div class="dashboard">
        <!-- Dashboard content (hidden during setup via locationConfigured check) -->
        <div v-if="locationConfigured !== false" class="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <!-- Bird Activity Overview -->
            <div class="bg-white rounded-lg shadow p-4 lg:col-span-3 h-[300px] lg:h-[375px]">
                <h2 class="text-lg font-semibold mb-2">Bird Activity Overview</h2>
                <div v-if="!isDataEmpty && !detailedBirdActivityError" class="flex h-[calc(100%-2rem)]">
                    <div class="w-full lg:w-1/3 lg:pr-2">
                        <canvas ref="totalObservationsChart" class="h-full"></canvas>
                    </div>
                    <div class="hidden lg:block lg:w-2/3 lg:pl-2 h-full">
                        <canvas ref="hourlyActivityHeatmap" class="h-full"></canvas>
                    </div>
                </div>
                <div v-else-if="detailedBirdActivityError" class="flex items-center justify-center h-[calc(100%-2rem)]">
                    <p class="text-lg text-gray-500">{{ detailedBirdActivityError }}</p>
                </div>
                <div v-else class="flex items-center justify-center h-[calc(100%-2rem)]">
                    <p class="text-lg text-gray-500">No bird activity recorded yet for today. Check back later!</p>
                </div>
            </div>
            <!-- Latest Observation -->
            <div class="bg-white rounded-lg shadow p-4 lg:col-span-2 flex flex-col lg:h-[220px]">
                <h2 class="text-lg font-semibold mb-2 text-left">Latest Observation</h2>
                <div v-if="latestObservationData && !latestObservationError"
                    class="flex flex-col lg:flex-row items-center lg:items-stretch lg:space-x-2 w-full h-full">
                    <!-- Bird Profile -->
                    <div
                        class="flex flex-col items-center lg:items-start justify-center lg:justify-start space-y-1.5 lg:w-[180px] lg:pl-3 lg:h-full">
                        <router-link :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
                            class="group">
                            <div class="relative">
                                <img :src="latestObservationimageUrl" :alt="latestObservationData.common_name"
                                    class="w-[68px] h-[68px] object-cover rounded-full group-hover:opacity-80 transition-opacity duration-300">
                                <div
                                    class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                                    <font-awesome-icon icon="fas fa-info-circle" class="text-white text-xl" />
                                </div>
                            </div>
                        </router-link>
                        <div class="flex flex-col items-center lg:items-start text-center lg:text-left">
                            <router-link :to="{ name: 'BirdDetails', params: { name: latestObservationData.common_name } }"
                                class="group flex items-center hover:text-blue-600 transition-colors duration-300">
                                <h3 class="text-[15px] font-medium group-hover:underline lg:truncate lg:max-w-[160px]">{{ latestObservationData.common_name
                                    }}</h3>
                                <font-awesome-icon icon="fas fa-external-link-alt"
                                    class="ml-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex-shrink-0 hidden lg:inline-block" />
                            </router-link>
                            <p class="text-[13px] text-gray-600 lg:truncate lg:max-w-[160px]">{{ latestObservationData.scientific_name }}</p>
                            <p class="text-xs text-gray-600">{{ formatTimestamp(latestObservationData.timestamp) }}</p>
                        </div>
                    </div>
                    <!-- Call Player -->
                    <div class="w-full lg:flex-1 lg:h-full mt-3 lg:mt-0 flex items-center justify-center lg:pr-2"
                        ref="canvasContainer">
                        <div class="w-full h-full relative flex items-center justify-center">
                            <div v-show="!latestObservationIsPlaying"
                                class="absolute inset-0 flex justify-center items-center z-10">
                                <button @click="playLatestObservation"
                                    class="bg-black bg-opacity-50 hover:bg-opacity-70 text-white rounded-full flex items-center justify-center w-10 h-10 lg:w-14 lg:h-14 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-blue-300">
                                    <font-awesome-icon icon="fas fa-play" class="text-lg lg:text-2xl" />
                                </button>

                            </div>
                            <div
                                class="bg-gray-200 h-12 lg:h-24 w-full rounded-lg overflow-hidden flex items-center justify-center">
                                <canvas ref="spectrogramCanvas" class="w-full h-full rounded-lg"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
                <p v-else-if="latestObservationError" class="mt-2 text-gray-500">{{ latestObservationError }}</p>
                <p v-else class="mt-2 text-gray-500">No observations available yet.</p>
            </div>
            <!-- Observation Summary -->
            <div class="bg-white rounded-lg shadow p-4">
                <h2 class="text-lg font-semibold mb-2">Observation Summary</h2>
                <div v-if="!summaryError">
                    <div class="mb-3">
                        <nav class="flex space-x-1" aria-label="Tabs">
                            <button v-for="tab in summaryPeriods" :key="tab.value"
                                @click="currentSummaryPeriod = tab.value" :class="[
                                    'px-2 py-1 text-xs font-medium rounded-md',
                                    currentSummaryPeriod === tab.value
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'text-gray-500 hover:text-gray-700'
                                ]">
                                {{ tab.label }}
                            </button>
                        </nav>
                    </div>
                    <ul v-if="currentPeriodSummary && Object.keys(currentPeriodSummary).length"
                        class="space-y-1 text-sm">
                        <li v-for="(value, key) in currentPeriodSummary" :key="key">
                            <span class="font-medium">{{ formatSummaryKey(key) }}: </span> 
                            <router-link v-if="(key === 'mostCommonBird' || key === 'rarestBird') && value !== 'N/A'"
                                :to="{ name: 'BirdDetails', params: { name: value } }"
                                class="font-medium hover:text-blue-600 hover:underline transition-colors duration-300">
                                {{ value }}
                            </router-link>
                            <span v-else>{{ formatSummaryValue(key, value) }}</span>
                        </li>
                    </ul>
                    <p v-else class="text-gray-500">No summary data available for this period.</p>
                </div>
                <p v-else class="text-gray-500">{{ summaryError }}</p>
            </div>

            <!-- Recent Observations -->
            <div class="bg-white rounded-lg shadow p-4 lg:col-span-2">
                <h2 class="text-lg font-semibold mb-2">Recent Observations</h2>
                <ul v-if="recentObservationsData.length && !recentObservationsError" class="space-y-2">
                    <li v-for="observation in recentObservationsData" :key="observation.id"
                        class="flex items-center justify-between">
                        <div>
                            <router-link :to="{ name: 'BirdDetails', params: { name: observation.common_name } }"
                                class="font-medium hover:text-blue-600 hover:underline transition-colors duration-300">
                                {{ observation.common_name }}
                            </router-link>
                            <span class="text-xs text-gray-500 ml-2">{{ formatTimestamp(observation.timestamp) }}</span>
                            <span class="text-xs text-gray-500 ml-2 hidden lg:inline">
                                {{ formatConfidence(observation.confidence) }}
                            </span>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button @click="togglePlayBirdCall(observation)" class="text-blue-500 hover:text-blue-700">
                                <font-awesome-icon
                                    :icon="currentPlayingId === observation.id ? ['fas', 'pause'] : ['fas', 'play']"
                                    class="h-4 w-4" />
                            </button>
                            <button @click="showSpectrogram(observation.spectrogram_file_name)"
                                class="text-green-600 hover:text-green-700">
                                <font-awesome-icon :icon="['fas', 'circle-info']" class="h-4 w-4" />
                            </button>
                        </div>
                    </li>
                </ul>
                <p v-else-if="recentObservationsError" class="text-gray-500">{{ recentObservationsError }}</p>
                <p v-else class="text-gray-500">No recent observations available.</p>
            </div>


            <!-- Hourly Activity Chart -->
            <div class="bg-white rounded-lg shadow p-4">
                <h2 class="text-lg font-semibold mb-2">Hourly Activity</h2>
                <div v-if="!hourlyBirdActivityError" class="relative h-[220px] w-full">
                    <canvas ref="hourlyActivityChart"></canvas>
                </div>
                <p v-else class="text-gray-500">{{ hourlyBirdActivityError }}</p>
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
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import Chart from 'chart.js/auto'
import { MatrixController, MatrixElement } from 'chartjs-chart-matrix'

import { library } from '@fortawesome/fontawesome-svg-core';
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome';
import { faPlay, faPause, faCircleInfo, faExternalLinkAlt } from '@fortawesome/free-solid-svg-icons';

	import { useFetchBirdData } from '@/composables/useFetchBirdData';
	import { useBirdCharts } from '@/composables/useBirdCharts';
	import { useAudioPlayer } from '@/composables/useAudioPlayer';
	import { useAppStatus } from '@/composables/useAppStatus';
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

            // Methods
            fetchDashboardData
        } = useFetchBirdData();


        const currentSummaryPeriod = ref('today')

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
            togglePlay: audioTogglePlay
        } = useAudioPlayer()

        // Chart References
        const hourlyActivityChartInstance = ref(null)
        const totalObservationsChartInstance = ref(null)
        const hourlyActivityHeatmapInstance = ref(null)

	        const summaryPeriods = [
            { label: 'Today', value: 'today' },
            { label: '7-Day', value: 'week' },
            { label: '30-Day', value: 'month' },
            { label: 'All Time', value: 'allTime' }
        ]

        // Use bird charts composable for chart creation
        const {
            colorPalette,
            destroyChart,
            createTotalObservationsChart: createTotalObsChart,
            createHourlyActivityHeatmap: createHeatmap,
            createHourlyActivityChart: createHourlyChart
        } = useBirdCharts()

        // App status for coordinating with setup flow
        const { locationConfigured } = useAppStatus()

        // Start data fetching and charts
        const startDashboard = async () => {
            await fetchDashboardData();
            dataFetchInterval = setInterval(fetchDashboardData, 4500)

            if (!hourlyBirdActivityError.value) {
                createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate: initialLoad.value });
            }
            if (!isDataEmpty.value) {
                createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: initialLoad.value, title: null });
                createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: initialLoad.value, title: null });
            }
            chartUpdateInterval = setInterval(redrawCharts, 4500)
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

        // Watch for latest observation data to initialize canvas when it becomes available
        // Use { once: true } to only initialize once, not on every data refresh
        watch(latestObservationData, (newData) => {
            if (newData) {
                nextTick(() => {
                    initializeCanvas();
                });
            }
        }, { once: true });

        onUnmounted(() => {
            // Clear intervals
            if (dataFetchInterval) clearInterval(dataFetchInterval)
            if (chartUpdateInterval) clearInterval(chartUpdateInterval)

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
                const minLog = 1;
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

        // Redraw charts function using composable methods
        const redrawCharts = async () => {
            initialLoad.value = false;
            await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value, { animate: false, title: null });
            await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value, { animate: false, title: null });
            await createHourlyChart(hourlyActivityChart, hourlyBirdActivityData.value, { animate: false });
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
            latestObservationimageUrl
        }
    }
}
</script>
