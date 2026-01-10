<template>
    <div class="charts-view p-4">
        <div class="bg-white rounded-lg shadow p-4">
            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-4">
                <h2 class="text-lg font-semibold mb-2">Bird Activity Overview</h2>
                <div class="flex flex-wrap items-center gap-2 justify-center lg:justify-end">
                    <button 
                        @click="previousDay"
                        :class="[
                            'p-2 rounded-lg transition-all duration-200',
                            isUpdating 
                                ? 'text-gray-300 cursor-not-allowed' 
                                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        ]"
                        :disabled="isUpdating"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                    </button>
                    <input 
                        id="date-picker"
                        type="date" 
                        v-model="selectedDate" 
                        @change="onDateChange"
                        :max="maxDate"
                        :disabled="isUpdating"
                        :class="[
                            'px-3 py-1 border rounded-md text-sm',
                            isUpdating
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 focus:ring-blue-500 focus:border-blue-500'
                        ]"
                    />
                    <button 
                        @click="nextDay"
                        :class="[
                            'p-2 rounded-lg transition-all duration-200',
                            canGoForward 
                                ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100' 
                                : 'text-gray-300 cursor-not-allowed'
                        ]"
                        :disabled="!canGoForward || isUpdating"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
                        </svg>
                    </button>
                    <button
                        @click="goToToday"
                        :class="[
                            'font-semibold py-1 px-3 rounded-lg shadow text-sm transition-all duration-300',
                            isUpdating
                                ? 'bg-gray-400 text-gray-200 cursor-not-allowed'
                                : 'bg-blue-600 hover:bg-blue-700 text-white focus:outline-none focus:ring-2 focus:ring-blue-300'
                        ]"
                        :disabled="isUpdating"
                    >
                        Today
                    </button>
                </div>
            </div>
            
            <div v-if="!isDataEmpty && !detailedBirdActivityError" class="flex h-[300px] lg:h-[375px]">
                <div class="w-full lg:w-1/3 lg:pr-2">
                    <canvas ref="totalObservationsChart" class="h-full"></canvas>
                </div>
                <div class="hidden lg:block lg:w-2/3 lg:pl-2 h-full">
                    <canvas ref="hourlyActivityHeatmap" class="h-full"></canvas>
                </div>
            </div>
            <div v-else-if="detailedBirdActivityError" class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">{{ detailedBirdActivityError }}</p>
            </div>
            <div v-else class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">No bird activity recorded for {{ formattedDate }}. Try selecting a different date.</p>
            </div>
        </div>

        <!-- Detection Trends -->
        <div class="bg-white rounded-lg shadow p-4 mt-4">
            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-4">
                <h2 class="text-lg font-semibold mb-2">Detection Trends</h2>
                <div class="flex flex-wrap items-center gap-2 justify-center lg:justify-end">
                    <!-- Time Range Dropdown -->
                    <select
                        v-model="trendsTimeRange"
                        @change="onTrendsTimeRangeChange"
                        :disabled="isUpdatingTrends"
                        class="px-3 py-1 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 text-sm"
                    >
                        <option value="7">Week</option>
                        <option value="14">Two Week</option>
                        <option value="30">Month</option>
                        <option value="90">3 Month</option>
                        <option value="180">6 Month</option>
                        <option value="365">Year</option>
                    </select>

                    <!-- Date Navigation -->
                    <button
                        @click="previousTrendsPeriod"
                        :class="[
                            'p-2 rounded-lg transition-all duration-200',
                            isUpdatingTrends
                                ? 'text-gray-300 cursor-not-allowed'
                                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        ]"
                        :disabled="isUpdatingTrends"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
                        </svg>
                    </button>

                    <input
                        type="date"
                        v-model="trendsEndDate"
                        @change="onTrendsEndDateChange"
                        :max="trendsMaxDate"
                        :disabled="isUpdatingTrends"
                        :class="[
                            'px-3 py-1 border rounded-md text-sm',
                            isUpdatingTrends
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 focus:ring-blue-500 focus:border-blue-500'
                        ]"
                    />

                    <button
                        @click="nextTrendsPeriod"
                        :class="[
                            'p-2 rounded-lg transition-all duration-200',
                            canGoForwardTrends
                                ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                                : 'text-gray-300 cursor-not-allowed'
                        ]"
                        :disabled="!canGoForwardTrends || isUpdatingTrends"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
                        </svg>
                    </button>

                    <button
                        @click="goToTodayTrends"
                        :class="[
                            'font-semibold py-1 px-3 rounded-lg shadow text-sm transition-all duration-300',
                            isUpdatingTrends
                                ? 'bg-gray-400 text-gray-200 cursor-not-allowed'
                                : 'bg-blue-600 hover:bg-blue-700 text-white focus:outline-none focus:ring-2 focus:ring-blue-300'
                        ]"
                        :disabled="isUpdatingTrends"
                    >
                        Today
                    </button>
                </div>
            </div>

            <!-- Chart or Placeholder -->
            <div v-if="trendsChartData.data.length > 0 && !trendsChartError" class="h-[300px] lg:h-[375px]">
                <canvas ref="trendsChart" class="h-full"></canvas>
            </div>
            <div v-else-if="trendsChartError" class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">{{ trendsChartError }}</p>
            </div>
            <div v-else class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">No detection data available for the selected period.</p>
            </div>
        </div>

        <!-- Species Detection Distribution -->
        <div class="bg-white rounded-lg shadow p-4 mt-4">
            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-4">
                <h2 class="text-lg font-semibold mb-2">Species Detection Distribution</h2>
                <div class="flex flex-wrap items-center gap-4 justify-center lg:justify-end">
                    <!-- Species Dropdown -->
                    <div class="relative">
                        <div class="flex items-center space-x-2">
                            <div class="relative">
                                <input
                                    type="text"
                                    v-model="searchQuery"
                                    @focus="showDropdown = true"
                                    @blur="handleBlur"
                                    @input="filterSpecies"
                                    placeholder="Search or select species..."
                                    class="px-3 py-1 pr-8 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 text-sm w-48 lg:w-64"
                                    :disabled="isLoadingSpecies"
                                />
                                <button
                                    @click="toggleDropdown"
                                    class="absolute right-0 top-0 h-full px-2 text-gray-400 hover:text-gray-600"
                                    :disabled="isLoadingSpecies"
                                >
                                    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                                    </svg>
                                </button>
                                
                                <!-- Dropdown List -->
                                <div v-show="showDropdown && !isLoadingSpecies" 
                                    class="absolute z-10 mt-1 w-full bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-auto">
                                    <div v-if="filteredSpecies.length === 0" class="px-3 py-2 text-sm text-gray-500">
                                        No species found
                                    </div>
                                    <button
                                        v-for="species in filteredSpecies"
                                        :key="species.common_name"
                                        @mousedown="selectSpecies(species)"
                                        class="w-full text-left px-3 py-2 text-sm hover:bg-gray-100 focus:bg-gray-100 focus:outline-none"
                                    >
                                        <div class="font-medium">{{ species.common_name }}</div>
                                        <div class="text-xs text-gray-500">{{ species.scientific_name }}</div>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- View Options and Navigation -->
                    <div v-if="selectedSpecies" class="flex items-center space-x-2 lg:space-x-4">
                        <select
                            :value="speciesView"
                            @change="onSpeciesViewChange($event.target.value)"
                            :disabled="isUpdatingSpecies"
                            aria-label="View period"
                            class="px-3 py-1 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 text-sm"
                        >
                            <option value="day">Day</option>
                            <option value="week">Week</option>
                            <option value="month">Month</option>
                            <option value="6month">6 Month</option>
                            <option value="year">Year</option>
                        </select>

                        <!-- Navigation buttons -->
                        <div class="flex items-center space-x-2">
                            <button 
                                @click="previousSpeciesPeriod"
                                :class="[
                                    'p-2 rounded-lg transition-all duration-200',
                                    isUpdatingSpecies 
                                        ? 'text-gray-300 cursor-not-allowed' 
                                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                                ]"
                                :disabled="isUpdatingSpecies"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
                                </svg>
                            </button>
                            <span class="text-sm font-medium text-gray-700 min-w-[120px] text-center">{{ speciesDateDisplay }}</span>
                            <button 
                                @click="nextSpeciesPeriod"
                                :class="[
                                    'p-2 rounded-lg transition-all duration-200',
                                    canGoForwardSpecies 
                                        ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100' 
                                        : 'text-gray-300 cursor-not-allowed'
                                ]"
                                :disabled="!canGoForwardSpecies || isUpdatingSpecies"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Chart or Placeholder -->
            <div v-if="selectedSpecies && !speciesChartError" class="h-[300px] lg:h-[375px]">
                <canvas ref="speciesChart" class="h-full"></canvas>
            </div>
            <div v-else-if="speciesChartError" class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">{{ speciesChartError }}</p>
            </div>
            <div v-else class="flex items-center justify-center h-[300px] lg:h-[375px]">
                <p class="text-lg text-gray-500">Please select a bird species from the dropdown to view its detection distribution.</p>
            </div>
        </div>
    </div>
