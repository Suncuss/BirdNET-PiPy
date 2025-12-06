import { ref } from 'vue'
import { useLogger } from './useLogger'
import { useServiceRestart } from './useServiceRestart'

export function useSystemUpdate() {
  const logger = useLogger('useSystemUpdate')
  const serviceRestart = useServiceRestart()

  // State
  const versionInfo = ref(null)
  const updateInfo = ref(null)
  const updateAvailable = ref(false)
  const checking = ref(false)
  const updating = ref(false)
  const statusMessage = ref(null)
  const statusType = ref(null) // 'success', 'error', 'info'

  const API_BASE_URL = '/api'

  /**
   * Load current version information
   */
  const loadVersionInfo = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/system/version`)
      if (!response.ok) throw new Error('Failed to fetch version info')

      const data = await response.json()
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
   * Check for available updates from origin/main
   */
  const checkForUpdates = async () => {
    checking.value = true
    statusMessage.value = null

    try {
      logger.info('Checking for updates...')
      const response = await fetch(`${API_BASE_URL}/system/update-check`)
      if (!response.ok) throw new Error('Failed to check for updates')

      const data = await response.json()
      updateInfo.value = data
      updateAvailable.value = data.update_available

      if (data.update_available) {
        setStatus('info', `Update available: ${data.commits_behind} new commits`)
        logger.info('Update available', data)
      } else {
        setStatus('success', 'System is up to date')
        logger.info('System is up to date', {
          current: data.current_commit,
          remote: data.remote_commit,
          branch: data.current_branch
        })
      }

      return data
    } catch (error) {
      logger.error('Failed to check for updates', error)
      setStatus('error', 'Failed to check for updates. Check network connection.')
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
      const response = await fetch(`${API_BASE_URL}/system/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.error || 'Update failed')
      }

      const data = await response.json()

      if (data.status === 'no_update_needed') {
        setStatus('info', 'System is already up to date')
        updating.value = false
        return
      }

      setStatus('info', 'Update started. Services restarting...')
      logger.info('Update triggered successfully', data)

      // Use shared service restart monitoring
      await serviceRestart.waitForRestart({
        maxWaitSeconds: 300, // 5 minutes for updates (longer than settings save)
        autoReload: true
      })
    } catch (error) {
      logger.error('Failed to trigger update', error)
      setStatus('error', `Update failed: ${error.message}`)
      updating.value = false
      throw error
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
    // Expose service restart state for UI
    restartMessage: serviceRestart.restartMessage,
    isRestarting: serviceRestart.isRestarting,
    // Methods
    loadVersionInfo,
    checkForUpdates,
    triggerUpdate
  }
}
