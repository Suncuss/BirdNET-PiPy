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

    it('fetches all dashboard data and sets activity order from param', async () => {
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
        latestObservationData,
        recentObservationsData,
        summaryData,
        hourlyBirdActivityData,
        detailedBirdActivityData
      } = useFetchBirdData()

      await fetchDashboardData('most')

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

      await fetchDashboardData('most')

      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.most)

      setActivityOrder('least')
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.least)
    })

    it('passes order param to set detailedBirdActivityData directly', async () => {
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

      const { fetchDashboardData, detailedBirdActivityData } = useFetchBirdData()

      await fetchDashboardData('least')
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.least)

      await fetchDashboardData('most')
      expect(detailedBirdActivityData.value).toEqual(dashData.activityOverview.most)
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

  describe('fetch race guard', () => {
    const mockDashboardResponse = (overrides = {}) => ({
      latestObservation: null,
      recentObservations: [],
      summary: {},
      hourlyActivity: [],
      activityOverview: { most: [], least: [] },
      ...overrides
    })

    it('discards stale response when a newer fetch starts', async () => {
      let resolveStale
      const staleData = mockDashboardResponse({
        recentObservations: [{ common_name: 'Stale Robin' }]
      })
      const freshData = mockDashboardResponse({
        recentObservations: [{ common_name: 'Fresh Jay' }]
      })

      mockApi.get
        .mockImplementationOnce(() => new Promise(resolve => {
          resolveStale = () => resolve({ data: staleData })
        }))
        .mockResolvedValueOnce({ data: freshData })

      const { fetchDashboardData, recentObservationsData } = useFetchBirdData()

      // Start first fetch (will be deferred)
      const staleFetch = fetchDashboardData()

      // Start second fetch (resolves immediately)
      await fetchDashboardData()

      // Now resolve the stale one
      resolveStale()
      await staleFetch

      // Data should be from fresh fetch, not stale
      expect(recentObservationsData.value).toEqual([{ common_name: 'Fresh Jay' }])
    })

    it('discards stale error when a newer fetch succeeds', async () => {
      let rejectStale
      const freshData = mockDashboardResponse()

      mockApi.get
        .mockImplementationOnce(() => new Promise((_, reject) => {
          rejectStale = () => reject(new Error('Stale error'))
        }))
        .mockResolvedValueOnce({ data: freshData })

      const { fetchDashboardData, latestObservationError } = useFetchBirdData()

      const staleFetch = fetchDashboardData()
      await fetchDashboardData()

      rejectStale()
      await staleFetch

      // Error should be null (from fresh success), not from stale rejection
      expect(latestObservationError.value).toBeNull()
    })
  })

  describe('wikimedia retry on default image', () => {
    const mockDashboardResponse = (overrides = {}) => ({
      latestObservation: { common_name: 'American Robin', confidence: 0.95 },
      recentObservations: [],
      summary: {},
      hourlyActivity: [],
      activityOverview: { most: [], least: [] },
      ...overrides
    })

    it('retries wikimedia when image is still default from previous failure', async () => {
      let wikimediaCallCount = 0
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          wikimediaCallCount++
          if (wikimediaCallCount === 1) {
            return Promise.reject(new Error('Wikimedia error'))
          }
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      // First call — wikimedia fails, image stays at default
      await fetchDashboardData()
      // Let wikimedia fire-and-forget settle
      await vi.waitFor(() => {
        expect(wikimediaCallCount).toBe(1)
      })
      expect(latestObservationimageUrl.value).toBe('/default_bird.webp')

      // Second call — same species but image still default, should retry
      await fetchDashboardData()
      await vi.waitFor(() => {
        expect(latestObservationimageUrl.value).toBe('/robin.jpg')
      })
      expect(wikimediaCallCount).toBe(2)
    })

    it('does not reset image to default on retry (same species)', async () => {
      let wikimediaCallCount = 0
      mockApi.get.mockImplementation((url) => {
        if (url === '/dashboard') {
          return Promise.resolve({ data: mockDashboardResponse() })
        }
        if (url === '/wikimedia_image') {
          wikimediaCallCount++
          if (wikimediaCallCount === 1) {
            return Promise.reject(new Error('Wikimedia error'))
          }
          return Promise.resolve({ data: { imageUrl: '/robin.jpg' } })
        }
        return Promise.reject(new Error(`Unknown URL: ${url}`))
      })

      const { fetchDashboardData, latestObservationimageUrl } = useFetchBirdData()

      // First call — fails
      await fetchDashboardData()
      await vi.waitFor(() => { expect(wikimediaCallCount).toBe(1) })

      // Manually set to some URL to verify it doesn't get reset to default
      // (This simulates a partial load scenario — but we test the real behavior:
      // on retry with same species, image should NOT be reset to default before fetch)
      // The image is still at /default_bird.webp after the first failed call,
      // so the retry should happen and succeed without resetting
      await fetchDashboardData()
      await vi.waitFor(() => {
        expect(latestObservationimageUrl.value).toBe('/robin.jpg')
      })
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