</template>

<script>
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import Chart from 'chart.js/auto'
import { MatrixController, MatrixElement } from 'chartjs-chart-matrix'
import { useFetchBirdData } from '@/composables/useFetchBirdData'
import { useBirdCharts } from '@/composables/useBirdCharts'
import { useDateNavigation } from '@/composables/useDateNavigation'
import { useChartHelpers } from '@/composables/useChartHelpers'
import api from '@/services/api'

Chart.register(MatrixController, MatrixElement)

export default {
    name: 'Charts',
    setup() {
        const {
            detailedBirdActivityData,
            detailedBirdActivityError,
            fetchChartsData,
            fetchTrendsData
        } = useFetchBirdData()

        // Use composables
        const {
            colorPalette,
            destroyChart,
            createTotalObservationsChart: createTotalObsChart,
            createHourlyActivityHeatmap: createHeatmap
        } = useBirdCharts()

        const { getLocalDateString } = useChartHelpers()

        // Use date navigation for species chart
        const {
            selectedView: speciesView,
            anchorDate: speciesAnchorDate,
            anchorDateString: speciesAnchorDateString,
            isUpdating: isUpdatingSpecies,
            dateDisplay: speciesDateDisplay,
            canGoForward: canGoForwardSpecies,
            navigatePrevious: navPreviousSpecies,
            navigateNext: navNextSpecies,
            changeView: changeSpeciesView,
            setAnchorDate: setSpeciesAnchorDate
        } = useDateNavigation({ initialView: 'month' })

        // Main date selection (for bird activity overview)
        const selectedDate = ref(getLocalDateString())
        const maxDate = ref(getLocalDateString())
        const isLoading = ref(false)
        const isUpdating = ref(false)

        // Chart refs
        const totalObservationsChart = ref(null)
        const hourlyActivityHeatmap = ref(null)

        // Species dropdown and chart
        const allSpecies = ref([])
        const filteredSpecies = ref([])
        const selectedSpecies = ref(null)
        const searchQuery = ref('')
        const showDropdown = ref(false)
        const isLoadingSpecies = ref(false)
        const speciesChart = ref(null)
        const speciesChartInstance = ref(null)
        const speciesChartError = ref(null)

        // Detection Trends chart
        const trendsChart = ref(null)
        const trendsChartInstance = ref(null)
        const trendsTimeRange = ref('30')  // Default 30 days
        const trendsEndDate = ref(getLocalDateString())
        const trendsMaxDate = ref(getLocalDateString())
        const isUpdatingTrends = ref(false)
        const trendsChartData = ref({ labels: [], data: [] })
        const trendsChartError = ref(null)

        // Computed properties
        const isDataEmpty = computed(() =>
            detailedBirdActivityData.value.length === 0 ||
            detailedBirdActivityData.value.every(bird => bird.hourlyActivity.every(count => count === 0))
        )

        const formattedDate = computed(() => {
            const date = new Date(selectedDate.value + 'T00:00:00')
            return date.toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            })
        })

        const canGoForward = computed(() => {
            return selectedDate.value < maxDate.value
        })

        const canGoForwardTrends = computed(() => {
            return trendsEndDate.value < trendsMaxDate.value
        })

        const trendsRangeLabels = {
            '7': 'Week',
            '14': 'Two Week',
            '30': 'Month',
            '90': '3 Month',
            '180': '6 Month',
            '365': 'Year'
        }

        const speciesViewLabels = {
            day: 'Day',
            week: 'Week',
            month: 'Month',
            '6month': '6 Month',
            year: 'Year'
        }

        // Methods
        const onDateChange = async () => {
            if (isUpdating.value) return
            
            isUpdating.value = true
            isLoading.value = true
            
            try {
                await fetchChartsData(selectedDate.value)
                if (!isDataEmpty.value) {
                    await createCharts()
                }
            } finally {
                isLoading.value = false
                isUpdating.value = false
            }
        }

        const previousDay = () => {
            if (isUpdating.value) return
            const date = new Date(selectedDate.value + 'T00:00:00')
            date.setDate(date.getDate() - 1)
            selectedDate.value = getLocalDateString(date)
            onDateChange()
        }

        const nextDay = () => {
            if (!canGoForward.value || isUpdating.value) return
            const date = new Date(selectedDate.value + 'T00:00:00')
            date.setDate(date.getDate() + 1)
            selectedDate.value = getLocalDateString(date)
            onDateChange()
        }

        const goToToday = () => {
            if (isUpdating.value) return
            const today = getLocalDateString()
            if (selectedDate.value === today) return
            selectedDate.value = today
            onDateChange()
        }

        const createCharts = async () => {
            // Add small delay to ensure DOM is ready
            await nextTick()
            await createTotalObsChart(totalObservationsChart, detailedBirdActivityData.value)
            await createHeatmap(hourlyActivityHeatmap, detailedBirdActivityData.value)
        }

        // Species dropdown methods
        const fetchAllSpecies = async () => {
            isLoadingSpecies.value = true
            try {
                const { data } = await api.get('/species/all')
                allSpecies.value = data
                filteredSpecies.value = data
            } catch (error) {
                console.error('Error fetching species list:', error)
                speciesChartError.value = 'Failed to load species list'
            } finally {
                isLoadingSpecies.value = false
            }
        }

        const filterSpecies = () => {
            const query = searchQuery.value.toLowerCase()
            filteredSpecies.value = allSpecies.value.filter(species =>
                species.common_name.toLowerCase().includes(query) ||
                species.scientific_name.toLowerCase().includes(query)
            )
        }

        const selectSpecies = (species) => {
            selectedSpecies.value = species
            searchQuery.value = species.common_name
            showDropdown.value = false
            speciesChartError.value = null
            updateSpeciesChart()
        }

        const toggleDropdown = () => {
            showDropdown.value = !showDropdown.value
            if (showDropdown.value) {
                searchQuery.value = ''
                filteredSpecies.value = allSpecies.value
            }
        }

        const handleBlur = () => {
            // Delay to allow click on dropdown items
            setTimeout(() => {
                showDropdown.value = false
                if (selectedSpecies.value) {
                    searchQuery.value = selectedSpecies.value.common_name
                }
            }, 200)
        }

        const updateSpeciesChart = async () => {
            if (!selectedSpecies.value || isUpdatingSpecies.value) return

            isUpdatingSpecies.value = true
            speciesChartError.value = null

            try {
                const dateString = getLocalDateString(speciesAnchorDate.value)
                const { data } = await api.get(
                    `/bird/${selectedSpecies.value.common_name}/detection_distribution`,
                    {
                        params: {
                            view: speciesView.value,
                            date: dateString
                        }
                    }
                )

                await nextTick()
                createSpeciesChart(data)
            } catch (error) {
                console.error('Error fetching species distribution:', error)
                speciesChartError.value = 'Failed to load detection data'
            } finally {
                isUpdatingSpecies.value = false
            }
        }

        // Wrapped navigation functions that trigger chart updates
        const onSpeciesViewChange = (newView) => {
            changeSpeciesView(newView)
            updateSpeciesChart()
        }

        const previousSpeciesPeriod = () => {
            navPreviousSpecies()
            updateSpeciesChart()
        }

        const nextSpeciesPeriod = () => {
            navNextSpecies()
            updateSpeciesChart()
        }

        const createSpeciesChart = (data) => {
            if (!speciesChart.value) return

            destroyChart(speciesChart)

            const viewLabel = speciesViewLabels[speciesView.value] || speciesView.value
            const ctx = speciesChart.value.getContext('2d')
            speciesChartInstance.value = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: 'Detections',
                        data: data.data,
                        backgroundColor: colorPalette.secondary,
                        borderColor: colorPalette.primary,
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: `${selectedSpecies.value.common_name} - ${viewLabel} View`,
                            font: { size: 14 },
                            color: colorPalette.text
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Number of Detections',
                                color: colorPalette.text
                            },
                            ticks: {
                                color: colorPalette.text,
                                callback: (value) => {
                                    const numericValue = Number(value)
                                    return Number.isInteger(numericValue) ? numericValue.toString() : ''
                                }
                            }
                        },
                        x: {
                            title: {
                                display: true,
                                text: 'Time Period',
                                color: colorPalette.text
                            },
                            ticks: {
                                color: colorPalette.text,
                                maxRotation: 45,
                                minRotation: 45
                            }
                        }
                    }
                }
            })
        }

        // Detection Trends chart methods
        const getTrendsStartDate = () => {
            const endDate = new Date(trendsEndDate.value + 'T00:00:00')
            const daysBack = parseInt(trendsTimeRange.value) - 1
            const startDate = new Date(endDate)
            startDate.setDate(startDate.getDate() - daysBack)
            return getLocalDateString(startDate)
        }

        const updateTrendsChart = async () => {
            if (isUpdatingTrends.value) return

            isUpdatingTrends.value = true
            trendsChartError.value = null

            try {
                const startDate = getTrendsStartDate()
                const endDate = trendsEndDate.value

                const data = await fetchTrendsData(startDate, endDate)

                if (data) {
                    trendsChartData.value = data
                    await nextTick()
                    createTrendsChart(data)
                }
            } catch (error) {
                console.error('Error updating trends chart:', error)
                trendsChartError.value = 'Failed to load detection trends'
            } finally {
                isUpdatingTrends.value = false
            }
        }

        const createTrendsChart = (data) => {
            if (!trendsChart.value) return

            destroyChart(trendsChart)

            const ctx = trendsChart.value.getContext('2d')

            // Format labels for display (shorter date format)
            const displayLabels = data.labels.map(dateStr => {
                const date = new Date(dateStr + 'T00:00:00')
                return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            })

            const rangeLabel = trendsRangeLabels[trendsTimeRange.value] || `${trendsTimeRange.value} Days`

            trendsChartInstance.value = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: displayLabels,
                    datasets: [{
                        label: 'Total Detections',
                        data: data.data,
                        borderColor: colorPalette.secondary,
                        backgroundColor: colorPalette.secondary + '40',  // 25% opacity
                        fill: false,
                        tension: 0.4,  // Cubic interpolation for smooth curves
                        pointRadius: data.data.length > 60 ? 0 : 3,  // Hide points for long ranges
                        pointHoverRadius: 5,
                        pointBackgroundColor: colorPalette.secondary
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: `Daily Detections - ${rangeLabel}`,
                            font: { size: 14 },
                            color: colorPalette.text
                        },
                        tooltip: {
                            callbacks: {
                                title: (context) => {
                                    // Show full date in tooltip
                                    const index = context[0].dataIndex
                                    const fullDate = data.labels[index]
                                    const date = new Date(fullDate + 'T00:00:00')
                                    return date.toLocaleDateString('en-US', {
                                        weekday: 'short',
                                        month: 'short',
                                        day: 'numeric',
                                        year: 'numeric'
                                    })
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Detections',
                                color: colorPalette.text
                            },
                            ticks: {
                                color: colorPalette.text,
                                callback: (value) => {
                                    return Number.isInteger(value) ? value : ''
                                }
                            }
                        },
                        x: {
                            title: {
                                display: true,
                                text: 'Date',
                                color: colorPalette.text
                            },
                            ticks: {
                                color: colorPalette.text,
                                maxRotation: 45,
                                minRotation: 45,
                                // Auto-skip labels for readability
                                autoSkip: true,
                                maxTicksLimit: 15
                            }
                        }
                    }
                }
            })
        }

        const onTrendsTimeRangeChange = () => {
            updateTrendsChart()
        }

        const onTrendsEndDateChange = () => {
            updateTrendsChart()
        }

        const previousTrendsPeriod = () => {
            if (isUpdatingTrends.value) return
            const date = new Date(trendsEndDate.value + 'T00:00:00')
            const daysBack = parseInt(trendsTimeRange.value)
            date.setDate(date.getDate() - daysBack)
            trendsEndDate.value = getLocalDateString(date)
            updateTrendsChart()
        }

        const nextTrendsPeriod = () => {
            if (!canGoForwardTrends.value || isUpdatingTrends.value) return
            const date = new Date(trendsEndDate.value + 'T00:00:00')
            const daysForward = parseInt(trendsTimeRange.value)
            date.setDate(date.getDate() + daysForward)
            // Cap at today
            const today = new Date()
            if (date > today) {
                trendsEndDate.value = getLocalDateString(today)
            } else {
                trendsEndDate.value = getLocalDateString(date)
            }
            updateTrendsChart()
        }

        const goToTodayTrends = () => {
            if (isUpdatingTrends.value) return
            const today = getLocalDateString()
            if (trendsEndDate.value === today) return
            trendsEndDate.value = today
            updateTrendsChart()
        }

        // Lifecycle
        onMounted(async () => {
            await fetchChartsData(selectedDate.value)
            if (!isDataEmpty.value) {
                createCharts()
            }
            await fetchAllSpecies()
            await updateTrendsChart()
        })

        onUnmounted(() => {
            destroyChart(totalObservationsChart)
            destroyChart(hourlyActivityHeatmap)
            destroyChart(speciesChart)
            destroyChart(trendsChart)
        })

        // Watch for data changes
        watch(detailedBirdActivityData, (newData) => {
            if (newData && newData.length > 0 && !isDataEmpty.value) {
                createCharts()
            }
        })


        return {
            selectedDate,
            maxDate,
            totalObservationsChart,
            hourlyActivityHeatmap,
            isDataEmpty,
            detailedBirdActivityError,
            formattedDate,
            onDateChange,
            canGoForward,
            isLoading,
            isUpdating,
            previousDay,
            nextDay,
            goToToday,
            // Species dropdown and chart
            allSpecies,
            filteredSpecies,
            selectedSpecies,
            searchQuery,
            showDropdown,
            isLoadingSpecies,
            speciesView,
            speciesChart,
            speciesChartError,
            isUpdatingSpecies,
            filterSpecies,
            selectSpecies,
            toggleDropdown,
            handleBlur,
            updateSpeciesChart,
            speciesDateDisplay,
            canGoForwardSpecies,
            onSpeciesViewChange,
            previousSpeciesPeriod,
            nextSpeciesPeriod,
            // Detection Trends chart
            trendsChart,
            trendsTimeRange,
            trendsEndDate,
            trendsMaxDate,
            trendsChartData,
            trendsChartError,
            isUpdatingTrends,
            canGoForwardTrends,
            onTrendsTimeRangeChange,
            onTrendsEndDateChange,
            previousTrendsPeriod,
            nextTrendsPeriod,
            goToTodayTrends
        }
    }
}
</script>
