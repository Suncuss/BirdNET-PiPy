import { ref, computed } from 'vue'
import api from '@/services/api'
import { createCoalescedLoader } from '@/utils/coalescedLoader'
import { useLogger } from './useLogger'

// Pre-load / post-reset shape of the auth status — single owner, so a new
// field can't be added to one copy and silently reset to a stale shape.
const defaultAuthStatus = () => ({
  authEnabled: false,
  setupComplete: false,
  authenticated: false,
  publicAccess: true,
  publicFeatures: [],
  stationName: ''
})

/**
 * Shared state (singleton pattern) - all components share the same refs.
 * This ensures that when one component updates auth state, all others see the change.
 */
const authStatus = ref(defaultAuthStatus())
const loading = ref(false)
const error = ref('')

// Server responses surface their own error message; network/timeout errors
// (no err.response) always show "Connection error" regardless of fallback.
const errorMessage = (err, serverFallback) =>
  err.response?.data?.error || (err.response ? serverFallback : 'Connection error')

// Coalesces the one-time /auth/status load — see ensureAuthLoaded().
const authLoad = createCoalescedLoader()

/**
 * Composable for authentication state management.
 * Handles login, logout, setup, and auth status checking.
 */
export function useAuth() {
  const logger = useLogger('useAuth')

  // Computed properties
  const needsLogin = computed(() =>
    authStatus.value.authEnabled && !authStatus.value.authenticated
  )

  const isAuthenticated = computed(() =>
    !authStatus.value.authEnabled || authStatus.value.authenticated
  )

  // Sign-in required and no limited public view either: the API 401s
  // everything, so views render a blank shell behind the login modal.
  const authGated = computed(() =>
    needsLogin.value && !authStatus.value.publicAccess
  )

  /**
   * Check current authentication status from API
   * @returns {Promise<boolean>} - True if status was retrieved successfully
   */
  const checkAuthStatus = async () => {
    try {
      // Tiny endpoint — fail fast so a degraded backend can't stall the guard.
      const { data } = await api.get('/auth/status', { timeout: 4000 })
      authStatus.value = {
        authEnabled: data.auth_enabled,
        setupComplete: data.setup_complete,
        authenticated: data.authenticated,
        // Default true so an older backend without the field keeps the
        // limited public view (the master switch is opt-out).
        publicAccess: data.public_access !== false,
        publicFeatures: data.public_features || [],
        stationName: data.station_name || ''
      }
      error.value = ''
      logger.debug('Auth status checked', authStatus.value)
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Failed to check authentication status')
      logger.error('Failed to check auth status', err)
      return false
    }
  }

  /**
   * Ensure auth status has loaded at least once (coalesced; a failed load
   * retries on the next call). The authStatus singleton is then kept
   * current by the mutations below.
   * @returns {Promise<boolean>}
   */
  const ensureAuthLoaded = () => authLoad.ensure(checkAuthStatus)

  /**
   * Login with password
   * @param {string} password - The password to authenticate with
   * @returns {Promise<boolean>} - True if login successful
   */
  const login = async (password) => {
    loading.value = true
    error.value = ''

    try {
      await api.post('/auth/login', { password })
      authStatus.value.authenticated = true
      logger.info('Login successful')
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Login failed')
      logger.warn('Login failed', { error: error.value, status: err.response?.status })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Logout and clear session
   */
  /**
   * End the session.
   * @returns {Promise<boolean>} true when the session actually ended. A failed
   * request leaves the user signed in, so callers must not tear down
   * authenticated state on a false.
   */
  const logout = async () => {
    try {
      await api.post('/auth/logout')
      authStatus.value.authenticated = false
      logger.info('Logged out')
      return true
    } catch (err) {
      logger.error('Logout error', err)
      return false
    }
  }

  /**
   * Set up initial password (first-time setup)
   * @param {string} password - The password to set
   * @returns {Promise<boolean>} - True if setup successful
   */
  const setup = async (password) => {
    loading.value = true
    error.value = ''

    try {
      await api.post('/auth/setup', { password })
      authStatus.value.authEnabled = true
      authStatus.value.setupComplete = true
      authStatus.value.authenticated = true
      logger.info('Password setup successful')
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Setup failed')
      logger.warn('Setup failed', { error: error.value, status: err.response?.status })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Toggle authentication on/off
   * @param {boolean} enabled - Whether to enable authentication
   * @returns {Promise<boolean>} - True if toggle successful
   */
  const toggleAuth = async (enabled) => {
    loading.value = true
    error.value = ''

    try {
      const { data } = await api.post('/auth/toggle', { enabled })
      authStatus.value.authEnabled = data.auth_enabled
      logger.info('Auth toggled', { enabled: data.auth_enabled })
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Toggle failed')
      logger.error('Toggle error', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Change password (requires current password)
   * @param {string} currentPassword - Current password for verification
   * @param {string} newPassword - New password to set
   * @returns {Promise<boolean>} - True if change successful
   */
  const changePassword = async (currentPassword, newPassword) => {
    loading.value = true
    error.value = ''

    try {
      await api.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword
      })
      logger.info('Password changed successfully')
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Password change failed')
      logger.error('Change password error', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Save per-feature access settings
   * @param {Object} accessSettings - Partial access settings to save (e.g. {charts_public: true})
   * @returns {Promise<boolean>} - True if save successful
   */
  const saveAccessSettings = async (accessSettings) => {
    try {
      await api.put('/settings/access', accessSettings)
      await checkAuthStatus()
      logger.info('Access settings saved', accessSettings)
      return true
    } catch (err) {
      error.value = errorMessage(err, 'Failed to save access settings')
      logger.warn('Access settings save failed', { error: error.value })
      return false
    }
  }

  /**
   * Clear error state
   */
  const clearError = () => {
    error.value = ''
  }

  /**
   * Reset all state (for testing purposes)
   */
  const resetState = () => {
    authStatus.value = defaultAuthStatus()
    loading.value = false
    error.value = ''
    authLoad.reset()
  }

  return {
    // State
    authStatus,
    loading,
    error,

    // Computed
    needsLogin,
    isAuthenticated,
    authGated,

    // Methods
    checkAuthStatus,
    ensureAuthLoaded,
    login,
    logout,
    setup,
    toggleAuth,
    changePassword,
    saveAccessSettings,
    clearError,
    resetState
  }
}
