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

        <!-- Species Detection Distribution -->
        <div class="bg-white rounded-lg shadow p-4 mt-4">
            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-4">
                <h2 class="text-lg font-semibold mb-2">Species Detection Distribution</h2>
                <div class="flex flex-wrap items-center gap-4 justify-center lg:justify-end">
                    <!-- Species Dropdown -->
                    <div class="relative">
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Species:</label>
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
                    <div v-if="selectedSpecies" class="flex items-center space-x-4">
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">View:</label>
                            <select 
                                v-model="speciesView" 
                                @change="onSpeciesViewChange"
                                :disabled="isUpdatingSpecies"
                                class="px-3 py-1 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 text-sm"
                            >
                                <option value="day">Day</option>
                                <option value="week">Week</option>
                                <option value="month">Month</option>
                                <option value="6month">6 Month</option>
                                <option value="year">Year</option>
                            </select>
                        </div>

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
import axios from 'axios'

Chart.register(MatrixController, MatrixElement)

export default {
    name: 'Charts',
    setup() {
        const {
            detailedBirdActivityData,
            detailedBirdActivityError,
            fetchChartsData
        } = useFetchBirdData()

        // Date management - fix timezone issue by using local date
        const getLocalDateString = (date = new Date()) => {
            const year = date.getFullYear()
            const month = String(date.getMonth() + 1).padStart(2, '0')
            const day = String(date.getDate()).padStart(2, '0')
            return `${year}-${month}-${day}`
        }

        const selectedDate = ref(getLocalDateString())
        const maxDate = ref(getLocalDateString())
        const isLoading = ref(false)
        const isUpdating = ref(false)

        // Chart refs
        const totalObservationsChart = ref(null)
        const hourlyActivityHeatmap = ref(null)
        const totalObservationsChartInstance = ref(null)
        const hourlyActivityHeatmapInstance = ref(null)

        // Species dropdown and chart
        const allSpecies = ref([])
        const filteredSpecies = ref([])
        const selectedSpecies = ref(null)
        const searchQuery = ref('')
        const showDropdown = ref(false)
        const isLoadingSpecies = ref(false)
        const speciesView = ref('month')
        const speciesChart = ref(null)
        const speciesChartInstance = ref(null)
        const speciesChartError = ref(null)
        const isUpdatingSpecies = ref(false)
        const speciesAnchorDate = ref(new Date(selectedDate.value + 'T00:00:00'))

        // API
        const API_BASE_URL = '/api'

        // Color palette
        const colorPalette = {
            primary: '#2D6A4F',
            secondary: '#74C69D',
            accent1: '#D9ED92',
            accent2: '#B7E4C7',
            text: '#1B4332',
            background: '#F1FAEE',
            grid: 'rgba(45, 106, 79, 0.2)'
        }

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

        // Species chart computed properties
        const speciesDateDisplay = computed(() => {
            const date = speciesAnchorDate.value
            switch (speciesView.value) {
                case 'day':
                    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                case 'week':
                    const weekStart = new Date(date)
                    weekStart.setDate(date.getDate() - date.getDay())
                    const weekEnd = new Date(weekStart)
                    weekEnd.setDate(weekStart.getDate() + 6)
                    return `${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                case 'month':
                    return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
                case '6month':
                    const start = date.getMonth() < 6 ? 0 : 6
                    const end = start + 5
                    return `${new Date(date.getFullYear(), start).toLocaleDateString('en-US', { month: 'short' })} - ${new Date(date.getFullYear(), end).toLocaleDateString('en-US', { month: 'short' })}`
                case 'year':
                    return date.getFullYear().toString()
            }
        })

        const canGoForwardSpecies = computed(() => {
            const now = new Date()
            const anchor = speciesAnchorDate.value
            
            switch (speciesView.value) {
                case 'day':
                    return anchor.toDateString() !== now.toDateString()
                case 'week':
                    const thisWeekStart = new Date(now)
                    thisWeekStart.setDate(now.getDate() - now.getDay())
                    const anchorWeekStart = new Date(anchor)
                    anchorWeekStart.setDate(anchor.getDate() - anchor.getDay())
                    return anchorWeekStart < thisWeekStart
                case 'month':
                    return anchor.getFullYear() !== now.getFullYear() || anchor.getMonth() !== now.getMonth()
                case '6month':
                    const currentHalf = Math.floor(now.getMonth() / 6)
                    const anchorHalf = Math.floor(anchor.getMonth() / 6)
                    return anchor.getFullYear() !== now.getFullYear() || anchorHalf !== currentHalf
                case 'year':
                    return anchor.getFullYear() !== now.getFullYear()
            }
        })

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
            selectedDate.value = getLocalDateString()
            onDateChange()
        }

        const createCharts = async () => {
            // Add small delay to ensure DOM is ready
            await nextTick()
            createTotalObservationsChart(detailedBirdActivityData.value)
            createHourlyActivityHeatmap(detailedBirdActivityData.value)
        }

        const destroyChartIfExists = (canvasRef) => {
            if (!canvasRef.value) return
            
            // Use Chart.js best practice for getting existing chart
            const existingChart = Chart.getChart(canvasRef.value)
            if (existingChart) {
                existingChart.destroy()
            }
        }

        const createTotalObservationsChart = (data) => {
            if (!totalObservationsChart.value) return

            destroyChartIfExists(totalObservationsChart)
            const ctx = totalObservationsChart.value.getContext('2d')
            
            totalObservationsChartInstance.value = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.species),
                    datasets: [{
                        label: 'Total Detections',
                        data: data.map(d => d.hourlyActivity.reduce((sum, val) => sum + val, 0)),
                        backgroundColor: colorPalette.secondary,
                        borderColor: colorPalette.primary,
                        borderWidth: 1,
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Total Detections by Species',
                            font: { size: 14 },
                            color: colorPalette.text
                        }
                    },
                    scales: {
                        x: {
                            title: { display: true, text: 'Detections', color: colorPalette.text },
                            ticks: { color: colorPalette.text },
                        },
                        y: {
                            ticks: { color: colorPalette.text },
                        }
                    },
                    layout: {
                        padding: {
                            left: 10,
                            right: 10,
                            top: 0,
                            bottom: 0
                        }
                    }
                }
            })
        }

        const createHourlyActivityHeatmap = (data) => {
            if (!hourlyActivityHeatmap.value) return

            destroyChartIfExists(hourlyActivityHeatmap)
            const ctx = hourlyActivityHeatmap.value.getContext('2d')
            
            const species = data.map(d => d.species)
            const rowStats = data.map(d => ({
                min: Math.min(...d.hourlyActivity),
                max: Math.max(...d.hourlyActivity)
            }))

            const prepareDataForCategoryMatrix = (data) => {
                const hours = Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0') + ':00')
                return data.flatMap((d, index) =>
                    d.hourlyActivity.map((value, hourIndex) => ({
                        x: hours[hourIndex],
                        y: d.species,
                        v: value,
                        rowStats: rowStats[index]
                    }))
                )
            }

            hourlyActivityHeatmapInstance.value = new Chart(ctx, {
                type: 'matrix',
                data: {
                    datasets: [{
                        label: 'Hourly Bird Detections',
                        data: prepareDataForCategoryMatrix(data),
                        borderColor: 'white',
                        borderWidth: 1,
                        width: ({ chart }) => (chart.chartArea || {}).width / 24,
                        height: ({ chart }) => (chart.chartArea || {}).height / species.length,
                        backgroundColor: (context) => {
                            const { v: value, rowStats } = context.raw
                            const { min, max } = rowStats
                            const normalizedValue = (max > min) ? (value - min) / (max - min) : 0.5
                            const [r, g, b] = [116, 198, 157]
                            const alpha = Math.sqrt(normalizedValue)
                            return `rgba(${r}, ${g}, ${b}, ${alpha})`
                        },
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: {
                            left: 0,
                            right: 10,
                            top: 10,
                            bottom: 0
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Hourly Activity Heatmap',
                            font: { size: 14 },
                            color: colorPalette.text
                        },
                        tooltip: {
                            callbacks: {
                                title: (context) => {
                                    const { x, y } = context[0].raw
                                    return `${y} at ${x}`
                                },
                                label: (context) => {
                                    return `Detections: ${context.raw.v}`
                                },
                            },
                            backgroundColor: colorPalette.primary,
                            titleColor: colorPalette.background,
                            bodyColor: colorPalette.background,
                        }
                    },
                    scales: {
                        x: {
                            type: 'category',
                            labels: Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0') + ':00'),
                            ticks: {
                                maxRotation: 0,
                                autoSkip: false,
                                font: { size: 9 }
                            },
                            grid: { display: false },
                            title: {
                                display: true,
                                text: 'Hour of Day',
                                color: colorPalette.text
                            }
                        },
                        y: {
                            type: 'category',
                            labels: species,
                            reverse: false,
                            offset: true,
                            ticks: { display: false },
                            grid: { display: false },
                            border: { display: false },
                        }
                    }
                },
                plugins: [{
                    id: 'customGrid',
                    afterDatasetsDraw: (chart) => {
                        const { ctx, chartArea, scales: { x, y } } = chart
                        ctx.save()
                        ctx.strokeStyle = colorPalette.grid
                        ctx.lineWidth = 1

                        // Vertical lines
                        for (let i = 0; i <= 24; i++) {
                            const xPos = x.getPixelForValue(i - 0.5)
                            ctx.beginPath()
                            ctx.moveTo(xPos, chartArea.top)
                            ctx.lineTo(xPos, chartArea.bottom)
                            ctx.stroke()
                        }

                        // Horizontal lines
                        for (let i = 0; i <= species.length; i++) {
                            const yPos = y.getPixelForValue(i - 0.5)
                            ctx.beginPath()
                            ctx.moveTo(chartArea.left, yPos)
                            ctx.lineTo(chartArea.right, yPos)
                            ctx.stroke()
                        }

                        ctx.restore()
                    }
                }, {
                    id: 'matrixLabels',
                    afterDatasetsDraw: (chart) => {
                        const { ctx, chartArea, scales: { x, y } } = chart
                        const dataset = chart.data.datasets[0]

                        ctx.save()
                        ctx.font = 'bold 10px Arial'
                        ctx.textAlign = 'center'
                        ctx.textBaseline = 'middle'

                        dataset.data.forEach((datapoint) => {
                            const value = datapoint.v
                            if (value > 0) {
                                const xCenter = x.getPixelForValue(datapoint.x)
                                const yCenter = y.getPixelForValue(datapoint.y)

                                ctx.fillStyle = 'black'
                                ctx.fillText(value, xCenter, yCenter)
                            }
                        })
                        ctx.restore()
                    }
                }]
            })
        }

        // Species dropdown methods
        const fetchAllSpecies = async () => {
            isLoadingSpecies.value = true
            try {
                const response = await axios.get(`${API_BASE_URL}/species/all`)
                allSpecies.value = response.data
                filteredSpecies.value = response.data
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
                const response = await axios.get(
                    `${API_BASE_URL}/bird/${selectedSpecies.value.common_name}/detection_distribution`,
                    {
                        params: {
                            view: speciesView.value,
                            date: dateString
                        }
                    }
                )

                await nextTick()
                createSpeciesChart(response.data)
            } catch (error) {
                console.error('Error fetching species distribution:', error)
                speciesChartError.value = 'Failed to load detection data'
            } finally {
                isUpdatingSpecies.value = false
            }
        }

        const onSpeciesViewChange = () => {
            // Adjust anchor date when view changes
            const anchor = speciesAnchorDate.value
            
            switch (speciesView.value) {
                case 'week':
                    // Adjust to start of week
                    speciesAnchorDate.value = new Date(anchor)
                    speciesAnchorDate.value.setDate(anchor.getDate() - anchor.getDay())
                    break
                case 'month':
                    // Adjust to first of month
                    speciesAnchorDate.value = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
                    break
                case '6month':
                    // Adjust to start of 6-month period
                    const halfYear = Math.floor(anchor.getMonth() / 6) * 6
                    speciesAnchorDate.value = new Date(anchor.getFullYear(), halfYear, 1)
                    break
                case 'year':
                    // Adjust to January 1st
                    speciesAnchorDate.value = new Date(anchor.getFullYear(), 0, 1)
                    break
            }
            
            updateSpeciesChart()
        }

        const previousSpeciesPeriod = () => {
            if (isUpdatingSpecies.value) return
            
            const anchor = new Date(speciesAnchorDate.value)
            
            switch (speciesView.value) {
                case 'day':
                    anchor.setDate(anchor.getDate() - 1)
                    break
                case 'week':
                    anchor.setDate(anchor.getDate() - 7)
                    break
                case 'month':
                    anchor.setMonth(anchor.getMonth() - 1)
                    break
                case '6month':
                    anchor.setMonth(anchor.getMonth() - 6)
                    break
                case 'year':
                    anchor.setFullYear(anchor.getFullYear() - 1)
                    break
            }
            
            speciesAnchorDate.value = anchor
            updateSpeciesChart()
        }

        const nextSpeciesPeriod = () => {
            if (!canGoForwardSpecies.value || isUpdatingSpecies.value) return
            
            const anchor = new Date(speciesAnchorDate.value)
            
            switch (speciesView.value) {
                case 'day':
                    anchor.setDate(anchor.getDate() + 1)
                    break
                case 'week':
                    anchor.setDate(anchor.getDate() + 7)
                    break
                case 'month':
                    anchor.setMonth(anchor.getMonth() + 1)
                    break
                case '6month':
                    anchor.setMonth(anchor.getMonth() + 6)
                    break
                case 'year':
                    anchor.setFullYear(anchor.getFullYear() + 1)
                    break
            }
            
            speciesAnchorDate.value = anchor
            updateSpeciesChart()
        }

        const createSpeciesChart = (data) => {
            if (!speciesChart.value) return

            destroyChartIfExists(speciesChart)

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
                            text: `${selectedSpecies.value.common_name} - ${speciesView.value.charAt(0).toUpperCase() + speciesView.value.slice(1)} View`,
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
                            ticks: { color: colorPalette.text }
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

        // Lifecycle
        onMounted(async () => {
            await fetchChartsData(selectedDate.value)
            if (!isDataEmpty.value) {
                createCharts()
            }
            await fetchAllSpecies()
        })

        onUnmounted(() => {
            destroyChartIfExists(totalObservationsChart)
            destroyChartIfExists(hourlyActivityHeatmap)
            destroyChartIfExists(speciesChart)
        })

        // Watch for data changes
        watch(detailedBirdActivityData, (newData) => {
            if (newData && newData.length > 0 && !isDataEmpty.value) {
                createCharts()
            }
        })

        // Sync species chart date with main date when main date changes
        watch(selectedDate, (newDate) => {
            speciesAnchorDate.value = new Date(newDate + 'T00:00:00')
            if (selectedSpecies.value) {
                updateSpeciesChart()
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
            nextSpeciesPeriod
        }
    }
}
</script>