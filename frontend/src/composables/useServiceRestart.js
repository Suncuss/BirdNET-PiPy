import { ref } from 'vue'
import api from '@/services/api'
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
   * @param {number} options.postConnectDelay - Extra delay after connection before reload (default: 15000)
   * @param {boolean} options.autoReload - Whether to reload page on success (default: true)
   * @returns {Promise<boolean>} - Resolves true when service is back, rejects on timeout
   */
  const waitForRestart = async (options = {}) => {
    const {
      maxWaitSeconds = 150,
      pollInterval = 5000,
      initialDelay = 10000,
      postConnectDelay = 15000, // Wait for all services (BirdNet, etc.) to fully initialize
      autoReload = true,
      message = 'Services restarting'
    } = options

    isRestarting.value = true
    restartMessage.value = `${message}...`
    restartError.value = ''

    const maxAttempts = Math.floor(maxWaitSeconds / (pollInterval / 1000))

    return new Promise((resolve, reject) => {
      let attempts = 0

      const checkConnection = async () => {
        attempts++

        try {
          // Axios doesn't use browser cache by default
          await api.get('/settings')

          // If we get here, the request succeeded
          logger.info('API reconnected, waiting for all services to initialize...')
          restartMessage.value = 'Waiting for services to initialize...'

          // Wait extra time for all services (BirdNet inference, etc.) to fully start
          setTimeout(() => {
            logger.info('Service restart complete')
            restartMessage.value = 'Services ready!'

            if (autoReload) {
              restartMessage.value = 'Reloading...'
              setTimeout(() => {
                window.location.reload()
              }, 1000)
            }

            isRestarting.value = false
            resolve(true)
          }, postConnectDelay)
        } catch (error) {
          if (attempts >= maxAttempts) {
            logger.warn('Service restart taking longer than expected')
            restartMessage.value = ''
            restartError.value = 'Update taking longer than expected. Try refreshing later.'
            isRestarting.value = false
            reject(new Error('RESTART_TIMEOUT'))
          } else {
            // Update message periodically
            const elapsed = Math.floor((attempts * pollInterval) / 1000)
            if (attempts % 4 === 0) {
              restartMessage.value = `${message}... (${elapsed}s)`
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
