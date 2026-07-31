import { ref, computed } from 'vue'
import api, { createLongRequest } from '@/services/api'
import { UPDATE_DISMISSED_UNTIL_KEY } from '@/utils/storageKeys'
import { useLogger } from './useLogger'
import {
  captureRestartBaseline,
  identityValue,
  isRestartTimeoutError,
  isUpdateFailedError,
  useServiceRestart
} from './useServiceRestart'
import { useAuth } from './useAuth'
import { useDismissible } from './useDismissible'

// Module-level state (shared across all components - singleton)
const versionInfo = ref(null)
const updateInfo = ref(null)
const updateAvailable = ref(false)
const checking = ref(false)
const updating = ref(false)
const statusMessage = ref(null)
const statusType = ref(null) // 'success', 'error', 'info'

// Update banner is snoozable for 7 days.
const dismissal = useDismissible(UPDATE_DISMISSED_UNTIL_KEY, 7 * 24 * 60 * 60 * 1000)

// Module-level like the state above: an update wait can outlive the Settings
// page (navigating away unmounts it), and a per-mount instance would orphan
// the in-flight wait's banner refs and cancellation handle on remount.
// Created lazily so importing this module has no side effects.
let serviceRestartSingleton = null
function getServiceRestart() {
  if (!serviceRestartSingleton) {
    serviceRestartSingleton = useServiceRestart()
  }
  return serviceRestartSingleton
}

// Native updates can legitimately take a long time on slow hardware (a local
// image build on a Pi Zero 2W exceeds the old 10-minute cap); the identity
// poll makes a long wait safe because it can't false-positive on the old
// server. HA add-on installs are pulls, so keep the shorter cap there.
const UPDATE_MAX_WAIT_SECONDS = 1800
const HA_UPDATE_MAX_WAIT_SECONDS = 600

// How long to wait for the HA dispatch response to supply a late identity
// baseline when no other identity is available. The backend can spend ~15s
// polling the update entity plus ~10s dispatching before its 200 arrives.
const HA_DISPATCH_BASELINE_WAIT_MS = 30_000

// Identity from the versionInfo cache (loaded alongside the update UI),
// for when the live pre-trigger capture fails: commit/version comparison
// works without a boot id, and never delays the monitor. Sentinel-filtered:
// 'unknown' placeholders can't prove advancement, and returning null here
// correctly falls through to the dispatch boot_id instead.
function cachedIdentityBaseline() {
  const commit = identityValue(versionInfo.value?.current_commit)
  const version = identityValue(versionInfo.value?.version)
  if (!commit && !version) return null
  return { commit, version }
}

