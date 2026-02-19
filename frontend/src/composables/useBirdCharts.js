import { nextTick } from 'vue'
import Chart from 'chart.js/auto'
import { useChartColors } from './useChartColors'
import { useChartHelpers } from './useChartHelpers'

/**
 * Composable for creating bird activity charts.
 * Provides factory functions for Total Observations bar chart and Hourly Activity heatmap.
 */
export function useBirdCharts() {
  const { colorPalette, secondaryRGB } = useChartColors()
  const { destroyChart, freezeChart, generateHourLabels, calculateRowStats, prepareDataForCategoryMatrix } = useChartHelpers()

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
   */
  const createTotalObservationsChart = async (canvasRef, data, options = {}) => {
    const { animate = true, title = 'Total Detections by Species' } = options

    // Handle both Vue refs and raw canvas elements
    const isRef = canvasRef && typeof canvasRef === 'object' && 'value' in canvasRef
    const canvas = isRef ? canvasRef.value : canvasRef

    if (!canvas) {
      return null
    }

    await nextTick()
    destroyChart(canvasRef)

    const ctx = canvas.getContext('2d')

    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.species),
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
            ticks: { color: colorPalette.text }
          }
        },
        layout: {
          padding: { left: 10, right: 10, top: 0, bottom: 0 }
        }
      }
    })
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

    // Handle both Vue refs and raw canvas elements
    const isRef = canvasRef && typeof canvasRef === 'object' && 'value' in canvasRef
    const canvas = isRef ? canvasRef.value : canvasRef

    if (!canvas) {
      return null
    }

    await nextTick()
    destroyChart(canvasRef)

    const ctx = canvas.getContext('2d')
    const species = data.map(d => d.species)
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
            ticks: { maxRotation: 0, autoSkip: false, font: { size: 9 } },
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

    // Handle both Vue refs and raw canvas elements
    const isRef = canvasRef && typeof canvasRef === 'object' && 'value' in canvasRef
    const canvas = isRef ? canvasRef.value : canvasRef

    if (!canvas) {
      return null
    }

    await nextTick()
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
                const hour = parseInt(this.getLabelForValue(index).split(':')[0])
                if (hour === 0) return '12AM'
                if (hour === 12) return '12PM'
                return hour > 12 ? `${hour - 12}PM` : `${hour}AM`
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
    createHourlyActivityChart
  }
}
