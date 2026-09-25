/**
 * Readiness wait between "the API is back" and reloading the page.
 *
 * The API answers seconds before the model server has loaded its model or the
 * main container has started recording. Instead of a fixed delay, poll the
 * backend's coarse readiness summary (/api/system/readiness) until no service
 * is still starting.
 *
 * Two consumers: the restart/update wait (useServiceRestart) and the
 * boot-time update overlay (useUpdateOverlay).
 */
import { API_BASE } from '@/services/baseUrl'

export const READINESS_URL = `${API_BASE}/system/readiness`

const FETCH_TIMEOUT_MS = 5000

/**
 * Fetch the per-service states ({model, recorder}).
 *
 * Resolves to the states, 'unsupported' when the backend predates the
 * endpoint (a 4xx other than 429: 404, or an older default-deny 401), or null
 * on anything retryable (server down, 5xx, rate limit, malformed body). Never
 * rejects. Raw fetch, like updateStage.js: no axios interceptors and no
 * 'api:unreachable' event while the stack is still coming up.
 */
export async function fetchServiceStates() {
  const controller = new AbortController()
  const abortTimer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetch(READINESS_URL, { cache: 'no-store', signal: controller.signal })
    if (response.status >= 400 && response.status < 500 && response.status !== 429) {
      return 'unsupported'
    }
    if (!response.ok) return null
    const data = await response.json()
    return data?.services && typeof data.services === 'object' ? data.services : null
  } catch (_error) {
    return null
  } finally {
    clearTimeout(abortTimer)
  }
}

/** What is still starting, for the banner (no trailing punctuation). */
export function describeReadiness(services) {
  return services.model === 'starting' ? 'Loading the detection model' : 'Starting the audio recorder'
}

// Resolves true after ms, or false as soon as the signal aborts.
function sleep(ms, signal) {
  return new Promise(resolve => {
    if (signal?.aborted) return resolve(false)
    const onAbort = () => {
      clearTimeout(timer)
      resolve(false)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve(true)
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * Poll readiness until no service is still starting.
 *
 * Resolves true when the caller should reload: every service settled (a
 * failed model included; the app reports it), the backend predates the
 * endpoint, or maxWaitMs passed — the page itself only needs the API.
 * Resolves false only when the signal aborts.
 *
 * @param {Object} options
 * @param {number} options.maxWaitMs - Give up waiting after this long (default 90s)
 * @param {number} options.pollIntervalMs - Delay between polls (default 2s)
 * @param {AbortSignal} options.signal - Cancels the wait
 * @param {Function} options.onProgress - Called with describeReadiness()
 *   text while a service is still starting
 */
export async function waitForServicesReady({
  maxWaitMs = 90000,
  pollIntervalMs = 2000,
  signal,
  onProgress
} = {}) {
  const deadline = Date.now() + maxWaitMs
  for (;;) {
    if (signal?.aborted) return false
    const services = await fetchServiceStates()
    if (signal?.aborted) return false
    if (services === 'unsupported') return true
    if (services) {
      if (!Object.values(services).includes('starting')) return true
      onProgress?.(describeReadiness(services))
    }

    const remaining = deadline - Date.now()
    if (remaining <= 0) return true
    if (!await sleep(Math.min(pollIntervalMs, remaining), signal)) return false
  }
}
