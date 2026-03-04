/**
 * Central API service for all internal API calls.
 *
 * Provides a pre-configured axios instance with:
 * - Base URL: /api
 * - Default timeout: 15 seconds
 * - Response interceptor for 401 handling
 * - Helper for long-running operations
 */
import axios from 'axios'

// Default timeout for most requests (15 seconds)
const DEFAULT_TIMEOUT = 15000

// Long timeout for operations like system updates (5 minutes)
const LONG_TIMEOUT = 300000

const stripTrailingSlash = (value) => (value?.endsWith('/') ? value.slice(0, -1) : value)

const getIngressBaseFromPathname = (pathname) => {
  const match = String(pathname || '').match(/^\/api\/hassio_ingress\/[^/]+/)
  return match ? match[0] : ''
}

/**
 * Resolve API base URL for native and Home Assistant ingress modes.
 * In ingress mode, HA normally injects:
 *   <base href="/api/hassio_ingress/<token>/">
 * This also includes a pathname fallback so ingress still works if <base> is not present.
 */
export function getApiBaseUrl() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return '/api'

  const baseHref = document.querySelector('base')?.getAttribute('href')
  if (baseHref) {
    return `${stripTrailingSlash(baseHref)}/api`
  }

  const ingressBase = getIngressBaseFromPathname(window.location.pathname)
  if (ingressBase) {
    return `${ingressBase}/api`
  }

  return '/api'
}

export function getAppBaseUrl() {
  const apiBase = stripTrailingSlash(getApiBaseUrl())
  return apiBase.endsWith('/api') ? apiBase.slice(0, -4) : ''
}

const API_BASE_URL = getApiBaseUrl()

/**
 * Pre-configured axios instance for internal API calls.
 * Use this for all /api/* endpoints.
 */
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_TIMEOUT,
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * Response interceptor for global error handling.
 * Emits 'auth:required' event on 401 responses.
 */
api.interceptors.response.use(
  // Success handler - pass through
  (response) => response,

  // Error handler
  (error) => {
    // Handle 401 Unauthorized - emit event for App.vue to handle
    if (error.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:required'))
    }

    // Re-throw the error for individual handlers
    return Promise.reject(error)
  }
)

/**
 * Create an axios instance with a longer timeout for long-running operations.
 * Use for system updates, large data exports, etc.
 *
 * Includes the same 401 interceptor as the default api instance for
 * consistent auth handling.
 *
 * @param {number} timeout - Timeout in milliseconds (default: 5 minutes)
 * @returns {import('axios').AxiosInstance}
 */
export function createLongRequest(timeout = LONG_TIMEOUT) {
  const instance = axios.create({
    baseURL: API_BASE_URL,
    timeout,
    headers: {
      'Content-Type': 'application/json'
    }
  })

  // Add same 401 interceptor for consistent auth handling
  instance.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        window.dispatchEvent(new CustomEvent('auth:required'))
      }
      return Promise.reject(error)
    }
  )

  return instance
}

// Export both default and named for flexibility
export default api
export { api }
