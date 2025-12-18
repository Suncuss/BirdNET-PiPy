/**
 * Tests for useTableData composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useTableData } from '@/composables/useTableData'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  delete: vi.fn()
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

describe('useTableData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

	  describe('initialization', () => {
	    it('returns all expected state refs', () => {
	      const result = useTableData()

      expect(result).toHaveProperty('detections')
      expect(result).toHaveProperty('currentPage')
      expect(result).toHaveProperty('perPage')
      expect(result).toHaveProperty('totalItems')
	      expect(result).toHaveProperty('totalPages')
	      expect(result).toHaveProperty('isLoading')
	      expect(result).toHaveProperty('error')
	      expect(result).toHaveProperty('actionError')
	    })

    it('returns filter state refs', () => {
      const result = useTableData()

      expect(result).toHaveProperty('startDate')
      expect(result).toHaveProperty('endDate')
      expect(result).toHaveProperty('selectedSpecies')
      expect(result).toHaveProperty('hasActiveFilters')
    })

    it('returns sorting state refs', () => {
      const result = useTableData()

      expect(result).toHaveProperty('sortField')
      expect(result).toHaveProperty('sortOrder')
    })

    it('returns pagination computed refs', () => {
      const result = useTableData()

      expect(result).toHaveProperty('hasNextPage')
      expect(result).toHaveProperty('hasPrevPage')
    })

	    it('returns all methods', () => {
	      const result = useTableData()

      expect(typeof result.fetchDetections).toBe('function')
      expect(typeof result.deleteDetection).toBe('function')
      expect(typeof result.goToPage).toBe('function')
      expect(typeof result.nextPage).toBe('function')
      expect(typeof result.prevPage).toBe('function')
      expect(typeof result.setFilters).toBe('function')
      expect(typeof result.clearFilters).toBe('function')
	      expect(typeof result.toggleSort).toBe('function')
	      expect(typeof result.setPerPage).toBe('function')
	      expect(typeof result.clearError).toBe('function')
	      expect(typeof result.clearActionError).toBe('function')
	    })

	    it('initializes with default values', () => {
	      const result = useTableData()

      expect(result.detections.value).toEqual([])
      expect(result.currentPage.value).toBe(1)
      expect(result.perPage.value).toBe(25)
	      expect(result.totalItems.value).toBe(0)
	      expect(result.isLoading.value).toBe(false)
	      expect(result.error.value).toBeNull()
	      expect(result.actionError.value).toBeNull()
	      expect(result.startDate.value).toBeNull()
	      expect(result.endDate.value).toBeNull()
	      expect(result.selectedSpecies.value).toBeNull()
	      expect(result.sortField.value).toBe('timestamp')
	      expect(result.sortOrder.value).toBe('desc')
	    })

    it('computes totalPages correctly', () => {
      const result = useTableData()

      // No items
      expect(result.totalPages.value).toBe(0)

      // Set total items
      result.totalItems.value = 100
      result.perPage.value = 25
      expect(result.totalPages.value).toBe(4)

      result.totalItems.value = 101
      expect(result.totalPages.value).toBe(5)
    })

    it('computes hasActiveFilters correctly', () => {
      const result = useTableData()

      expect(result.hasActiveFilters.value).toBe(false)

      result.startDate.value = '2024-01-01'
      expect(result.hasActiveFilters.value).toBe(true)

      result.startDate.value = null
      result.selectedSpecies.value = 'Robin'
      expect(result.hasActiveFilters.value).toBe(true)
    })
  })

	  describe('fetchDetections', () => {
    it('fetches detections with default params', async () => {
      const mockResponse = {
        data: {
          detections: [
            { id: 1, common_name: 'Robin', confidence: 0.9 }
          ],
          pagination: {
            total_items: 1,
            page: 1,
            per_page: 25
          }
        }
      }

      mockApi.get.mockResolvedValueOnce(mockResponse)

      const { fetchDetections, detections, totalItems, isLoading } = useTableData()

      await fetchDetections()

      expect(mockApi.get).toHaveBeenCalledWith('/detections', {
        params: {
          page: 1,
          per_page: 25,
          sort: 'timestamp',
          order: 'desc'
        }
      })

      expect(detections.value).toEqual(mockResponse.data.detections)
      expect(totalItems.value).toBe(1)
      expect(isLoading.value).toBe(false)
    })

    it('includes filters in request params', async () => {
      mockApi.get.mockResolvedValueOnce({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { fetchDetections, startDate, endDate, selectedSpecies } = useTableData()

      startDate.value = '2024-01-01'
      endDate.value = '2024-01-31'
      selectedSpecies.value = 'Blue Jay'

      await fetchDetections()

      expect(mockApi.get).toHaveBeenCalledWith('/detections', {
        params: {
          page: 1,
          per_page: 25,
          sort: 'timestamp',
          order: 'desc',
          start_date: '2024-01-01',
          end_date: '2024-01-31',
          species: 'Blue Jay'
        }
      })
    })

    it('handles API errors', async () => {
      mockApi.get.mockRejectedValueOnce(new Error('Network error'))

      const { fetchDetections, error, detections, totalItems } = useTableData()

      await fetchDetections()

      expect(error.value).toBe('Failed to load detections. Please try again.')
      expect(detections.value).toEqual([])
      expect(totalItems.value).toBe(0)
    })

	    it('sets isLoading during fetch', async () => {
      let resolvePromise
      const pendingPromise = new Promise(resolve => {
        resolvePromise = resolve
      })

      mockApi.get.mockReturnValueOnce(pendingPromise)

      const { fetchDetections, isLoading } = useTableData()

      const fetchPromise = fetchDetections()
      expect(isLoading.value).toBe(true)

      resolvePromise({ data: { detections: [], pagination: { total_items: 0 } } })
      await fetchPromise

	      expect(isLoading.value).toBe(false)
	    })

	    it('clamps currentPage when server total_pages is lower', async () => {
	      mockApi.get
	        .mockResolvedValueOnce({
	          data: {
	            detections: [],
	            pagination: { total_items: 100, total_pages: 4 }
	          }
	        })
	        .mockResolvedValueOnce({
	          data: {
	            detections: [{ id: 99, common_name: 'Robin', confidence: 0.9 }],
	            pagination: { total_items: 100, total_pages: 4 }
	          }
	        })

	      const { fetchDetections, detections, currentPage } = useTableData()
	      currentPage.value = 5

	      await fetchDetections()

	      expect(currentPage.value).toBe(4)
	      expect(mockApi.get).toHaveBeenCalledTimes(2)
	      expect(mockApi.get).toHaveBeenNthCalledWith(1, '/detections', {
	        params: {
	          page: 5,
	          per_page: 25,
	          sort: 'timestamp',
	          order: 'desc'
	        }
	      })
	      expect(mockApi.get).toHaveBeenNthCalledWith(2, '/detections', {
	        params: {
	          page: 4,
	          per_page: 25,
	          sort: 'timestamp',
	          order: 'desc'
	        }
	      })
	      expect(detections.value).toEqual([{ id: 99, common_name: 'Robin', confidence: 0.9 }])
	    })
	  })

	  describe('deleteDetection', () => {
    it('deletes detection and refreshes data', async () => {
      mockApi.delete.mockResolvedValueOnce({
        data: { status: 'deleted', id: 1, species: 'Robin' }
      })

      mockApi.get.mockResolvedValueOnce({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { deleteDetection } = useTableData()

      const result = await deleteDetection(1)

      expect(result).toBe(true)
      expect(mockApi.delete).toHaveBeenCalledWith('/detections/1')
      expect(mockApi.get).toHaveBeenCalled() // Should refresh after delete
    })

	    it('handles 401 error', async () => {
	      mockApi.delete.mockRejectedValueOnce({
	        response: { status: 401 }
	      })

	      const { deleteDetection, error, actionError } = useTableData()

	      const result = await deleteDetection(1)

	      expect(result).toBe(false)
	      expect(error.value).toBeNull()
	      expect(actionError.value).toBe('Authentication required to delete detections.')
	    })

	    it('handles 404 error', async () => {
	      mockApi.delete.mockRejectedValueOnce({
	        response: { status: 404 }
	      })

	      const { deleteDetection, error, actionError } = useTableData()

	      const result = await deleteDetection(1)

	      expect(result).toBe(false)
	      expect(error.value).toBeNull()
	      expect(actionError.value).toBe('Detection not found.')
	    })

	    it('handles generic errors', async () => {
	      mockApi.delete.mockRejectedValueOnce(new Error('Network error'))

	      const { deleteDetection, error, actionError } = useTableData()

	      const result = await deleteDetection(1)

	      expect(result).toBe(false)
	      expect(error.value).toBeNull()
	      expect(actionError.value).toBe('Failed to delete detection. Please try again.')
	    })
	  })

  describe('pagination methods', () => {
    it('goToPage navigates to valid page', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 100 } }
      })

      const { goToPage, currentPage, totalItems, perPage } = useTableData()
      totalItems.value = 100
      perPage.value = 25

      await goToPage(3)

      expect(currentPage.value).toBe(3)
      expect(mockApi.get).toHaveBeenCalled()
    })

    it('goToPage does not navigate to invalid page', async () => {
      const { goToPage, currentPage, totalItems, perPage } = useTableData()
      totalItems.value = 100
      perPage.value = 25

      await goToPage(10) // Only 4 pages exist

      expect(currentPage.value).toBe(1) // Should stay at 1
      expect(mockApi.get).not.toHaveBeenCalled()
    })

    it('nextPage increments page', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 100 } }
      })

      const { nextPage, currentPage, totalItems, perPage } = useTableData()
      totalItems.value = 100
      perPage.value = 25

      await nextPage()

      expect(currentPage.value).toBe(2)
    })

    it('prevPage decrements page', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 100 } }
      })

      const { prevPage, currentPage, totalItems, perPage, goToPage } = useTableData()
      totalItems.value = 100
      perPage.value = 25
      currentPage.value = 3

      await prevPage()

      expect(currentPage.value).toBe(2)
    })

    it('hasNextPage computed correctly', () => {
      const { hasNextPage, currentPage, totalItems, perPage } = useTableData()
      totalItems.value = 100
      perPage.value = 25

      currentPage.value = 1
      expect(hasNextPage.value).toBe(true)

      currentPage.value = 4
      expect(hasNextPage.value).toBe(false)
    })

    it('hasPrevPage computed correctly', () => {
      const { hasPrevPage, currentPage } = useTableData()

      currentPage.value = 1
      expect(hasPrevPage.value).toBe(false)

      currentPage.value = 2
      expect(hasPrevPage.value).toBe(true)
    })
  })

  describe('filter methods', () => {
    it('setFilters updates filters and resets page', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { setFilters, startDate, endDate, selectedSpecies, currentPage } = useTableData()
      currentPage.value = 3

      await setFilters({
        startDate: '2024-01-01',
        endDate: '2024-01-31',
        species: 'Robin'
      })

      expect(startDate.value).toBe('2024-01-01')
      expect(endDate.value).toBe('2024-01-31')
      expect(selectedSpecies.value).toBe('Robin')
      expect(currentPage.value).toBe(1)
      expect(mockApi.get).toHaveBeenCalled()
    })

    it('clearFilters resets all filters', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { clearFilters, startDate, endDate, selectedSpecies, currentPage } = useTableData()
      startDate.value = '2024-01-01'
      endDate.value = '2024-01-31'
      selectedSpecies.value = 'Robin'
      currentPage.value = 3

      await clearFilters()

      expect(startDate.value).toBeNull()
      expect(endDate.value).toBeNull()
      expect(selectedSpecies.value).toBeNull()
      expect(currentPage.value).toBe(1)
      expect(mockApi.get).toHaveBeenCalled()
    })
  })

  describe('sort methods', () => {
    it('toggleSort changes sort order for same field', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { toggleSort, sortField, sortOrder, currentPage } = useTableData()
      currentPage.value = 3

      await toggleSort('timestamp')

      expect(sortField.value).toBe('timestamp')
      expect(sortOrder.value).toBe('asc') // Was desc, toggled to asc
      expect(currentPage.value).toBe(1)
    })

    it('toggleSort changes field and defaults to desc', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { toggleSort, sortField, sortOrder } = useTableData()

      await toggleSort('confidence')

      expect(sortField.value).toBe('confidence')
      expect(sortOrder.value).toBe('desc')
    })
  })

  describe('perPage methods', () => {
    it('setPerPage updates per_page and resets page', async () => {
      mockApi.get.mockResolvedValue({
        data: { detections: [], pagination: { total_items: 0 } }
      })

      const { setPerPage, perPage, currentPage } = useTableData()
      currentPage.value = 3

      await setPerPage(50)

      expect(perPage.value).toBe(50)
      expect(currentPage.value).toBe(1)
      expect(mockApi.get).toHaveBeenCalled()
    })

    it('setPerPage only accepts valid values', async () => {
      const { setPerPage, perPage } = useTableData()

      await setPerPage(30) // Invalid

      expect(perPage.value).toBe(25) // Should stay at default
      expect(mockApi.get).not.toHaveBeenCalled()
    })
  })

	  describe('error handling', () => {
	    it('clearError clears error message', () => {
	      const { error, actionError, clearError } = useTableData()
	      error.value = 'Some error'
	      actionError.value = 'Some action error'

	      clearError()

	      expect(error.value).toBeNull()
	      expect(actionError.value).toBeNull()
	    })

	    it('clearActionError clears action error message', () => {
	      const { actionError, clearActionError } = useTableData()
	      actionError.value = 'Some action error'

	      clearActionError()

	      expect(actionError.value).toBeNull()
	    })
	  })
	})
