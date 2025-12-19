import { ref, computed } from 'vue'
import api from '@/services/api'
import { useLogger } from './useLogger'

/**
 * Composable for managing paginated detection table data.
 * Handles fetching, filtering, sorting, pagination, and deletion.
 */
export function useTableData() {
  const logger = useLogger('useTableData')

  // Pagination state
  const currentPage = ref(1)
  const perPage = ref(25)
  const totalItems = ref(0)
  const totalPages = computed(() =>
    perPage.value > 0 ? Math.ceil(totalItems.value / perPage.value) : 0
  )

  // Data state
  const detections = ref([])
  const isLoading = ref(false)
  const error = ref(null)
  const actionError = ref(null)

  // Filter state
  const startDate = ref(null)
  const endDate = ref(null)
  const selectedSpecies = ref(null)

  // Sorting state
  const sortField = ref('timestamp')
  const sortOrder = ref('desc')

  // Selection state
  const selectedIds = ref(new Set())

  // Computed for pagination info
  const hasNextPage = computed(() => currentPage.value < totalPages.value)
  const hasPrevPage = computed(() => currentPage.value > 1)

  // Computed for active filters
  const hasActiveFilters = computed(() =>
    !!(startDate.value || endDate.value || selectedSpecies.value)
  )

  // Computed for selection
  const selectedCount = computed(() => selectedIds.value.size)
  const allSelected = computed(() =>
    detections.value.length > 0 &&
    detections.value.every(d => selectedIds.value.has(d.id))
  )

  /**
   * Fetch detections from API with current filters and pagination.
   */
  async function fetchDetections() {
    isLoading.value = true
    error.value = null

    try {
      while (true) {
        const params = {
          page: currentPage.value,
          per_page: perPage.value,
          sort: sortField.value,
          order: sortOrder.value
        }

        if (startDate.value) params.start_date = startDate.value
        if (endDate.value) params.end_date = endDate.value
        if (selectedSpecies.value) params.species = selectedSpecies.value

        logger.info('Fetching detections', params)

        const response = await api.get('/detections', { params })
        logger.api('GET', '/detections', params, response)

        detections.value = Array.isArray(response.data?.detections)
          ? response.data.detections
          : []
        totalItems.value = Number(response.data?.pagination?.total_items) || 0

        const serverTotalPages = response.data?.pagination?.total_pages
        if (Number.isFinite(serverTotalPages) && serverTotalPages > 0 && currentPage.value > serverTotalPages) {
          currentPage.value = serverTotalPages
          continue
        }

        if (Number.isFinite(serverTotalPages) && serverTotalPages === 0) {
          currentPage.value = 1
        }

        logger.debug('Detections fetched successfully', {
          count: detections.value.length,
          totalItems: totalItems.value,
          page: currentPage.value
        })

        break
      }
    } catch (err) {
      logger.error('Failed to fetch detections', err)
      error.value = 'Failed to load detections. Please try again.'
      detections.value = []
      totalItems.value = 0
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Delete a detection by ID.
   * @param {number} id - Detection ID to delete
   * @returns {Promise<boolean>} - True if deletion was successful
   */
  async function deleteDetection(id) {
    logger.info('Deleting detection', { id })
    actionError.value = null

    try {
      const response = await api.delete(`/detections/${id}`)
      logger.api('DELETE', `/detections/${id}`, null, response)

      if (response.data?.status === 'deleted') {
        logger.info('Detection deleted successfully', {
          id,
          species: response.data.species
        })

        // Refresh the current page
        await fetchDetections()
        return true
      }
      return false
    } catch (err) {
      logger.error('Failed to delete detection', err)

      if (err.response?.status === 401) {
        actionError.value = 'Authentication required to delete detections.'
      } else if (err.response?.status === 404) {
        actionError.value = 'Detection not found.'
      } else {
        actionError.value = 'Failed to delete detection. Please try again.'
      }
      return false
    }
  }

  /**
   * Toggle selection for a single detection.
   * @param {number} id - Detection ID
   */
  function toggleSelection(id) {
    const newSet = new Set(selectedIds.value)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    selectedIds.value = newSet
  }

  /**
   * Check if a detection is selected.
   * @param {number} id - Detection ID
   * @returns {boolean}
   */
  function isSelected(id) {
    return selectedIds.value.has(id)
  }

  /**
   * Toggle select all on current page.
   */
  function toggleSelectAll() {
    if (allSelected.value) {
      // Deselect all on current page
      const newSet = new Set(selectedIds.value)
      detections.value.forEach(d => newSet.delete(d.id))
      selectedIds.value = newSet
    } else {
      // Select all on current page
      const newSet = new Set(selectedIds.value)
      detections.value.forEach(d => newSet.add(d.id))
      selectedIds.value = newSet
    }
  }

  /**
   * Clear all selections.
   */
  function clearSelection() {
    selectedIds.value = new Set()
  }

  /**
   * Delete all selected detections.
   * @returns {Promise<{success: boolean, deleted: number, failed: number}>}
   */
  async function deleteSelected() {
    if (selectedIds.value.size === 0) {
      return { success: false, deleted: 0, failed: 0 }
    }

    logger.info('Batch deleting detections', { count: selectedIds.value.size })
    actionError.value = null

    try {
      const ids = Array.from(selectedIds.value)
      const response = await api.delete('/detections/batch', { data: { ids } })
      logger.api('DELETE', '/detections/batch', { ids }, response)

      const { deleted, failed } = response.data

      if (deleted > 0) {
        logger.info('Batch deletion successful', { deleted, failed })
        clearSelection()
        await fetchDetections()
      }

      if (failed > 0) {
        actionError.value = `Deleted ${deleted} detection(s), but ${failed} failed.`
      }

      return { success: deleted > 0, deleted, failed }
    } catch (err) {
      logger.error('Failed to batch delete detections', err)

      if (err.response?.status === 401) {
        actionError.value = 'Authentication required to delete detections.'
      } else {
        actionError.value = 'Failed to delete detections. Please try again.'
      }
      return { success: false, deleted: 0, failed: selectedIds.value.size }
    }
  }

  /**
   * Navigate to a specific page.
   * @param {number} page - Page number (1-indexed)
   */
  function goToPage(page) {
    if (page >= 1 && page <= totalPages.value) {
      currentPage.value = page
      fetchDetections()
    }
  }

  /**
   * Go to next page if available.
   */
  function nextPage() {
    if (hasNextPage.value) {
      goToPage(currentPage.value + 1)
    }
  }

  /**
   * Go to previous page if available.
   */
  function prevPage() {
    if (hasPrevPage.value) {
      goToPage(currentPage.value - 1)
    }
  }

  /**
   * Set filters and reset to page 1.
   * @param {Object} filters - Filter values
   * @param {string} [filters.startDate] - Start date (YYYY-MM-DD)
   * @param {string} [filters.endDate] - End date (YYYY-MM-DD)
   * @param {string} [filters.species] - Species common name
   */
  function setFilters(filters) {
    if (filters.startDate !== undefined) startDate.value = filters.startDate || null
    if (filters.endDate !== undefined) endDate.value = filters.endDate || null
    if (filters.species !== undefined) selectedSpecies.value = filters.species || null

    // Reset to page 1 when filters change
    currentPage.value = 1
    fetchDetections()
  }

  /**
   * Clear all filters and reset to page 1.
   */
  function clearFilters() {
    startDate.value = null
    endDate.value = null
    selectedSpecies.value = null
    currentPage.value = 1
    fetchDetections()
  }

  /**
   * Toggle sort order or change sort field.
   * @param {string} field - Field to sort by (timestamp, confidence, common_name)
   */
  function toggleSort(field) {
    if (sortField.value === field) {
      // Toggle order if same field
      sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
    } else {
      // Change field and default to desc
      sortField.value = field
      sortOrder.value = 'desc'
    }

    // Reset to page 1 when sort changes
    currentPage.value = 1
    fetchDetections()
  }

  /**
   * Change the number of items per page.
   * @param {number} count - Items per page (25, 50, or 100)
   */
  function setPerPage(count) {
    if ([25, 50, 100].includes(count)) {
      perPage.value = count
      currentPage.value = 1
      fetchDetections()
    }
  }

  /**
   * Clear error message.
   */
  function clearError() {
    error.value = null
    actionError.value = null
  }

  function clearActionError() {
    actionError.value = null
  }

  return {
    // State
    detections,
    currentPage,
    perPage,
    totalItems,
    totalPages,
    isLoading,
    error,
    actionError,

    // Filters
    startDate,
    endDate,
    selectedSpecies,
    hasActiveFilters,

    // Sorting
    sortField,
    sortOrder,

    // Selection
    selectedIds,
    selectedCount,
    allSelected,

    // Pagination
    hasNextPage,
    hasPrevPage,

    // Methods
    fetchDetections,
    deleteDetection,
    deleteSelected,
    toggleSelection,
    isSelected,
    toggleSelectAll,
    clearSelection,
    goToPage,
    nextPage,
    prevPage,
    setFilters,
    clearFilters,
    toggleSort,
    setPerPage,
    clearError,
    clearActionError
  }
}
