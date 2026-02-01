import { ref, computed } from 'vue'
import { useLogger } from './useLogger'

/**
 * Shared state (singleton pattern) - all components share the same refs.
 * This ensures that when one component updates auth state, all others see the change.
 */
const authStatus = ref({
  authEnabled: false,
  setupComplete: false,
  authenticated: false
})
const loading = ref(false)
const error = ref('')

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

  /**
   * Check current authentication status from API
   * @returns {Promise<boolean>} - True if status was retrieved successfully
   */
  const checkAuthStatus = async () => {
    try {
      const response = await fetch('/api/auth/status')
      if (response.ok) {
        const data = await response.json()
        authStatus.value = {
          authEnabled: data.auth_enabled,
          setupComplete: data.setup_complete,
          authenticated: data.authenticated
        }
        error.value = ''
        logger.debug('Auth status checked', authStatus.value)
        return true
      } else {
        error.value = 'Failed to check authentication status'
        logger.error('Auth status check failed', { status: response.status })
        return false
      }
    } catch (err) {
      error.value = 'Connection error - could not check authentication'
      logger.error('Failed to check auth status', err)
      return false
    }
  }

  /**
   * Login with password
   * @param {string} password - The password to authenticate with
   * @returns {Promise<boolean>} - True if login successful
   */
  const login = async (password) => {
    loading.value = true
    error.value = ''

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      })

      const data = await response.json()

      if (response.ok) {
        authStatus.value.authenticated = true
        logger.info('Login successful')
        return true
      } else {
        error.value = data.error || 'Login failed'
        logger.warn('Login failed', { error: error.value })
        return false
      }
    } catch (err) {
      error.value = 'Connection error'
      logger.error('Login error', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Logout and clear session
   */
  const logout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
      authStatus.value.authenticated = false
      logger.info('Logged out')
    } catch (err) {
      logger.error('Logout error', err)
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
      const response = await fetch('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      })

      const data = await response.json()

      if (response.ok) {
        authStatus.value.authEnabled = true
        authStatus.value.setupComplete = true
        authStatus.value.authenticated = true
        logger.info('Password setup successful')
        return true
      } else {
        error.value = data.error || 'Setup failed'
        logger.warn('Setup failed', { error: error.value })
        return false
      }
    } catch (err) {
      error.value = 'Connection error'
      logger.error('Setup error', err)
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
      const response = await fetch('/api/auth/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      })

      const data = await response.json()

      if (response.ok) {
        authStatus.value.authEnabled = data.auth_enabled
        logger.info('Auth toggled', { enabled: data.auth_enabled })
        return true
      } else {
        error.value = data.error || 'Toggle failed'
        return false
      }
    } catch (err) {
      error.value = 'Connection error'
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
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      })

      const data = await response.json()

      if (response.ok) {
        logger.info('Password changed successfully')
        return true
      } else {
        error.value = data.error || 'Password change failed'
        return false
      }
    } catch (err) {
      error.value = 'Connection error'
      logger.error('Change password error', err)
      return false
    } finally {
      loading.value = false
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
    authStatus.value = {
      authEnabled: false,
      setupComplete: false,
      authenticated: false
    }
    loading.value = false
    error.value = ''
  }

  return {
    // State
    authStatus,
    loading,
    error,

    // Computed
    needsLogin,
    isAuthenticated,

    // Methods
    checkAuthStatus,
    login,
    logout,
    setup,
    toggleAuth,
    changePassword,
    clearError,
    resetState
  }
}
