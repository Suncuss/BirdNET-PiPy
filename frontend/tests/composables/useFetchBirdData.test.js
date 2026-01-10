/**
 * Tests for useFetchBirdData composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useFetchBirdData } from '@/composables/useFetchBirdData'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    api: vi.fn()
  })
}))

describe('useFetchBirdData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('initialization', () => {
    it('returns all expected refs', () => {
      const result = useFetchBirdData()

      expect(result).toHaveProperty('hourlyBirdActivityData')
      expect(result).toHaveProperty('detailedBirdActivityData')
      expect(result).toHaveProperty('latestObservationData')
      expect(result).toHaveProperty('recentObservationsData')
      expect(result).toHaveProperty('summaryData')
      expect(result).toHaveProperty('hourlyBirdActivityError')
      expect(result).toHaveProperty('detailedBirdActivityError')
      expect(result).toHaveProperty('latestObservationError')
      expect(result).toHaveProperty('recentObservationsError')
      expect(result).toHaveProperty('summaryError')
      expect(result).toHaveProperty('latestObservationimageUrl')
    })

    it('returns fetch functions', () => {
      const result = useFetchBirdData()

      expect(result).toHaveProperty('fetchDashboardData')
      expect(result).toHaveProperty('fetchChartsData')
      expect(typeof result.fetchDashboardData).toBe('function')
      expect(typeof result.fetchChartsData).toBe('function')
    })

    it('initializes with empty/default values', () => {
      const result = useFetchBirdData()

      expect(result.hourlyBirdActivityData.value).toEqual([])
      expect(result.detailedBirdActivityData.value).toEqual([])
      expect(result.latestObservationData.value).toBeNull()
      expect(result.recentObservationsData.value).toEqual([])
      expect(result.summaryData.value).toEqual({})
      expect(result.latestObservationimageUrl.value).toBe('/default_bird.webp')
    })

    it('initializes errors as null', () => {
      const result = useFetchBirdData()

      expect(result.hourlyBirdActivityError.value).toBeNull()
      expect(result.detailedBirdActivityError.value).toBeNull()
      expect(result.latestObservationError.value).toBeNull()
      expect(result.recentObservationsError.value).toBeNull()
      expect(result.summaryError.value).toBeNull()
    })
  })

  describe('fetchChartsData', () => {
    it('fetches hourly and detailed activity data', async () => {
      const mockHourlyData = [{ hour: 0, count: 5 }, { hour: 1, count: 10 }]
      const mockDetailedData = [{ species: 'Robin', count: 3 }]

      mockApi.get.mockImplementation((url) => {
        if (url.includes('/activity/hourly')) {
          return Promise.resolve({ data: mockHourlyData })
        }
        if (url.includes('/activity/overview')) {
          return Promise.resolve({ data: mockDetailedData })
        }
        return Promise.reject(new Error('Unknown URL'))
      })

      const { fetchChartsData, hourlyBirdActivityData, detailedBirdActivityData } = useFetchBirdData()

      await fetchChartsData('2025-11-26')

      expect(hourlyBirdActivityData.value).toEqual(mockHourlyData)
      expect(detailedBirdActivityData.value).toEqual(mockDetailedData)
    })

    it('handles API errors gracefully for hourly data', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/activity/hourly')) {
          return Promise.reject(new Error('Network error'))
        }
        if (url.includes('/activity/overview')) {
          return Promise.resolve({ data: [] })
        }
        return Promise.reject(new Error('Unknown URL'))
      })

      const { fetchChartsData, hourlyBirdActivityData, hourlyBirdActivityError } = useFetchBirdData()

      await fetchChartsData('2025-11-26')

      expect(hourlyBirdActivityData.value).toEqual([])
      expect(hourlyBirdActivityError.value).toBe('Failed to fetch hourly activity data.')
    })

    it('handles API errors gracefully for detailed data', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/activity/hourly')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/activity/overview')) {
          return Promise.reject(new Error('Network error'))
        }
        return Promise.reject(new Error('Unknown URL'))
      })

      const { fetchChartsData, detailedBirdActivityData, detailedBirdActivityError } = useFetchBirdData()

      await fetchChartsData('2025-11-26')

      expect(detailedBirdActivityData.value).toEqual([])
      expect(detailedBirdActivityError.value).toBe('Failed to fetch detailed activity data.')
    })

    it('passes date parameter to API calls', async () => {
      mockApi.get.mockResolvedValue({ data: [] })

      const { fetchChartsData } = useFetchBirdData()

      await fetchChartsData('2025-12-01')

      expect(mockApi.get).toHaveBeenCalledWith(
        '/activity/hourly',
        { params: { date: '2025-12-01' } }
      )
      expect(mockApi.get).toHaveBeenCalledWith(
        '/activity/overview',
        { params: { date: '2025-12-01' } }
      )
    })
  })

  describe('fetchDashboardData', () => {
    it('fetches all dashboard data in parallel', async () => {
      const mockLatest = { common_name: 'American Robin', confidence: 0.95 }
      const mockRecent = [{ common_name: 'Blue Jay' }, { common_name: 'Cardinal' }]
      const mockSummary = { total_detections: 100, unique_species: 25 }

      mockApi.get.mockImplementation((url) => {
        if (url.includes('/observations/latest')) {
          return Promise.resolve({ data: mockLatest })
        }
        if (url.includes('/observations/recent')) {
          return Promise.resolve({ data: mockRecent })
        }
        if (url.includes('/observations/summary')) {
          return Promise.resolve({ data: mockSummary })
        }
        if (url.includes('/activity/')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/wikimedia_image')) {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const {
        fetchDashboardData,
        latestObservationData,
        recentObservationsData,
        summaryData
      } = useFetchBirdData()

      await fetchDashboardData()

      expect(latestObservationData.value).toEqual(mockLatest)
      expect(recentObservationsData.value).toEqual(mockRecent)
      expect(summaryData.value).toEqual(mockSummary)
    })

    it('fetches wikimedia image when latest observation exists', async () => {
      const mockLatest = { common_name: 'American Robin', confidence: 0.95 }

      mockApi.get.mockImplementation((url) => {
        if (url.includes('/observations/latest')) {
          return Promise.resolve({ data: mockLatest })
        }
        if (url.includes('/observations/recent')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/observations/summary')) {
          return Promise.resolve({ data: {} })
        }
        if (url.includes('/activity/')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/wikimedia_image')) {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      await fetchDashboardData()

      // Verify wikimedia was called with the species name
      expect(mockApi.get).toHaveBeenCalledWith(
        '/wikimedia_image',
        { params: { species: 'American Robin' } }
      )
      expect(latestObservationimageUrl.value).toBe('/robin.jpg')
    })

    it('keeps default image when no latest observation', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/observations/latest')) {
          return Promise.reject(new Error('Not found'))
        }
        if (url.includes('/observations/recent')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/observations/summary')) {
          return Promise.resolve({ data: {} })
        }
        if (url.includes('/activity/')) {
          return Promise.resolve({ data: [] })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      await fetchDashboardData()

      expect(latestObservationimageUrl.value).toBe('/default_bird.webp')
    })

    it('sets error messages on API failures', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/observations/latest')) {
          return Promise.reject(new Error('Server error'))
        }
        if (url.includes('/observations/recent')) {
          return Promise.reject(new Error('Server error'))
        }
        if (url.includes('/observations/summary')) {
          return Promise.reject(new Error('Server error'))
        }
        if (url.includes('/activity/')) {
          return Promise.resolve({ data: [] })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const {
        fetchDashboardData,
        latestObservationError,
        recentObservationsError,
        summaryError
      } = useFetchBirdData()

      await fetchDashboardData()

      expect(latestObservationError.value).toBe('Failed to fetch latest observation data.')
      expect(recentObservationsError.value).toBe('Failed to fetch recent observations data.')
      expect(summaryError.value).toBe('Failed to fetch summary data.')
    })
  })

  describe('reactive updates', () => {
    it('data refs are reactive and update on subsequent fetches', async () => {
      const initialData = [{ species: 'Robin', count: 1 }]
      const updatedData = [{ species: 'Robin', count: 5 }, { species: 'Jay', count: 3 }]

      let callCount = 0
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/activity/hourly')) {
          return Promise.resolve({ data: [] })
        }
        if (url.includes('/activity/overview')) {
          callCount++
          return Promise.resolve({ data: callCount === 1 ? initialData : updatedData })
        }
        return Promise.resolve({ data: [] })
      })

      const { fetchChartsData, detailedBirdActivityData } = useFetchBirdData()

      await fetchChartsData('2025-11-26')
      expect(detailedBirdActivityData.value).toEqual(initialData)

      await fetchChartsData('2025-11-27')
      expect(detailedBirdActivityData.value).toEqual(updatedData)
    })

    it('clears error on successful retry', async () => {
      let shouldFail = true
      mockApi.get.mockImplementation((url) => {
        if (url.includes('/activity/hourly')) {
          if (shouldFail) {
            return Promise.reject(new Error('Network error'))
          }
          return Promise.resolve({ data: [{ hour: 0, count: 10 }] })
        }
        return Promise.resolve({ data: [] })
      })

      const { fetchChartsData, hourlyBirdActivityError, hourlyBirdActivityData } = useFetchBirdData()

      // First call fails
      await fetchChartsData('2025-11-26')
      expect(hourlyBirdActivityError.value).toBe('Failed to fetch hourly activity data.')

      // Retry succeeds
      shouldFail = false
      await fetchChartsData('2025-11-26')
      expect(hourlyBirdActivityError.value).toBeNull()
      expect(hourlyBirdActivityData.value).toEqual([{ hour: 0, count: 10 }])
    })
  })
})
