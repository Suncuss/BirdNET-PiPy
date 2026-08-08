import { ref } from 'vue'
import api from '@/services/api'
import { fetchUpdateStage } from '@/utils/updateStage'
import { useLogger } from './useLogger'

const STAGE_POLL_INTERVAL_MS = 5000

// True while any waitForRestart() is pending, across instances. The
// boot-time update overlay (useUpdateOverlay) checks this so the tab that
// initiated a restart/update — whose banner already owns the UX — never
// also gets the overlay when its identity probes fail mid-wait.
export const managedWaitActive = ref(false)

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
 * True when waitForRestart detected a failed update: the host restarted the
 * previous version and marked the run failed via the update-status flag.
 */
export function isUpdateFailedError(error) {
  return error?.message === 'UPDATE_FAILED'
}

/**
 * Post restart request, tolerating connection errors that indicate the restart was accepted.
 *
 * Returns {bootId} when the response carries one: the responding process IS
 * the old server, so its boot_id doubles as a late identity baseline for
 * waitForRestart when the earlier captureRestartBaseline() failed. Returns
 * null when no identity is available (connection cut, older backend).
 */
export async function requestRestart() {
  try {
    const response = await api.post('/system/restart')
    const bootId = response?.data?.boot_id
    return bootId ? { bootId } : null
  } catch (error) {
    if (!isLikelyRestartInProgressError(error)) {
      throw error
    }
    console.warn('Restart request connection dropped; waiting for reconnection anyway', error)
    return null
  }
}

/**
 * The backend uses the literal string 'unknown' as a placeholder when
 * version metadata is missing (e.g. HA without BUILD_VERSION); a sentinel
 * can never prove identity or advancement, so treat it as absent.
 */
export function identityValue(value) {
  return value && value !== 'unknown' ? value : undefined
}

/**
 * Snapshot the running server's identity BEFORE triggering a restart/update.
 *
 * waitForRestart() compares later probes against this, so the old server
 * answering during a slow shutdown can never be mistaken for the new one
 * (on slow hardware the stack can take far longer than any fixed delay to
 * go down). Returns null when the identity can't be captured; the wait then
 * falls back to down-then-up detection.
 */
export async function captureRestartBaseline() {
  try {
    const response = await api.get('/system/version')
    const data = response?.data
    if (!data) return null
    return {
      bootId: data.boot_id,
      commit: identityValue(data.current_commit),
      version: identityValue(data.version),
      runtimeMode: data.runtime_mode,
      updateStatus: data.update_status
    }
  } catch (_error) {
    return null
  }
}

// True when the baseline carries the identity field(s) the expectation needs;
// otherwise the wait falls back to down-then-up detection. A bootId-only
// baseline (from a trigger response) suffices for updates too: completion
// then rides on the explicit success status + new boot_id clause.
function hasIdentity(expectation, baseline) {
  if (!baseline) return false
  if (expectation === 'update') {
    return Boolean(baseline.commit || baseline.version || baseline.bootId)
  }
  return Boolean(baseline.bootId)
}

