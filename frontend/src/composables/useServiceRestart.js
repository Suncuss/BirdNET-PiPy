import { ref } from 'vue'
import api from '@/services/api'
import { useLogger } from './useLogger'

const PROGRESS_INTERVAL_MS = 5000

/**
 * Detect errors that likely mean restart was accepted but HTTP response was cut off.
 */
export function isLikelyRestartInProgressError(error) {
  const status = error?.response?.status
  if (status === 502 || status === 504) return true

  const code = `${error?.code || ''}`.toUpperCase()
  if (code === 'ECONNABORTED' || code === 'ERR_NETWORK') return true

  const message = `${error?.message || ''}`.toLowerCase()
  return (
    message.includes('network error') ||
    message.includes('timeout') ||
    message.includes('upstream prematurely closed connection') ||
    message.includes('status code 502') ||
    message.includes('status code 504')
  )
}

/**
 * True when waitForRestart gave up waiting — the restart is presumed still in
 * progress, so callers should report "slow", not "failed".
 */
export function isRestartTimeoutError(error) {
  return error?.message === 'RESTART_TIMEOUT'
}

/**
 * Post restart request, tolerating connection errors that indicate the restart was accepted.
 */
export async function requestRestart() {
  try {
    await api.post('/system/restart')
  } catch (error) {
    if (!isLikelyRestartInProgressError(error)) {
      throw error
    }
    console.warn('Restart request connection dropped; waiting for reconnection anyway', error)
  }
}

/**
 * Composable for monitoring service restart and reconnection
 * Used after settings changes or system updates that trigger a restart
 */
export function useServiceRestart() {
  const logger = useLogger('useServiceRestart')

  const isRestarting = ref(false)
  const restartMessage = ref('')
  const restartError = ref('')

  // Set while a waitForRestart() is pending; reset() calls it to stop the
  // poll loop and progress timer and settle the promise with false.
  let cancelActiveWait = null

  /**
   * Monitor service reconnection after a restart-triggering action
   * @param {Object} options
   * @param {number} options.maxWaitSeconds - Max time to wait (default: 150s / 2.5 min)
   * @param {number} options.pollInterval - Polling interval in ms (default: 5000)
   * @param {number} options.initialDelay - Delay before first check in ms (default: 10000)
   * @param {number} options.postConnectDelay - Extra delay after connection before reload (default: 15000)
   * @param {boolean} options.autoReload - Whether to reload page on success (default: true)
   * @param {string} options.timeoutMessage - restartError text shown when the wait times out
   * @returns {Promise<boolean>} - Resolves true when service is back, false
   *   when reset() cancelled the wait; rejects on timeout
   */
  const waitForRestart = async (options = {}) => {
    const {
      maxWaitSeconds = 150,
      pollInterval = 5000,
      initialDelay = 10000,
      postConnectDelay = 15000, // Wait for all services (BirdNet, etc.) to fully initialize
      autoReload = true,
      message = 'Services restarting',
      timeoutMessage = 'Restart is taking longer than expected. Try refreshing the page in a minute.'
    } = options

    isRestarting.value = true
    restartMessage.value = `${message}...`
    restartError.value = ''

    const startTime = Date.now()

    return new Promise((resolve, reject) => {
      let progressTimer = null
      let pendingTimer = null
      let cancelled = false
      let lastDisplayedElapsedSec = 0

      const stopProgressTimer = () => {
        if (progressTimer !== null) {
          clearInterval(progressTimer)
          progressTimer = null
        }
      }

      cancelActiveWait = () => {
        cancelled = true
        cancelActiveWait = null
        stopProgressTimer()
        clearTimeout(pendingTimer)
        // Resolve, don't reject: every caller's catch turns unexpected
        // errors into user-facing failure banners, and a reset() usually
        // means the user just dismissed one.
        resolve(false)
      }

      const updateProgressMessage = () => {
        const elapsedIntervals = Math.floor((Date.now() - startTime) / PROGRESS_INTERVAL_MS)
        const elapsedSec = elapsedIntervals * (PROGRESS_INTERVAL_MS / 1000)
        if (elapsedSec <= lastDisplayedElapsedSec) return

        lastDisplayedElapsedSec = elapsedSec
        restartMessage.value = `${message}... (${elapsedSec}s)`
      }

      const checkConnection = async () => {
        const elapsedMs = Date.now() - startTime

        if (elapsedMs >= maxWaitSeconds * 1000) {
          stopProgressTimer()
          cancelActiveWait = null
          logger.warn('Service restart taking longer than expected')
          restartMessage.value = ''
          restartError.value = timeoutMessage
          isRestarting.value = false
          reject(new Error('RESTART_TIMEOUT'))
          return
        }

        try {
          // Reachability probe — detects when the API is back after a
          // restart. Deliberately a raw request: routing it through
          // useSettings would let its coalescing return stale cached data
          // and never detect the reconnect.
          await api.get('/settings')
          if (cancelled) return // reset() fired while the probe was in flight

          // If we get here, the request succeeded
          stopProgressTimer()
          logger.info('API reconnected, waiting for all services to initialize...')
          restartMessage.value = 'Waiting for services to initialize...'

          // Wait extra time for all services (BirdNet inference, etc.) to fully start
          pendingTimer = setTimeout(() => {
            cancelActiveWait = null
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
        } catch (_error) {
          if (cancelled) return
          pendingTimer = setTimeout(checkConnection, pollInterval)
        }
      }

      progressTimer = setInterval(updateProgressMessage, PROGRESS_INTERVAL_MS)

      // Start checking after initial delay (allow time for shutdown)
      pendingTimer = setTimeout(checkConnection, initialDelay)
    })
  }

  /**
   * Reset the restart state, cancelling any in-flight waitForRestart():
   * its timers stop, its promise resolves false, and no later probe
   * completion can resurrect banner messages or trigger the auto-reload.
   */
  const reset = () => {
    if (cancelActiveWait) {
      cancelActiveWait()
    }
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
