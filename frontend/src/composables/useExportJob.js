import { ref, computed, onUnmounted } from 'vue'
import api, { SLOW_QUERY_TIMEOUT } from '@/services/api'
import { API_BASE } from '@/services/baseUrl'

const POLL_INTERVAL_MS = 1000

/**
 * Client side of a prepared detection export (backend: core/export_jobs.py).
 *
 * The job lives on the server — one at a time, surviving a closed modal or
 * a page reload — so this only mirrors it: `load()` picks up whatever job
 * exists, polling runs only while it is preparing and this component is
 * mounted, and the download is a plain link so the browser streams the file
 * to disk instead of holding it in memory.
 *
 * `job` is the server snapshot ({ id, state, rows_done, rows_total, bytes,
 * filename, ... }) or null when there is none. `loading` covers the initial
 * lookup, `starting` a start request. `today` is the station's local date
 * (YYYY-MM-DD) once `load()` has run. `options` everywhere is
 * { range, start_date?, end_date? } with range = all | 7d | 30d | year | custom.
 */
export function useExportJob() {
  const job = ref(null)
  const error = ref('')
  const loading = ref(false)
  const starting = ref(false)
  const today = ref(null)
  let pollTimer = null
  // Requests still in flight at unmount must not start polling again.
  let mounted = true

  const stopPolling = () => {
    clearTimeout(pollTimer)
    pollTimer = null
  }

  const schedulePoll = () => {
    stopPolling()
    if (mounted && job.value?.state === 'preparing') {
      pollTimer = setTimeout(poll, POLL_INTERVAL_MS)
    }
  }

  const poll = async () => {
    const id = job.value?.id
    if (!id) return
    try {
      const { data } = await api.get(`/detections/export/jobs/${id}`)
      if (job.value?.id !== id) return // discarded while the poll was in flight
      job.value = data.job
    } catch (err) {
      if (job.value?.id !== id) return
      if (err.response?.status === 404) {
        job.value = null
        error.value = 'The export expired or was cancelled. Start a new one.'
        return
      }
      // Transient (network blip, restart in progress): keep polling.
    }
    schedulePoll()
  }

  const load = async () => {
    loading.value = true
    try {
      const { data } = await api.get('/detections/export/jobs/current')
      job.value = data.job
      today.value = data.today
      schedulePoll()
    } catch {
      error.value = 'Could not check for an existing export.'
    } finally {
      loading.value = false
    }
  }

  const fetchCount = async (options) => {
    const { data } = await api.get('/detections/export/count', {
      params: options,
      timeout: SLOW_QUERY_TIMEOUT
    })
    return data.count
  }

  const start = async (options) => {
    error.value = ''
    starting.value = true
    try {
      const { data } = await api.post('/detections/export/jobs', options, {
        timeout: SLOW_QUERY_TIMEOUT
      })
      job.value = data.job
    } catch (err) {
      const running = err.response?.status === 409 && err.response.data?.job
      if (running) {
        job.value = running
      } else {
        error.value = err.response?.data?.error || 'Could not start the export.'
      }
    } finally {
      starting.value = false
      schedulePoll()
    }
  }

  // Cancel a preparing export, or delete a finished one's file.
  const discard = async () => {
    const id = job.value?.id
    stopPolling()
    job.value = null
    error.value = ''
    if (!id) return
    try {
      await api.delete(`/detections/export/jobs/${id}`)
    } catch {
      // 404: already gone. Anything else: the server expires it within the hour.
    }
  }

  const percent = computed(() => {
    const { rows_done: done, rows_total: total } = job.value || {}
    return total ? Math.min(100, Math.floor((done / total) * 100)) : 0
  })

  const downloadUrl = computed(() =>
    job.value?.state === 'ready'
      ? `${API_BASE}/detections/export/jobs/${job.value.id}/file`
      : null
  )

  onUnmounted(() => {
    mounted = false
    stopPolling()
  })

  return { job, error, loading, starting, today, percent, downloadUrl, load, fetchCount, start, discard }
}