// True when a probe response proves the expected transition happened.
function identityAdvanced(expectation, baseline, data) {
  if (!data) return false
  const bootChanged = Boolean(baseline?.bootId && data.boot_id && data.boot_id !== baseline.bootId)
  if (expectation !== 'update') return bootChanged

  const codeChanged = Boolean(
    (baseline?.commit && identityValue(data.current_commit) &&
      data.current_commit !== baseline.commit) ||
    (baseline?.version && identityValue(data.version) &&
      data.version !== baseline.version)
  )

  // bootId-only baseline (from a trigger response): a new process plus a
  // non-failure status — or no status system at all (the HA add-on never
  // writes one) — is the only completion proof available.
  if (baseline?.bootId && !baseline.commit && !baseline.version) {
    return bootChanged && (data.update_status === 'success' || data.update_status == null)
  }

  // A commit/version change alone can be the OLD process serving a
  // version.json refreshed mid-update (compose down is best-effort and the
  // file is read live per request), so when the baseline carries a boot id,
  // demand process proof: a new boot_id, or none at all — the baselined
  // process demonstrably served one, so a response without it is a
  // different, older-code server (supported latest->release downgrade).
  const processProof = baseline?.bootId ? (bootChanged || !data.boot_id) : true
  // Second clause: install.sh rebuilt/restarted without a commit or version
  // change (e.g. stale-version.json repair) and reported explicit success.
  return (codeChanged && processProof) || (data.update_status === 'success' && bootChanged)
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
   * Monitor service reconnection after a restart-triggering action.
   *
   * Probes /system/version and, when a baseline is provided, completes only
   * once the response's identity differs from it — 'restart' waits for a new
   * boot_id, 'update' for a new commit/version (or an explicit success
   * status). A reachable server with an unchanged identity just means the
   * transition hasn't happened yet. Without a usable baseline it falls back
   * to requiring at least one failed probe before accepting a success.
   *
   * @param {Object} options
   * @param {'restart'|'update'} options.expect - Which transition proves
   *   completion. Identity semantics only: wait length is maxWaitSeconds and
   *   banner staging is progressUrl. Default 'restart'
   * @param {Object|null} options.baseline - Identity from captureRestartBaseline() taken before the trigger
   * @param {number} options.maxWaitSeconds - Max time to wait (default: 150s / 2.5 min)
   * @param {number} options.pollInterval - Polling interval in ms (default: 5000)
   * @param {number} options.initialDelay - Delay before first check in ms (default: 10000)
   * @param {number} options.postConnectDelay - Extra delay after connection before reload (default: 15000)
   * @param {boolean} options.autoReload - Whether to reload page on success (default: true)
   * @param {string} options.message - Progress banner subject, no trailing
   *   punctuation: this appends '...'. Unlike timeoutMessage/failureMessage,
   *   which are used verbatim
   * @param {string} options.timeoutMessage - restartError text shown when the wait times out
   * @param {string} options.failureMessage - restartError text shown when the update failed
   * @param {string|null} options.progressUrl - Same-origin URL of the host's
   *   update-stage file (native updates pass '/update-progress', served
   *   statically by the nginx container that stays up through the update).
   *   When set, a poll fetches it every 5s and each fresh stage message
   *   replaces the generic subject in the banner. Any fetch/parse failure —
   *   endpoint absent (HA, older stack), server down, malformed body — is
   *   silently ignored and the last message stays.
   * @returns {Promise<boolean>} - Resolves true when service is back, false
   *   when reset() cancelled the wait; rejects on timeout (RESTART_TIMEOUT)
   *   or a detected failed update (UPDATE_FAILED)
   */
  const waitForRestart = async (options = {}) => {
    // Only one wait can be active per instance: starting a new one cancels
    // any predecessor (its promise resolves false), so a stale wait can
    // never fire a surprise reload after being superseded.
    if (cancelActiveWait) {
      cancelActiveWait()
    }

    const {
      expect: expectation = 'restart',
      baseline = null,
      maxWaitSeconds = 150,
      pollInterval = 5000,
      initialDelay = 10000,
      postConnectDelay = 15000, // Wait for all services (BirdNet, etc.) to fully initialize
      autoReload = true,
      message = 'Services restarting',
      timeoutMessage = 'Restart is taking longer than expected. Try refreshing the page in a minute.',
      failureMessage = 'Update failed — the system is still on the previous version. Check the system logs for details.',
      progressUrl = null
    } = options

    isRestarting.value = true
    managedWaitActive.value = true
    restartMessage.value = `${message}...`
    restartError.value = ''

    const startTime = Date.now()
    const identityMode = hasIdentity(expectation, baseline)
    // Fallback only: a success may be accepted once an outage was observed.
    let sawOutage = false
    // A 'failed' status is terminal only if it appeared during THIS attempt.
    // Evidence: a literal non-failed status at baseline (normally the
    // dispatch's verified 'pending' read-back), or a probe witnessing a
    // non-failed phase mid-wait. null/undefined mean the reset outcome is
    // unknown — a stale 'failed' could have survived — so no evidence.
    let sawNonFailedStatus =
      baseline?.updateStatus != null && baseline.updateStatus !== 'failed'

    return new Promise((resolve, reject) => {
      let stagePollTimer = null
      let pendingTimer = null
      let cancelled = false

      // Nulling the handle is what makes it the liveness flag read below.
      const stopStagePolling = () => {
        clearInterval(stagePollTimer)
        stagePollTimer = null
      }

      cancelActiveWait = () => {
        cancelled = true
        cancelActiveWait = null
        stopStagePolling()
        clearTimeout(pendingTimer)
        managedWaitActive.value = false
        // Resolve, don't reject: every caller's catch turns unexpected
        // errors into user-facing failure banners, and a reset() usually
        // means the user just dismissed one.
        resolve(false)
      }

      const settleWithError = (errorCode, bannerText) => {
        stopStagePolling()
        cancelActiveWait = null
        restartMessage.value = ''
        restartError.value = bannerText
        isRestarting.value = false
        managedWaitActive.value = false
        reject(new Error(errorCode))
      }

      let stageFetchPending = false

      const pollStageMessage = () => {
        // The pending guard keeps an endpoint that hangs (rather than
        // failing fast) from stacking a request per tick over a long wait.
        if (stageFetchPending) return
        stageFetchPending = true
        fetchUpdateStage(progressUrl)
          .then(stage => {
            // Still-polling check: the fetch is async, so a response landing
            // after the wait settled would clobber 'Services ready!'.
            if (stage && stagePollTimer !== null) {
              restartMessage.value = `${stage.message}...`
            }
          })
          .finally(() => { stageFetchPending = false })
      }

      const checkConnection = async () => {
        const elapsedMs = Date.now() - startTime

        if (elapsedMs >= maxWaitSeconds * 1000) {
          logger.warn('Service restart taking longer than expected')
          settleWithError('RESTART_TIMEOUT', timeoutMessage)
          return
        }

        try {
          // Identity probe — deliberately a raw request so nothing cached
          // can mask the reconnect, and against /system/version because its
          // boot_id/commit prove WHICH server instance answered.
          const response = await api.get('/system/version')
          if (cancelled) return // reset() fired while the probe was in flight

          const payload = response?.data || {}
          // Mirror the baseline-init rule: only a literal non-failed status
          // is evidence. null/undefined (file absent mid-rewrite, transient
          // read error, old backend, HA) proves nothing, so it must not
          // upgrade a later stale 'failed' into a current-attempt failure.
          if (payload.update_status != null && payload.update_status !== 'failed') {
            sawNonFailedStatus = true
          }

          // The host marked this attempt failed (evidence: see the
          // sawNonFailedStatus init — without it, a stale file that
          // survived an unverified reset could false-fail a successful
          // retry). Terminal even if the commit/version advanced:
          // version.json is refreshed before the post-build configuration
          // steps, so metadata can be ahead of what actually runs when a
          // late step fails.
          if (
            expectation === 'update' &&
            payload.update_status === 'failed' &&
            sawNonFailedStatus
          ) {
            logger.error('Update failed on host; previous version restarted')
            settleWithError('UPDATE_FAILED', failureMessage)
            return
          }

          const advanced = identityAdvanced(expectation, baseline, payload)

          const reconnected = identityMode ? advanced : sawOutage
          if (!reconnected) {
            // Reachable, but still the old instance (or no outage observed
            // yet in fallback mode): the transition hasn't happened. This is
            // the case the old reachability-only probe got wrong on slow
            // hardware, reloading into a server about to go down.
            pendingTimer = setTimeout(checkConnection, pollInterval)
            return
          }

          stopStagePolling()
          logger.info('API reconnected, waiting for all services to initialize...')
          restartMessage.value = 'Waiting for services to initialize...'

          // Wait extra time for all services (BirdNet inference, etc.) to fully start
          pendingTimer = setTimeout(() => {
            cancelActiveWait = null
            managedWaitActive.value = false
            logger.info('Service restart complete')
            restartMessage.value = 'Services ready!'

            if (autoReload) {
              // Keep isRestarting true: the page is about to be replaced,
              // and clearing it early lets the banner chain fall through to
              // "update available" for the last second before the reload.
              restartMessage.value = 'Reloading...'
              setTimeout(() => {
                window.location.reload()
              }, 1000)
            } else {
              isRestarting.value = false
            }
            resolve(true)
          }, postConnectDelay)
        } catch (_error) {
          if (cancelled) return
          sawOutage = true
          pendingTimer = setTimeout(checkConnection, pollInterval)
        }
      }

      // The banner repaints only when the host reports a new stage — no
      // elapsed counter, because a ticking number made a normal wait read as
      // something going wrong and the spinner beside it already carries
      // "still working".
      if (progressUrl) {
        // Interval first, so the primed call's guard is already armed when
        // its fetch resolves. Primed at all so a real stage replaces the
        // generic subject as soon as the host has one, not a tick later.
        stagePollTimer = setInterval(pollStageMessage, STAGE_POLL_INTERVAL_MS)
        pollStageMessage()
      }

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
