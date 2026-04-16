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

// Auth endpoints manage their own 401 semantics (bad password, setup-not-complete).
// The session-expired flow should only fire for non-auth endpoints.
const isAuthEndpoint = (url) => typeof url === 'string' && url.includes('/auth/')

const authErrorHandler = (error) => {
  if (error.response?.status === 401 && !isAuthEndpoint(error.config?.url)) {
    window.dispatchEvent(new CustomEvent('auth:required'))
  }
  return Promise.reject(error)
}

function createApiInstance(timeout) {
  const instance = axios.create({
    baseURL: API_BASE,
    timeout,
    headers: { 'Content-Type': 'application/json' }
  })
  instance.interceptors.response.use((response) => response, authErrorHandler)
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
