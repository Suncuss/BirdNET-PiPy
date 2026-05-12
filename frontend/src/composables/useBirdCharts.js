import { nextTick, ref } from 'vue'
import Chart from 'chart.js/auto'
import { useChartColors } from './useChartColors'
import { useChartHelpers } from './useChartHelpers'
import { useTimeFormat } from './useTimeFormat'
import { getDisplaySpeciesName } from '@/utils/birdNames'

/**
 * Composable for creating bird activity charts.
 * Provides factory functions for Total Observations bar chart and Hourly Activity heatmap.
 */
export function useBirdCharts() {
  const { colorPalette, secondaryRGB } = useChartColors()
  const { resolveCanvas, destroyChart, freezeChart, generateHourLabels, calculateRowStats, prepareDataForCategoryMatrix } = useChartHelpers()
  const { formatHourLabel } = useTimeFormat()

  // Reactive layout state for the species-axis HTML overlay (SpeciesAxisLinks).
  // Populated by createTotalObservationsChart via a Chart.js afterLayout plugin.
  const speciesAxisLayout = ref({ ticks: [], axisLeft: 0, axisWidth: 0, rowHeight: 0 })

  /**
   * Create custom grid plugin for matrix/heatmap charts.
   * Draws grid lines around each cell.
   * @param {string[]} species - Array of species names
   * @returns {Object} Chart.js plugin
   */
  const createCustomGridPlugin = (species) => ({
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
  })

  /**
   * Create matrix labels plugin for heatmap charts.
   * Draws detection count values inside cells.
   * @returns {Object} Chart.js plugin
   */
  const createMatrixLabelsPlugin = () => ({
    id: 'matrixLabels',
    afterDatasetsDraw: (chart) => {
      const { ctx, scales: { x, y } } = chart
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
  })

  /**
   * Create Total Observations horizontal bar chart.
   * Shows detection count per species.
   *
   * @param {Ref|HTMLCanvasElement} canvasRef - Vue ref to canvas element or canvas directly
   * @param {Array<{species: string, hourlyActivity: number[]}>} data - Bird activity data
   * @param {Object} options - Chart options
   * @param {boolean} options.animate - Enable animation (default: true)
   * @param {string} options.title - Chart title (default: 'Total Detections by Species')
   * @returns {Promise<Chart|null>} Chart instance or null if canvas not available
   *
   * Side effect: emits axis tick positions into `speciesAxisLayout` (returned from useBirdCharts)
   * so an HTML overlay can render the species labels as real router-links. The canvas y-axis
   * ticks are rendered transparent — they still reserve layout width but are not visible.
   */
  const createTotalObservationsChart = async (canvasRef, data, options = {}) => {
    const { animate = true, title = 'Total Detections by Species' } = options

    const canvas = resolveCanvas(canvasRef)
    if (!canvas) {
      return null
    }

    await nextTick()

    // In-place update if a bar chart already exists on this canvas
    const existing = Chart.getChart(canvas)
    if (existing && existing.config.type === 'bar') {
      if (existing.$speciesAxisCtx) existing.$speciesAxisCtx.data = data
      existing.data.labels = data.map(d => getDisplaySpeciesName(d))
      existing.data.datasets[0].data = data.map(d => d.hourlyActivity.reduce((sum, val) => sum + val, 0))
      existing.options.animation = animate
      existing.update()
      return existing
    }

    destroyChart(canvasRef)
    const ctx = canvas.getContext('2d')

    // Shared mutable context: plugin closure reads `data` from here so in-place updates
    // (polling refresh, Most/Least toggle) are reflected on the next layout pass.
    const speciesAxisCtx = { data }

    const speciesLayoutPlugin = {
      id: 'speciesLayoutEmitter',
      afterLayout: (chart) => {
        const yScale = chart.scales?.y
        if (!yScale) return
        const speciesData = speciesAxisCtx.data || []
        const labels = chart.data.labels || []
        const ticks = speciesData.map((d, i) => ({
          y: yScale.getPixelForValue(i),
          label: labels[i],
          commonName: d.species
        }))
        const rowHeight = speciesData.length > 0
          ? (yScale.bottom - yScale.top) / speciesData.length
          : 0
        const axisLeft = yScale.left
        const axisWidth = yScale.width

        // Skip the ref write when geometry and species set are unchanged — avoids
        // a Vue re-render of the overlay on every polling refresh that returned the
        // same data.
        const prev = speciesAxisLayout.value
        if (prev.ticks.length === ticks.length
          && prev.axisLeft === axisLeft
          && prev.axisWidth === axisWidth
          && prev.rowHeight === rowHeight
          && prev.ticks.every((t, i) => t.commonName === ticks[i].commonName && t.y === ticks[i].y && t.label === ticks[i].label)) {
          return
        }

        speciesAxisLayout.value = { ticks, axisLeft, axisWidth, rowHeight }
      }
    }

    const chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => getDisplaySpeciesName(d)),
        datasets: [{
          label: 'Total Detections',
          data: data.map(d => d.hourlyActivity.reduce((sum, val) => sum + val, 0)),
          backgroundColor: colorPalette.secondary,
          borderColor: colorPalette.primary,
          borderWidth: 1
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        animation: animate,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: title ? {
            display: true,
            text: title,
            font: { size: 14 },
            color: colorPalette.text
          } : { display: false }
        },
        scales: {
          x: {
            title: { display: true, text: 'Detections', color: colorPalette.text },
            ticks: { color: colorPalette.text, precision: 0 }
          },
          y: {
            // Transparent ticks reserve layout space; HTML overlay renders the real labels as links.
            ticks: { color: 'transparent' }
          }
        },
        layout: {
          padding: { left: 10, right: 10, top: 0, bottom: 0 }
        }
      },
      plugins: [speciesLayoutPlugin]
    })

    chart.$speciesAxisCtx = speciesAxisCtx
    return chart
  }

  /**
   * Create Hourly Activity Heatmap (matrix chart).
   * Shows detection counts per species per hour with color intensity.
   *
   * @param {Ref|HTMLCanvasElement} canvasRef - Vue ref to canvas element or canvas directly
   * @param {Array<{species: string, hourlyActivity: number[]}>} data - Bird activity data
   * @param {Object} options - Chart options
   * @param {boolean} options.animate - Enable animation (default: true)
   * @param {string} options.title - Chart title (default: 'Hourly Activity Heatmap')
   * @returns {Promise<Chart|null>} Chart instance or null if canvas not available
   */
  const createHourlyActivityHeatmap = async (canvasRef, data, options = {}) => {
    const { animate = true, title = 'Hourly Activity Heatmap' } = options

    const canvas = resolveCanvas(canvasRef)
    if (!canvas) {
      return null
    }

    await nextTick()
    destroyChart(canvasRef)

    const ctx = canvas.getContext('2d')
    const species = data.map(d => getDisplaySpeciesName(d))
    const rowStats = calculateRowStats(data)
    const [r, g, b] = secondaryRGB

    return new Chart(ctx, {
      type: 'matrix',
      data: {
        datasets: [{
          label: 'Hourly Bird Detections',
          data: prepareDataForCategoryMatrix(data, rowStats),
          borderColor: 'white',
          borderWidth: 1,
          width: ({ chart }) => (chart.chartArea || {}).width / 24,
          height: ({ chart }) => (chart.chartArea || {}).height / species.length,
          backgroundColor: (context) => {
            const { v: value, rowStats: rs } = context.raw
            const { min, max } = rs
            const normalizedValue = (max > min) ? (value - min) / (max - min) : 0.5
            const alpha = Math.sqrt(normalizedValue)
            return `rgba(${r}, ${g}, ${b}, ${alpha})`
          }
        }]
      },
      options: {
        responsive: true,
        animation: animate,
        maintainAspectRatio: false,
        layout: {
          padding: { left: 0, right: 10, top: 10, bottom: 0 }
        },
        plugins: {
          legend: { display: false },
          title: title ? {
            display: true,
            text: title,
            font: { size: 14 },
            color: colorPalette.text
          } : { display: false },
          tooltip: {
            callbacks: {
              title: (context) => {
                const { x, y } = context[0].raw
                return `${y} at ${x}`
              },
              label: (context) => `Detections: ${context.raw.v}`
            },
            backgroundColor: colorPalette.primary,
            titleColor: colorPalette.background,
            bodyColor: colorPalette.background
          }
        },
        scales: {
          x: {
            type: 'category',
            labels: generateHourLabels(),
            ticks: {
              maxRotation: 0,
              autoSkip: false,
              font: { size: 9 },
              callback: function(value, index) {
                return formatHourLabel(this.getLabelForValue(index))
              }
            },
            grid: { display: false },
            title: { display: true, text: 'Hour of Day', color: colorPalette.text }
          },
          y: {
            type: 'category',
            labels: species,
            reverse: false,
            offset: true,
            ticks: { display: false },
            grid: { display: false },
            border: { display: false }
          }
        }
      },
      plugins: [createCustomGridPlugin(species), createMatrixLabelsPlugin()]
    })
  }

  /**
   * Create Hourly Activity bar chart.
   * Shows total detection counts per hour of day.
   *
   * @param {Ref|HTMLCanvasElement} canvasRef - Vue ref to canvas element or canvas directly
   * @param {Array<{hour: string, count: number}>} data - Hourly activity data
   * @param {Object} options - Chart options
   * @param {boolean} options.animate - Enable animation (default: true)
   * @returns {Promise<Chart|null>} Chart instance or null if canvas not available
   */
  const createHourlyActivityChart = async (canvasRef, data, options = {}) => {
    const { animate = true } = options

    const canvas = resolveCanvas(canvasRef)
    if (!canvas) {
      return null
    }

    await nextTick()

    // In-place update if a bar chart already exists on this canvas
    const existing = Chart.getChart(canvas)
    if (existing && existing.config.type === 'bar') {
      existing.data.labels = data.map(d => d.hour)
      existing.data.datasets[0].data = data.map(d => d.count)
      existing.options.animation = animate
      existing.update()
      return existing
    }

    destroyChart(canvasRef)
    const ctx = canvas.getContext('2d')

    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.hour),
        datasets: [{
          label: 'Detections',
          data: data.map(d => d.count),
          backgroundColor: colorPalette.accent1,
          borderColor: colorPalette.primary,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        animation: animate,
        maintainAspectRatio: false,
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
              display: false
            },
            ticks: {
              color: colorPalette.text,
              callback: function(value, index) {
                return formatHourLabel(this.getLabelForValue(index))
              }
            }
          }
        },
        plugins: {
          legend: { display: false }
        }
      }
    })
  }

  return {
    colorPalette,
    destroyChart,
    freezeChart,
    createTotalObservationsChart,
    createHourlyActivityHeatmap,
    createHourlyActivityChart,
    speciesAxisLayout
  }
}
