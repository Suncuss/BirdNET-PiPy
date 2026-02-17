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
      expect(result).toHaveProperty('setActivityOrder')
      expect(result).toHaveProperty('fetchChartsData')
      expect(typeof result.fetchDashboardData).toBe('function')
      expect(typeof result.setActivityOrder).toBe('function')
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
      expect(hourlyBirdActivityError.value).toBe('Hmm, cannot reach the server')
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
      expect(detailedBirdActivityError.value).toBe('Hmm, cannot reach the server')
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
        { params: { date: '2025-12-01', order: 'most' } }
      )
    })
  })

  describe('fetchDashboardData', () => {
    const mockDashboardResponse = (overrides = {}) => ({
      latestObservation: { common_name: 'American Robin', confidence: 0.95 },
      recentObservations: [{ common_name: 'Blue Jay' }, { common_name: 'Cardinal' }],
      summary: { today: {}, week: {}, month: {}, allTime: {} },
      hourlyActivity: [{ hour: '00:00', count: 0 }],
      activityOverview: {
        most: [{ species: 'Robin', count: 3 }],
        least: [{ species: 'Sparrow', count: 1 }]
      },
      ...overrides
    })

    it('fetches all dashboard data from consolidated endpoint', async () => {
      const dashData = mockDashboardResponse()

      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: dashData })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const {
        fetchDashboardData,
        setActivityOrder,
        latestObservationData,
        recentObservationsData,
        summaryData,
        hourlyBirdActivityData,
        detailedBirdActivityData
      } = useFetchBirdData()

      await fetchDashboardData()
      setActivityOrder('most')

      expect(latestObservationData.value).toEqual(dashData.latestObservation)
      expect(recentObservationsData.value).toEqual(dashData.recentObservations)
      expect(summaryData.value).toEqual(dashData.summary)
      expect(hourlyBirdActivityData.value).toEqual(dashData.hourlyActivity)
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.most)
    })

    it('switches activity order instantly via setActivityOrder', async () => {
      const dashData = mockDashboardResponse()

      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: dashData })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, setActivityOrder, detailedBirdActivityData } = useFetchBirdData()

      await fetchDashboardData()

      setActivityOrder('most')
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.most)

      setActivityOrder('least')
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.least)
    })

    it('fetches wikimedia image when latest observation exists', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      await fetchDashboardData()
      // Wikimedia is fire-and-forget — flush microtasks
      await vi.waitFor(() => {
        expect(latestObservationimageUrl.value).toBe('/robin.jpg')
      })

      expect(mockApi.get).toHaveBeenCalledWith(
        '/wikimedia_image',
        { params: { species: 'American Robin' } }
      )
    })

    it('uses custom image URL when hasCustomImage is true', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg', hasCustomImage: true } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      await fetchDashboardData()
      // Wikimedia is fire-and-forget — flush microtasks
      await vi.waitFor(() => {
        expect(latestObservationimageUrl.value).toContain('/bird/American%20Robin/image')
      })
    })

    it('keeps default image when no latest observation', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse({ latestObservation: null }) })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      await fetchDashboardData()

      expect(latestObservationimageUrl.value).toBe('/default_bird.webp')
      // Should not call wikimedia at all
      expect(mockApi.get).not.toHaveBeenCalledWith(
        '/wikimedia_image',
        expect.anything()
      )
    })

    it('skips wikimedia when species has not changed', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      // First call — species changes from null to Robin, triggers wikimedia
      await fetchDashboardData()
      await vi.waitFor(() => {
        expect(latestObservationimageUrl.value).toBe('/robin.jpg')
      })

      // Reset mock call history
      mockApi.get.mockClear()
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      // Second call — same species, should NOT call wikimedia
      await fetchDashboardData()

      expect(mockApi.get).toHaveBeenCalledTimes(1) // only /dashboard
      expect(mockApi.get).not.toHaveBeenCalledWith(
        '/wikimedia_image',
        expect.anything()
      )
      // Image URL preserved from first call
      expect(latestObservationimageUrl.value).toBe('/robin.jpg')
    })

    it('keeps default image when wikimedia call fails', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          return Promise.reject(new Error('Wikimedia error'))
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const {
        fetchDashboardData,
        latestObservationimageUrl,
        latestObservationError
      } = useFetchBirdData()

      await fetchDashboardData()

      // Image stays at default but dashboard data is still populated
      expect(latestObservationimageUrl.value).toBe('/default_bird.webp')
      expect(latestObservationError.value).toBeNull()
    })

    it('sets all error messages on dashboard API failure', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.reject(new Error('Server error'))
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const {
        fetchDashboardData,
        latestObservationError,
        recentObservationsError,
        summaryError,
        hourlyBirdActivityError,
        detailedBirdActivityError
      } = useFetchBirdData()

      await fetchDashboardData()

      expect(latestObservationError.value).toBe('Hmm, cannot reach the server')
      expect(recentObservationsError.value).toBe('Hmm, cannot reach the server')
      expect(summaryError.value).toBe('Hmm, cannot reach the server')
      expect(hourlyBirdActivityError.value).toBe('Hmm, cannot reach the server')
      expect(detailedBirdActivityError.value).toBe('Hmm, cannot reach the server')
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
      expect(hourlyBirdActivityError.value).toBe('Hmm, cannot reach the server')

      // Retry succeeds
      shouldFail = false
      await fetchChartsData('2025-11-26')
      expect(hourlyBirdActivityError.value).toBeNull()
      expect(hourlyBirdActivityData.value).toEqual([{ hour: 0, count: 10 }])
    })
  })
})
