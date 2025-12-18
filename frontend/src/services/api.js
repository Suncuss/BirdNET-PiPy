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

/**
 * Pre-configured axios instance for internal API calls.
 * Use this for all /api/* endpoints.
 */
const api = axios.create({
  baseURL: '/api',
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
 * Use for system updates, large data imports, etc.
 *
 * @param {number} timeout - Timeout in milliseconds (default: 5 minutes)
 * @returns {import('axios').AxiosInstance}
 */
export function createLongRequest(timeout = LONG_TIMEOUT) {
  return axios.create({
    baseURL: '/api',
    timeout,
    headers: {
      'Content-Type': 'application/json'
    }
  })
}

// Export both default and named for flexibility
export default api
export { api }
