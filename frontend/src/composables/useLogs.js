import { ref, onUnmounted } from 'vue'
import api from '@/services/api'

const POLL_INTERVAL = 3000

export function useLogs() {
  const entries = ref([])
  const total = ref(0)
  const isLoading = ref(false)
  const error = ref('')
  const serviceFilter = ref('')
  const searchQuery = ref('')
  const isPolling = ref(false)

  let pollTimer = null
  let abortController = null

  const fetchLogs = async () => {
    if (abortController) abortController.abort()
    abortController = new AbortController()

    try {
      isLoading.value = true
      error.value = ''

      const params = {}
      if (serviceFilter.value) params.service = serviceFilter.value
      if (searchQuery.value) params.search = searchQuery.value

      const { data } = await api.get('/system/logs', { params, signal: abortController.signal })
      // Skip update if data hasn't changed (avoids unnecessary reactivity cascade)
      const newFirst = data.entries[0]?.timestamp
      const oldFirst = entries.value[0]?.timestamp
      const newLast = data.entries[data.entries.length - 1]?.timestamp
      const oldLast = entries.value[entries.value.length - 1]?.timestamp
      if (data.total !== total.value || newFirst !== oldFirst || newLast !== oldLast || data.entries.length !== entries.value.length) {
        entries.value = data.entries
        total.value = data.total
      }
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return
      error.value = err.response?.data?.error || 'Failed to fetch logs'
    } finally {
      isLoading.value = false
    }
  }

  const startPolling = () => {
    stopPolling()
    isPolling.value = true
    fetchLogs()
    pollTimer = setInterval(fetchLogs, POLL_INTERVAL)
  }

  const stopPolling = () => {
    isPolling.value = false
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const applyFilters = () => {
    fetchLogs()
  }

  const clearFilters = () => {
    serviceFilter.value = ''
    searchQuery.value = ''
    fetchLogs()
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    entries,
    total,
    isLoading,
    error,
    serviceFilter,
    searchQuery,
    isPolling,
    fetchLogs,
    startPolling,
    stopPolling,
    applyFilters,
    clearFilters
  }
}
