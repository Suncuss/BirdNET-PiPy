/**
 * Central API service for all internal API calls.
 *
 * Provides a pre-configured axios instance with:
 * - Base URL: <base href> + api
 * - Default timeout: 15 seconds
 * - Response interceptor for 401 handling (skips /auth/ endpoints)
 * - Helper for long-running operations
 */
import axios from 'axios'
import { API_BASE } from '@/services/baseUrl'

const DEFAULT_TIMEOUT = 15000
const LONG_TIMEOUT = 300000

// Budget for heavy read queries (dashboard aggregation, table fetches).
// Right after a stack restart the first reads can legitimately wait out
// main's backlog writes and WAL recovery (SQLite busy handling holds
// readers up to 30s); the 15s default turns that bounded wait into a
// dead view.
export const SLOW_QUERY_TIMEOUT = 45000

// Auth endpoints manage their own 401 semantics (bad password, setup-not-complete).
// The session-expired flow should only fire for non-auth endpoints.
const isAuthEndpoint = (url) => typeof url === 'string' && url.includes('/auth/')

// Backend-unreachable shapes: nginx proxying to a dead upstream (502/504) or
// no response at all (network error, timeout). May mean a native update has
// the stack down — the update overlay listens and decides (it requires a
// fresh /update-progress stage, so ordinary outages don't trigger it).
const isServerUnreachable = (error) =>
  !error.response || error.response.status === 502 || error.response.status === 504

const responseErrorHandler = (error) => {
  if (error.response?.status === 401 && !isAuthEndpoint(error.config?.url)) {
    window.dispatchEvent(new CustomEvent('auth:required'))
  }
  if (isServerUnreachable(error)) {
    window.dispatchEvent(new CustomEvent('api:unreachable'))
  }
  return Promise.reject(error)
}

function createApiInstance(timeout) {
  const instance = axios.create({
    baseURL: API_BASE,
    timeout,
    headers: { 'Content-Type': 'application/json' }
  })
  instance.interceptors.response.use((response) => response, responseErrorHandler)
  return instance
}

const api = createApiInstance(DEFAULT_TIMEOUT)

/**
 * Create an axios instance with a longer timeout for long-running operations.
 * Use for system updates, large data exports, etc.
 *
 * @param {number} timeout - Timeout in milliseconds (default: 5 minutes)
 * @returns {import('axios').AxiosInstance}
 */
export function createLongRequest(timeout = LONG_TIMEOUT) {
  return createApiInstance(timeout)
}

export default api
export { api }
