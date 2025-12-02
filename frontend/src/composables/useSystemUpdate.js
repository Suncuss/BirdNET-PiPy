import { ref } from 'vue'
import { useLogger } from './useLogger'

export function useSystemUpdate() {
  const logger = useLogger('useSystemUpdate')

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

      // Log detailed update check results
      console.log('=== Update Check Results ===')
      console.log('Current commit:', data.current_commit)
      console.log('Remote commit:', data.remote_commit)
      console.log('Current branch:', data.current_branch)
      console.log('Target branch:', data.target_branch)
      console.log('Commits behind:', data.commits_behind)
      console.log('Update available:', data.update_available)
      console.log('Preview commits:', data.preview_commits)
      console.log('============================')

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
   * Trigger system update with user confirmation
   */
  const triggerUpdate = async () => {
    // Confirmation dialog
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

      // Start monitoring for reconnection
      monitorReconnection()
    } catch (error) {
      logger.error('Failed to trigger update', error)
      setStatus('error', `Update failed: ${error.message}`)
      updating.value = false
      throw error
    }
  }

  /**
   * Monitor service reconnection after update
   */
  const monitorReconnection = () => {
    let attempts = 0
    const maxAttempts = 60 // 5 minutes (5s interval)

    const checkConnection = async () => {
      attempts++

      try {
        const response = await fetch(`${API_BASE_URL}/system/version`, {
          method: 'GET',
          cache: 'no-cache',
          headers: { 'Cache-Control': 'no-cache' }
        })

        if (response.ok) {
          logger.info('Service reconnected after update')
          setStatus('success', 'Update complete! Reloading page...')

          // Reload page after short delay
          setTimeout(() => {
            window.location.reload()
          }, 2000)
        } else {
          throw new Error('Service not ready')
        }
      } catch (error) {
        // Service still down
        if (attempts >= maxAttempts) {
          logger.error('Update timeout - service did not reconnect')
          setStatus(
            'error',
            'Update may have failed. Service did not restart. Please check manually.'
          )
          updating.value = false
        } else {
          // Update status message every 6 attempts (30 seconds)
          if (attempts % 6 === 0) {
            const elapsed = Math.floor(attempts * 5 / 60)
            setStatus('info', `Update in progress... (${elapsed} min)`)
          }

          // Try again in 5 seconds
          setTimeout(checkConnection, 5000)
        }
      }
    }

    // Start checking after 10 seconds (allow time for shutdown)
    setTimeout(checkConnection, 10000)
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
    // Methods
    loadVersionInfo,
    checkForUpdates,
    triggerUpdate
  }
}
