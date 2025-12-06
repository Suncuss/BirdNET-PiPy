import { ref } from 'vue'
import { useLogger } from './useLogger'

/**
 * Composable for monitoring service restart and reconnection
 * Used after settings changes or system updates that trigger a restart
 */
export function useServiceRestart() {
  const logger = useLogger('useServiceRestart')

  const isRestarting = ref(false)
  const restartMessage = ref('')
  const restartError = ref('')

  /**
   * Monitor service reconnection after a restart-triggering action
   * @param {Object} options
   * @param {number} options.maxWaitSeconds - Max time to wait (default: 150s / 2.5 min)
   * @param {number} options.pollInterval - Polling interval in ms (default: 5000)
   * @param {number} options.initialDelay - Delay before first check in ms (default: 10000)
   * @param {boolean} options.autoReload - Whether to reload page on success (default: true)
   * @returns {Promise<boolean>} - Resolves true when service is back, rejects on timeout
   */
  const waitForRestart = async (options = {}) => {
    const {
      maxWaitSeconds = 150,
      pollInterval = 5000,
      initialDelay = 10000,
      autoReload = true
    } = options

    isRestarting.value = true
    restartMessage.value = 'Services restarting...'
    restartError.value = ''

    const maxAttempts = Math.floor(maxWaitSeconds / (pollInterval / 1000))

    return new Promise((resolve, reject) => {
      let attempts = 0

      const checkConnection = async () => {
        attempts++

        try {
          const response = await fetch('/api/settings', {
            method: 'GET',
            cache: 'no-cache',
            headers: { 'Cache-Control': 'no-cache' }
          })

          if (response.ok) {
            logger.info('Service reconnected after restart')
            restartMessage.value = 'Services ready!'

            if (autoReload) {
              restartMessage.value = 'Services ready! Reloading...'
              setTimeout(() => {
                window.location.reload()
              }, 1000)
            }

            isRestarting.value = false
            resolve(true)
          } else {
            throw new Error('Service not ready')
          }
        } catch (error) {
          if (attempts >= maxAttempts) {
            logger.error('Service restart timeout')
            restartMessage.value = ''
            restartError.value = 'Service restart timed out. Please refresh the page manually.'
            isRestarting.value = false
            reject(new Error('Timeout waiting for service restart'))
          } else {
            // Update message periodically
            const elapsed = Math.floor((attempts * pollInterval) / 1000)
            if (attempts % 4 === 0) {
              restartMessage.value = `Services restarting... (${elapsed}s)`
            }
            setTimeout(checkConnection, pollInterval)
          }
        }
      }

      // Start checking after initial delay (allow time for shutdown)
      setTimeout(checkConnection, initialDelay)
    })
  }

  /**
   * Reset the restart state
   */
  const reset = () => {
    isRestarting.value = false
    restartMessage.value = ''
    restartError.value = ''
  }

  return {
    isRestarting,
    restartMessage,
    restartError,
    waitForRestart,
    reset
  }
}