export function useSystemUpdate() {
  const logger = useLogger('useSystemUpdate')
  const serviceRestart = getServiceRestart()

  const { isAuthenticated } = useAuth()

  // Computed: should show indicator (update available AND not dismissed AND user can act on it)
  const showUpdateIndicator = computed(() => {
    if (!updateAvailable.value) return false
    if (!isAuthenticated.value) return false
    return !dismissal.isDismissed()
  })

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

    // Identity snapshot of the OLD server, taken before anything restarts:
    // the wait engine compares probes against it, so the old server still
    // answering during a slow shutdown can't be mistaken for the new one.
    const baseline = await captureRestartBaseline()
    const runtimeMode = baseline?.runtimeMode || versionInfo.value?.runtime_mode

    if (runtimeMode === 'ha') {
      await triggerHaUpdate(baseline)
      return
    }

    try {
      logger.info('Triggering system update...')
      const longApi = createLongRequest()
      const { data } = await longApi.post('/system/update')

      if (data.status === 'no_update_needed') {
        setStatus('info', 'System is already up to date')
        updating.value = false
        return
      }

      setStatus('info', 'Update started. Services restarting...')
      logger.info('Update triggered successfully', data)

      // Strengthen the baseline with what the trigger response knows: the
      // responder is the OLD process, so its boot_id fills in for a failed
      // capture (cached versionInfo supplies commit/version), and
      // update_status is the server's read-back after clearing any stale
      // value — so a later 'failed' is attributable to this attempt.
      const base = baseline || cachedIdentityBaseline()
      let effectiveBaseline = base
      if (base || data.boot_id) {
        effectiveBaseline = {
          ...(base || {}),
          bootId: base?.bootId || data.boot_id,
          ...(data.update_status !== undefined && { updateStatus: data.update_status })
        }
      }

      const completed = await serviceRestart.waitForRestart({
        expect: 'update',
        baseline: effectiveBaseline,
        maxWaitSeconds: UPDATE_MAX_WAIT_SECONDS,
        autoReload: true,
        message: 'System updating',
        timeoutMessage: 'Update taking longer than expected. Try refreshing later.',
        // Native only — the HA path has no stage file (see the JSDoc)
        progressUrl: '/update-progress'
      })
      if (!completed) {
        updating.value = false // cancelled via reset()
      }
    } catch (error) {
      updating.value = false
      // Timeout is not a failure - just taking longer than expected
      if (isRestartTimeoutError(error)) {
        logger.warn('Update restart timeout - may still be in progress')
        setStatus('info', 'Update taking longer than expected. Try refreshing later.')
      } else if (isUpdateFailedError(error)) {
        logger.error('Update failed on host; previous version restarted')
        setStatus('error', 'Update failed — the system is still on the previous version. Check the system logs for details.')
      } else {
        logger.error('Failed to trigger update', error)
        const backendError = error.response?.data?.error
        setStatus('error', `Update failed: ${backendError || error.message}`)
        throw error
      }
    }
  }

  // Supervisor kills our process mid-install, so we can't await the dispatch
  // response. Fire it, let the shared wait engine poll the server identity,
  // and surface only real dispatch failures (backend 502 payloads) as errors.
  async function triggerHaUpdate(baseline) {
    const longApi = createLongRequest()

    logger.info('Triggering HA addon update...', { baseline })
    let dispatchFailed = false
    const dispatch = longApi.post('/system/update')
    dispatch.catch(err => {
      // Backend returns 502 with {error: "..."} for known dispatch failures
      // (slug lookup, entity not ready, HTTP error from HA Core). Surface
      // those; for raw connection drops (Supervisor killed us), keep waiting.
      const backendError = err.response?.data?.error
      if (backendError) {
        logger.error('HA update dispatch failed', err)
        dispatchFailed = true
        serviceRestart.reset() // cancels the in-flight wait (resolves false)
        updating.value = false
        setStatus('error', `Update failed: ${backendError}`)
      } else {
        logger.warn('HA update dispatch connection lost (identity poll detects completion)', err)
      }
    })

    // Prefer commit/version identity from the cache over waiting on the
    // dispatch: a fast container swap can finish before any dispatch
    // response arrives, and a version comparison also refuses to call a
    // failed update (old image restarted, new boot, no status file) done.
    let effectiveBaseline = baseline || cachedIdentityBaseline()
    if (effectiveBaseline && !effectiveBaseline.bootId) {
      // Without process identity the wait engine waives its process proof,
      // so a stale cache (add-on already updated from another tab or the HA
      // UI) would look "advanced" on the very first probe. The dispatch
      // responder is the old process: graft its boot_id onto the baseline
      // whenever the response arrives — the engine reads the baseline per
      // probe — without delaying the monitor on it.
      const enrichable = effectiveBaseline
      dispatch
        .then(response => {
          const bootId = response?.data?.boot_id
          if (bootId && !enrichable.bootId) {
            enrichable.bootId = bootId
          }
        })
        .catch(() => {})
    }
    if (!effectiveBaseline) {
      // Nothing cached either: give the dispatch response a window to
      // supply the old process's boot_id as a late baseline (the 200
      // usually arrives before Supervisor swaps the container out).
      effectiveBaseline = await Promise.race([
        dispatch
          .then(response => {
            const bootId = response?.data?.boot_id
            return bootId ? { bootId } : null
          })
          .catch(() => null),
        new Promise(resolve => setTimeout(() => resolve(null), HA_DISPATCH_BASELINE_WAIT_MS))
      ])
      if (dispatchFailed) {
        // The error handler above already surfaced it; don't start a wait.
        return
      }
    }

    try {
      const completed = await serviceRestart.waitForRestart({
        expect: 'update',
        baseline: effectiveBaseline,
        maxWaitSeconds: HA_UPDATE_MAX_WAIT_SECONDS,
        autoReload: true,
        message: 'Updating via Home Assistant',
        timeoutMessage: 'Update is taking longer than expected. Refresh the page manually if needed.',
        failureMessage: 'Update failed — the add-on is still on the previous version. Check the add-on logs.'
      })
      if (!completed) {
        updating.value = false // cancelled (e.g. dispatch error path above)
      }
    } catch (error) {
      updating.value = false
      if (isRestartTimeoutError(error)) {
        setStatus('info', 'Update is taking longer than expected. Refresh the page manually if needed.')
      } else if (isUpdateFailedError(error)) {
        setStatus('error', 'Update failed — the add-on is still on the previous version. Check the add-on logs.')
      } else {
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
    dismissUpdate: dismissal.dismiss,
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
