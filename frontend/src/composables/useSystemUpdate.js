import { ref, computed } from 'vue'
import api, { createLongRequest } from '@/services/api'
import { useLogger } from './useLogger'
import { useServiceRestart } from './useServiceRestart'

// Module-level state (shared across all components - singleton)
const versionInfo = ref(null)
const updateInfo = ref(null)
const updateAvailable = ref(false)
const checking = ref(false)
const updating = ref(false)
const statusMessage = ref(null)
const statusType = ref(null) // 'success', 'error', 'info'

// Dismissal state - stores expiry timestamp (when to show again)
const DISMISS_STORAGE_KEY = 'birdnet_update_dismissed_until'
const DISMISS_DURATION_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function loadDismissedUntil() {
  try {
    const stored = localStorage.getItem(DISMISS_STORAGE_KEY)
    return stored ? parseInt(stored, 10) : null
  } catch {
    return null
  }
}

const dismissedUntil = ref(loadDismissedUntil())

export function useSystemUpdate() {
  const logger = useLogger('useSystemUpdate')
  const serviceRestart = useServiceRestart()

  // Computed: should show indicator (update available AND not dismissed)
  const showUpdateIndicator = computed(() => {
    if (!updateAvailable.value) return false
    return !dismissedUntil.value || Date.now() >= dismissedUntil.value
  })

  const dismissUpdate = () => {
    const expiry = Date.now() + DISMISS_DURATION_MS
    dismissedUntil.value = expiry
    localStorage.setItem(DISMISS_STORAGE_KEY, String(expiry))
  }

  /**
   * Load current version information
   */
  const loadVersionInfo = async () => {
    try {
      const { data } = await api.get('/system/version')
      versionInfo.value = data
      logger.info('Version info loaded', data)
      return data
    } catch (error) {
      logger.error('Failed to load version info', error)
      setStatus('error', 'Failed to load version information')
      throw error
    }
  }

  /**
   * Check for available updates
   * @param {Object} options
   * @param {boolean} options.silent - Skip status message updates (for background checks)
   * @param {boolean} options.force - Bypass backend cache
   */
  const checkForUpdates = async (options = {}) => {
    const { silent = false, force = false } = options

    checking.value = true
    if (!silent) {
      statusMessage.value = null
    }

    try {
      logger.info('Checking for updates...', { silent, force })
      const url = force ? '/system/update-check?force=true' : '/system/update-check'
      const { data } = await api.get(url)
      updateInfo.value = data
      updateAvailable.value = data.update_available

      if (!silent) {
        if (data.update_available) {
          // No status message needed - the update box in the UI is sufficient
          logger.info('Update available', data)
        } else {
          setStatus('success', 'System is up to date')
          logger.info('System is up to date', {
            current: data.current_commit,
            remote: data.remote_commit,
            branch: data.current_branch
          })
        }
      }

      return data
    } catch (error) {
      logger.error('Failed to check for updates', error)
      if (!silent) {
        setStatus('error', 'Failed to check for updates. Check network connection.')
      }
      throw error
    } finally {
      checking.value = false
    }
  }

  /**
   * Trigger system update
   * @param {boolean} skipConfirm - Skip the browser confirmation dialog (when using custom modal)
   */
  const triggerUpdate = async (skipConfirm = false) => {
    // Confirmation dialog (skip if already confirmed via custom modal)
    if (!skipConfirm) {
      const confirmed = window.confirm(
        `This will update the system and restart all services.\n\n` +
        `Expected downtime: 2-5 minutes\n` +
        `Audio detection will be interrupted during this time.\n\n` +
        `Continue with update?`
      )

      if (!confirmed) {
        logger.info('Update cancelled by user')
        return
      }
    }

    updating.value = true
    statusMessage.value = null

    try {
      logger.info('Triggering system update...')
      // Use long timeout for update operation (5 minutes)
      const longApi = createLongRequest()
      const { data } = await longApi.post('/system/update')

      if (data.status === 'no_update_needed') {
        setStatus('info', 'System is already up to date')
        updating.value = false
        return
      }

      setStatus('info', 'Update started. Services restarting...')
      logger.info('Update triggered successfully', data)

      // Use shared service restart monitoring
      await serviceRestart.waitForRestart({
        maxWaitSeconds: 600, // 10 minutes for updates
        autoReload: true,
        message: 'System updating'
      })
    } catch (error) {
      updating.value = false
      // Timeout is not a failure - just taking longer than expected
      if (error.message === 'RESTART_TIMEOUT') {
        logger.warn('Update restart timeout - may still be in progress')
        setStatus('info', 'Update taking longer than expected. Try refreshing later.')
      } else {
        logger.error('Failed to trigger update', error)
        setStatus('error', `Update failed: ${error.message}`)
        throw error
      }
    }
  }

  /**
   * Set status message with auto-clear for non-error messages
   */
  const setStatus = (type, message) => {
    statusType.value = type
    statusMessage.value = message

    // Auto-clear success/info messages after 10 seconds
    if (type !== 'error') {
      setTimeout(() => {
        if (statusMessage.value === message) {
          statusMessage.value = null
          statusType.value = null
        }
      }, 10000)
    }
  }

  return {
    // State
    versionInfo,
    updateInfo,
    updateAvailable,
    checking,
    updating,
    statusMessage,
    statusType,
    // New
    showUpdateIndicator,
    dismissUpdate,
    // Expose service restart state for UI
    restartMessage: serviceRestart.restartMessage,
    restartError: serviceRestart.restartError,
    isRestarting: serviceRestart.isRestarting,
    // Methods
    loadVersionInfo,
    checkForUpdates,
    triggerUpdate
  }
}
