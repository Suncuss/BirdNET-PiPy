/**
 * Tests for useChartHelpers composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useChartHelpers } from '@/composables/useChartHelpers'

// Mock Chart.js
vi.mock('chart.js/auto', () => {
  const mockDestroy = vi.fn()
  const mockGetChart = vi.fn()

  return {
    default: {
      getChart: mockGetChart
    },
    __mockDestroy: mockDestroy,
    __mockGetChart: mockGetChart
  }
})

describe('useChartHelpers', () => {
  let helpers
  let mockGetChart
  let mockDestroy

  beforeEach(async () => {
    // Get mock functions
    const chartModule = await import('chart.js/auto')
    mockGetChart = chartModule.__mockGetChart
    mockDestroy = vi.fn()

    // Reset mocks
    vi.clearAllMocks()

    helpers = useChartHelpers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('destroyChart', () => {
    it('does nothing when canvasRef is null', () => {
      helpers.destroyChart(null)
      expect(mockGetChart).not.toHaveBeenCalled()
    })

    it('does nothing when canvasRef.value is null', () => {
      const canvasRef = ref(null)
      helpers.destroyChart(canvasRef)
      expect(mockGetChart).not.toHaveBeenCalled()
    })

    it('calls Chart.getChart with canvas element from ref', () => {
      const canvas = document.createElement('canvas')
      const canvasRef = ref(canvas)

      mockGetChart.mockReturnValue(null)
      helpers.destroyChart(canvasRef)

      expect(mockGetChart).toHaveBeenCalledWith(canvas)
    })

    it('calls destroy on existing chart', () => {
      const canvas = document.createElement('canvas')
      const canvasRef = ref(canvas)
      const mockChart = { destroy: mockDestroy }

      mockGetChart.mockReturnValue(mockChart)
      helpers.destroyChart(canvasRef)

      expect(mockDestroy).toHaveBeenCalled()
    })

    it('does not call destroy when no chart exists', () => {
      const canvas = document.createElement('canvas')
      const canvasRef = ref(canvas)

      mockGetChart.mockReturnValue(null)
      helpers.destroyChart(canvasRef)

      expect(mockDestroy).not.toHaveBeenCalled()
    })

    it('accepts raw canvas element (not ref)', () => {
      const canvas = document.createElement('canvas')

      mockGetChart.mockReturnValue(null)
      helpers.destroyChart(canvas)

      expect(mockGetChart).toHaveBeenCalledWith(canvas)
    })
  })

  describe('generateHourLabels', () => {
    it('returns array of 24 hour labels', () => {
      const labels = helpers.generateHourLabels()
      expect(labels).toHaveLength(24)
    })

    it('first label is 00:00', () => {
      const labels = helpers.generateHourLabels()
      expect(labels[0]).toBe('00:00')
    })

    it('last label is 23:00', () => {
      const labels = helpers.generateHourLabels()
      expect(labels[23]).toBe('23:00')
    })

    it('all labels are in HH:00 format', () => {
      const labels = helpers.generateHourLabels()
      labels.forEach(label => {
        expect(label).toMatch(/^\d{2}:00$/)
      })
    })

    it('labels are sequential', () => {
      const labels = helpers.generateHourLabels()
      for (let i = 0; i < 24; i++) {
        const expected = i.toString().padStart(2, '0') + ':00'
        expect(labels[i]).toBe(expected)
      }
    })
  })

  describe('calculateRowStats', () => {
    it('calculates min and max for each row', () => {
      const data = [
        { hourlyActivity: [1, 5, 3, 2] },
        { hourlyActivity: [10, 20, 15, 5] }
      ]

      const stats = helpers.calculateRowStats(data)

      expect(stats).toHaveLength(2)
      expect(stats[0]).toEqual({ min: 1, max: 5 })
      expect(stats[1]).toEqual({ min: 5, max: 20 })
    })

    it('handles single value arrays', () => {
      const data = [{ hourlyActivity: [42] }]
      const stats = helpers.calculateRowStats(data)

      expect(stats[0]).toEqual({ min: 42, max: 42 })
    })

    it('handles all zeros', () => {
      const data = [{ hourlyActivity: [0, 0, 0, 0] }]
      const stats = helpers.calculateRowStats(data)

      expect(stats[0]).toEqual({ min: 0, max: 0 })
    })

    it('returns empty array for empty input', () => {
      const stats = helpers.calculateRowStats([])
      expect(stats).toEqual([])
    })
  })

  describe('prepareDataForCategoryMatrix', () => {
    it('transforms data into matrix format', () => {
      const data = [
        { species: 'Robin', hourlyActivity: [1, 2] }
      ]
      const rowStats = [{ min: 1, max: 2 }]

      const result = helpers.prepareDataForCategoryMatrix(data, rowStats)

      expect(result).toHaveLength(2)
      expect(result[0]).toEqual({
        x: '00:00',
        y: 'Robin',
        v: 1,
        rowStats: { min: 1, max: 2 }
      })
      expect(result[1]).toEqual({
        x: '01:00',
        y: 'Robin',
        v: 2,
        rowStats: { min: 1, max: 2 }
      })
    })

    it('handles multiple species', () => {
      const data = [
        { species: 'Robin', hourlyActivity: [1] },
        { species: 'Sparrow', hourlyActivity: [5] }
      ]
      const rowStats = [
        { min: 1, max: 1 },
        { min: 5, max: 5 }
      ]

      const result = helpers.prepareDataForCategoryMatrix(data, rowStats)

      expect(result).toHaveLength(2)
      expect(result[0].y).toBe('Robin')
      expect(result[1].y).toBe('Sparrow')
    })

    it('creates 24 * species count data points for full day', () => {
      const data = [
        { species: 'Robin', hourlyActivity: Array(24).fill(0) },
        { species: 'Sparrow', hourlyActivity: Array(24).fill(0) }
      ]
      const rowStats = [{ min: 0, max: 0 }, { min: 0, max: 0 }]

      const result = helpers.prepareDataForCategoryMatrix(data, rowStats)

      expect(result).toHaveLength(48) // 24 hours * 2 species
    })
  })

  describe('getLocalDateString', () => {
    it('returns date in YYYY-MM-DD format', () => {
      const date = new Date(2024, 5, 15) // June 15, 2024
      const result = helpers.getLocalDateString(date)

      expect(result).toBe('2024-06-15')
    })

    it('pads single digit months', () => {
      const date = new Date(2024, 0, 1) // January 1, 2024
      const result = helpers.getLocalDateString(date)

      expect(result).toBe('2024-01-01')
    })

    it('pads single digit days', () => {
      const date = new Date(2024, 11, 5) // December 5, 2024
      const result = helpers.getLocalDateString(date)

      expect(result).toBe('2024-12-05')
    })

    it('defaults to current date when no argument provided', () => {
      const result = helpers.getLocalDateString()
      const now = new Date()

      const expected = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0')
      ].join('-')

      expect(result).toBe(expected)
    })
  })
})
