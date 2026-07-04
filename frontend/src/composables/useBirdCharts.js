import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import Chart from 'chart.js/auto'
import { useChartColors } from './useChartColors'
import { useChartHelpers } from './useChartHelpers'
import { useTimeFormat } from './useTimeFormat'
import { getDisplaySpeciesName } from '@/utils/birdNames'
import { tableDetectionsLink } from '@/utils/detectionLinks'

// Assign `next` to `layoutRef` only if it differs from the current value.
// Each layout is flat scalars plus a `ticks` array of flat objects; equality
// is a shallow compare of both. Skipping equal writes avoids a Vue re-render
// of the axis overlay on every polling refresh that produced the same geometry.
const commitAxisLayout = (layoutRef, next) => {
  const prev = layoutRef.value
  const sameScalars = Object.keys(next).every(k => k === 'ticks' || prev[k] === next[k])
  const sameTicks = prev.ticks.length === next.ticks.length
    && next.ticks.every((t, i) => {
      const p = prev.ticks[i]
      return p && Object.keys(t).every(k => p[k] === t[k])
    })
  if (sameScalars && sameTicks) return
  layoutRef.value = next
}

/**
 * Composable for creating bird activity charts.
 * Provides factory functions for Total Observations bar chart and Hourly Activity heatmap.
 */
