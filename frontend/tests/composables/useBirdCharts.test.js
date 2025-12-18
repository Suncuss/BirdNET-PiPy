/**
 * Tests for useBirdCharts composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { useBirdCharts } from '@/composables/useBirdCharts'

// Mock Chart.js
const mockDestroy = vi.fn()
const mockUpdate = vi.fn()
let mockChartInstance = null

vi.mock('chart.js/auto', () => {
  const ChartMock = vi.fn().mockImplementation(() => {
    mockChartInstance = {
      destroy: mockDestroy,
      update: mockUpdate,
      data: { datasets: [] },
      options: {}
    }
    return mockChartInstance
  })
  ChartMock.getChart = vi.fn().mockReturnValue(null)
  ChartMock.register = vi.fn()
  return { default: ChartMock }
})

describe('useBirdCharts', () => {
  let charts
  let mockCanvas
  let mockContext
  let Chart

  beforeEach(async () => {
    vi.clearAllMocks()

    // Get Chart mock
    const chartModule = await import('chart.js/auto')
    Chart = chartModule.default

    // Create mock canvas with proper getContext
    mockContext = {
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      fillText: vi.fn(),
      getImageData: vi.fn(),
      putImageData: vi.fn()
    }

    mockCanvas = document.createElement('canvas')
    mockCanvas.getContext = vi.fn().mockReturnValue(mockContext)

    charts = useBirdCharts()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    mockChartInstance = null
  })

  describe('initialization', () => {
    it('returns expected properties and methods', () => {
      expect(charts).toHaveProperty('colorPalette')
      expect(charts).toHaveProperty('destroyChart')
      expect(charts).toHaveProperty('createTotalObservationsChart')
      expect(charts).toHaveProperty('createHourlyActivityHeatmap')
      expect(charts).toHaveProperty('createHourlyActivityChart')
    })

    it('colorPalette has expected colors', () => {
      expect(charts.colorPalette.primary).toBe('#2D6A4F')
      expect(charts.colorPalette.secondary).toBe('#74C69D')
    })
  })

  describe('createTotalObservationsChart', () => {
    const mockData = [
      { species: 'Robin', hourlyActivity: [1, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
      { species: 'Sparrow', hourlyActivity: [0, 0, 0, 5, 5, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] }
    ]

    it('returns null when canvas is not available', async () => {
      const result = await charts.createTotalObservationsChart(null, mockData)
      expect(result).toBeNull()
    })

    it('returns null when canvasRef.value is null', async () => {
      const canvasRef = ref(null)
      const result = await charts.createTotalObservationsChart(canvasRef, mockData)
      expect(result).toBeNull()
    })

    it('creates chart with correct type', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createTotalObservationsChart(canvasRef, mockData)

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          type: 'bar'
        })
      )
    })

    it('uses horizontal bar orientation (indexAxis: y)', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createTotalObservationsChart(canvasRef, mockData)

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          options: expect.objectContaining({
            indexAxis: 'y'
          })
        })
      )
    })

    it('calculates total detections correctly', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createTotalObservationsChart(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.data.datasets[0].data).toEqual([6, 15]) // Robin: 1+2+3=6, Sparrow: 5+5+5=15
    })

    it('accepts animate option', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createTotalObservationsChart(canvasRef, mockData, { animate: false })

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          options: expect.objectContaining({
            animation: false
          })
        })
      )
    })

    it('accepts custom title option', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createTotalObservationsChart(canvasRef, mockData, { title: 'Custom Title' })

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.options.plugins.title.text).toBe('Custom Title')
    })

    it('accepts raw canvas element (not ref)', async () => {
      await charts.createTotalObservationsChart(mockCanvas, mockData)
      expect(Chart).toHaveBeenCalled()
    })
  })

  describe('createHourlyActivityHeatmap', () => {
    const mockData = [
      { species: 'Robin', hourlyActivity: Array(24).fill(0).map((_, i) => i % 5) },
      { species: 'Sparrow', hourlyActivity: Array(24).fill(0).map((_, i) => i % 3) }
    ]

    it('returns null when canvas is not available', async () => {
      const result = await charts.createHourlyActivityHeatmap(null, mockData)
      expect(result).toBeNull()
    })

    it('creates chart with matrix type', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityHeatmap(canvasRef, mockData)

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          type: 'matrix'
        })
      )
    })

    it('includes custom plugins', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityHeatmap(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.plugins).toHaveLength(2)
      expect(chartCall.plugins[0].id).toBe('customGrid')
      expect(chartCall.plugins[1].id).toBe('matrixLabels')
    })

    it('creates 24 x species count data points', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityHeatmap(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.data.datasets[0].data).toHaveLength(48) // 24 hours * 2 species
    })

    it('data points have correct structure', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityHeatmap(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      const firstDataPoint = chartCall.data.datasets[0].data[0]

      expect(firstDataPoint).toHaveProperty('x')
      expect(firstDataPoint).toHaveProperty('y')
      expect(firstDataPoint).toHaveProperty('v')
      expect(firstDataPoint).toHaveProperty('rowStats')
    })

    it('accepts animate option', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityHeatmap(canvasRef, mockData, { animate: false })

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          options: expect.objectContaining({
            animation: false
          })
        })
      )
    })
  })

  describe('createHourlyActivityChart', () => {
    const mockData = [
      { hour: '00:00', count: 5 },
      { hour: '01:00', count: 3 },
      { hour: '02:00', count: 8 }
    ]

    it('returns null when canvas is not available', async () => {
      const result = await charts.createHourlyActivityChart(null, mockData)
      expect(result).toBeNull()
    })

    it('creates bar chart', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityChart(canvasRef, mockData)

      expect(Chart).toHaveBeenCalledWith(
        mockContext,
        expect.objectContaining({
          type: 'bar'
        })
      )
    })

    it('uses correct data labels', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityChart(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.data.labels).toEqual(['00:00', '01:00', '02:00'])
    })

    it('uses correct data values', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityChart(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.data.datasets[0].data).toEqual([5, 3, 8])
    })

    it('begins y-axis at zero', async () => {
      const canvasRef = ref(mockCanvas)
      await charts.createHourlyActivityChart(canvasRef, mockData)

      const chartCall = Chart.mock.calls[0][1]
      expect(chartCall.options.scales.y.beginAtZero).toBe(true)
    })
  })

  describe('destroyChart', () => {
    it('is exposed from composable', () => {
      expect(typeof charts.destroyChart).toBe('function')
    })

    it('handles null canvas gracefully', () => {
      expect(() => charts.destroyChart(null)).not.toThrow()
    })
  })
})