export function useBirdCharts() {
  const { colorPalette, secondaryRGB } = useChartColors()
  const { resolveCanvas, destroyChart, freezeChart, generateHourLabels, calculateRowStats, prepareDataForCategoryMatrix } = useChartHelpers()
  const { formatHourLabel } = useTimeFormat()
  const router = useRouter()

  // Reactive layout state for the species-axis HTML overlay (SpeciesAxisLinks).
  // Populated by createTotalObservationsChart via a Chart.js afterLayout plugin.
  const speciesAxisLayout = ref({ ticks: [], axisLeft: 0, axisWidth: 0, rowHeight: 0 })

  // Reactive layout state for the time-axis HTML overlay (TimeAxisLinks).
  // Populated by createHourlyActivityHeatmap via a Chart.js afterLayout plugin.
  const timeAxisLayout = ref({ ticks: [], axisLeft: 0, axisTop: 0, axisHeight: 0, colWidth: 0, date: null })

  // Shared x-axis tick font size for BOTH the Total Observations bar chart
  // (visible numeric labels) and the heatmap (transparent ticks; hour
  // labels are drawn by the TimeAxisLinks overlay). Applied to both so the
  // bands stay equal and the two plots stay row/bottom-aligned. Matches
  // TimeAxisLinks' HOUR_LABEL_FONT_MAX_PX (11) so the bar numbers and hour
  // labels read at the same size once the layout is wide enough for the
  // overlay font to scale up to its ceiling. The label-row offset is font-independent
  // (LABEL_TOP_OFFSET_PX = tickLength + ticks.padding), so changing this
  // does not disturb the vertical alignment.
  const X_AXIS_TICK_FONT_SIZE = 11

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

        commitAxisLayout(speciesAxisLayout, { ticks, axisLeft, axisWidth, rowHeight })
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
            // Shared font size keeps this band the same height as the heatmap
            // x-axis so the two plots stay row-aligned.
            ticks: { color: colorPalette.text, precision: 0, font: { size: X_AXIS_TICK_FONT_SIZE } },
            // Render the tick-mark stubs transparent rather than disabling
            // them: invisible, but they still reserve their layout space so
            // the band height (and the alignment with the heatmap) is
            // unchanged. Gridlines and numeric labels stay visible.
            grid: { tickColor: 'transparent' }
          },
          y: {
            // Transparent ticks reserve layout space; HTML overlay renders the real labels as links.
            // autoSkip:false guarantees one tick (and therefore one gridline)
            // per species, so every bar stays bounded by gridlines even when
            // the plot is short (e.g. mobile). Without this, Chart.js drops
            // half the category ticks and gridlines cross the bars.
            ticks: { color: 'transparent', autoSkip: false }
          }
        },
        layout: {
          // top matches the heatmap's layout.padding.top so both plots
          // start at the same y and the species rows line up.
          padding: { left: 10, right: 10, top: 10, bottom: 0 }
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
   * @param {string} options.date - Date (YYYY-MM-DD) the heatmap represents; emitted
   *   into timeAxisLayout so the TimeAxisLinks overlay can deep-link the Table view
   *   to that date + clicked hour, and also used as the date filter when a cell
   *   is clicked to drill into the Table view.
   * @returns {Promise<Chart|null>} Chart instance or null if canvas not available
   *
   * Side effect: emits x-axis tick positions into `timeAxisLayout` (returned from
   * useBirdCharts) so an HTML overlay can render the hour labels as real router-links.
   * The canvas x-axis tick text is rendered transparent — it still reserves layout
   * height but is not visible.
   */
  const createHourlyActivityHeatmap = async (canvasRef, data, options = {}) => {
    const { animate = true, title = 'Hourly Activity Heatmap', date = null } = options

    // Resolve the data point under a pointer event, or null if the pointer
    // isn't over a cell. Shared by onClick (navigate) and onHover (cursor).
    const cellAtEvent = (event, chart) => {
      const items = chart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, false)
      if (!items.length) return null
      return chart.data.datasets[0].data[items[0].index] || null
    }

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
    const hourLabels = generateHourLabels()

    const timeLayoutPlugin = {
      id: 'timeLayoutEmitter',
      afterLayout: (chart) => {
        const area = chart.chartArea
        const xScale = chart.scales?.x
        if (!area || !xScale) return
        // Derive geometry from chartArea — each matrix cell is
        // chartArea.width / 24 wide, tiled from chartArea.left, so the cell
        // centre for hour i is left + (i + 0.5) * colWidth. (This equals the
        // x-scale's getPixelForValue(i); chartArea is just the clearer source.)
        const n = hourLabels.length
        const colWidth = area.width / n
        const ticks = hourLabels.map((label, i) => ({
          x: area.left + (i + 0.5) * colWidth,
          label,
          hour: i
        }))
        const axisLeft = area.left
        const axisTop = area.bottom
        const axisHeight = xScale.height

        commitAxisLayout(timeAxisLayout, { ticks, axisLeft, axisTop, axisHeight, colWidth, date })
      }
    }

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
        // Cell drill-down: a click on a non-empty cell deep-links the Table
        // view to that species + hour (+ date). Empty cells (v <= 0) are
        // inert so clicking the heatmap's whitespace does nothing.
        onClick: (event, _elements, chart) => {
          const point = cellAtEvent(event, chart)
          if (!point || point.v <= 0) return
          router.push(tableDetectionsLink({ hour: point.hour, date, species: point.commonName }))
        },
        // A pointer cursor marks clickable (non-empty) cells. onHover fires
        // on every pointer move, so skip the CSSOM write unless the cursor
        // actually changes — same no-op-write discipline as commitAxisLayout.
        onHover: (event, _elements, chart) => {
          const target = event?.native?.target
          if (!target) return
          const point = cellAtEvent(event, chart)
          const cursor = point && point.v > 0 ? 'pointer' : 'default'
          if (target.style.cursor !== cursor) target.style.cursor = cursor
        },
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
                return `${y} at ${formatHourLabel(x)}`
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
            labels: hourLabels,
            ticks: {
              // Transparent: the visible hour labels are drawn by the
              // TimeAxisLinks overlay. Shared font size keeps this band the
              // same height as the bar chart x-axis (so the plots stay
              // row-aligned) and sizes the room available to the overlay.
              color: 'transparent',
              maxRotation: 0,
              autoSkip: false,
              font: { size: X_AXIS_TICK_FONT_SIZE },
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
      plugins: [createCustomGridPlugin(species), createMatrixLabelsPlugin(), timeLayoutPlugin]
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
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (context) => formatHourLabel(context[0].label)
            }
          }
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
    speciesAxisLayout,
    timeAxisLayout
  }
}
