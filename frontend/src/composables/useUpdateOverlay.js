/**
 * Boot-time update overlay: explains the outage to anyone who loads (or
 * refreshes) the app while a native update has the backend down.
 *
 * The tab that initiated an update gets the staged banner via
 * waitForRestart; every other tab or fresh visitor would otherwise see a
 * rendered dashboard full of failed requests. Two triggers, both requiring a
 * FRESH stage in /update-progress, so an ordinary outage — or a stage file
 * left behind by a failed update — never gets dressed up as an update in
 * progress:
 *
 * - Boot (checkForUpdateAtBoot, App.vue onMounted): reads the stage file
 *   straight away. nginx serves it statically, so a visitor arriving
 *   mid-update gets the overlay in milliseconds.
 * - Reactive (checkForActiveUpdate, on the api service's 'api:unreachable'
 *   event): for tabs that were already open when the update began. On its
 *   own this path is slow for a fresh visitor — the update REMOVES the api
 *   container, so nginx's connect takes 3s (ARP timeout) to fail, and the
 *   page sits on "Fetching data…" until it does.
 *
 * Module-level singleton state, like useSystemUpdate: one overlay per page,
 * shared by the component and the trigger wiring.
 */
import { ref } from 'vue'
import { managedWaitActive } from './useServiceRestart'
import { fetchUpdateStage, isStageFresh } from '@/utils/updateStage'
import { waitForServicesReady } from '@/utils/serviceReadiness'
import { API_BASE } from '@/services/baseUrl'
import { useLogger } from './useLogger'

// A local image build can sit in its "build" stage for tens of minutes
// without a rewrite, so freshness is generous. install.sh stamps a UTC
// timestamp per stage write exactly for this check.
const STAGE_MAX_AGE_MS = 60 * 60 * 1000
const POLL_INTERVAL_MS = 5000
// The boot check's veto probe must settle before the first poll tick: from
// then on pollWhileUpdating owns the verdict (and its verdict is a reload).
// Not an "is the API down" timeout — an unanswered probe just leaves the
// overlay up for the poll to resolve.
const BOOT_PROBE_TIMEOUT_MS = 4000

const visible = ref(false)
const stageMessage = ref('')
const reloading = ref(false)
// What the backend is still starting once it is back online ('' when unknown)
const readinessMessage = ref('')

let checkInFlight = false
// Set when a real API failure arrives while a check is in flight or the
// overlay is already up. The reactive path is a no-op then, so without this
// the boot probe's dismissal would swallow it (see checkForUpdateAtBoot).
let apiFailedDuringCheck = false
let pollTimer = null
let readinessAbort = null

const logger = useLogger('useUpdateOverlay')

/**
 * Show the overlay if a fresh update stage proves an update is actually
 * running. Resolves to whether it activated. Activation happens inside the
 * in-flight window so overlapping callers can't start a second poll.
 */
async function activateOnFreshStage({ ignoreFailed = false } = {}) {
  if (visible.value || checkInFlight || managedWaitActive.value) return false
  checkInFlight = true
  try {
    const stage = await fetchUpdateStage()
    if (!stage || !isStageFresh(stage.timestamp, STAGE_MAX_AGE_MS)) return false
    if (ignoreFailed && stage.stage === 'failed') return false
    // A managed wait may have started while the fetch was in flight
    if (managedWaitActive.value) return false
    logger.info('Update in progress detected, showing overlay', stage)
    stageMessage.value = stage.message
    visible.value = true
    pollTimer = setInterval(pollWhileUpdating, POLL_INTERVAL_MS)
    return true
  } finally {
    checkInFlight = false
  }
}

/**
 * Called on every 'api:unreachable' event. Cheap no-op unless a fresh
 * update stage proves an update is actually running.
 */
async function checkForActiveUpdate() {
  if (visible.value || checkInFlight) apiFailedDuringCheck = true
  await activateOnFreshStage()
}

/**
 * Called once at app boot. No failed API call backs this path up, so the
 * stage file alone has to be trustworthy:
 * - a 'failed' stage is skipped — it lingers (fresh for up to an hour) on a
 *   healthy station after a failed update, and would flash the overlay on
 *   every page load. The reactive path still covers the real failure window.
 * - one API probe can veto: the stage is also briefly fresh while the API is
 *   up (the "stopping" seconds before the stack goes down, the tail of a
 *   same-commit update). The veto DISMISSES rather than reloads — this page
 *   just loaded, and a reload would find the same stage and loop. It is
 *   void if a page request failed with the API unreachable while the check
 *   ran: then the poll's reload is the recovery.
 */
async function checkForUpdateAtBoot() {
  apiFailedDuringCheck = false
  if (!await activateOnFreshStage({ ignoreFailed: true })) return
  const reachable = await isApiReachable(BOOT_PROBE_TIMEOUT_MS)
  // A page request that failed meanwhile outranks the probe: dismissing would
  // cancel the poll and leave that view broken. The poll reloads instead.
  if (reachable && !reloading.value && !apiFailedDuringCheck) {
    logger.info('API reachable, dismissing the boot-time overlay')
    deactivateUpdateOverlay()
  }
}

// Raw fetch: same-origin, and no 'api:unreachable' event. Any answer from the
// API counts, including a 401 — /system/version is login-walled on a station
// with public access off, and a signed-out visitor must not read that as an
// outage (the overlay would never lift and would cover the login dialog).
// Only nginx's dead-upstream statuses mean the API is down.
const UPSTREAM_DOWN_STATUSES = new Set([502, 503, 504])

async function isApiReachable(timeoutMs) {
  const controller = new AbortController()
  const abortTimer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null
  try {
    const response = await fetch(`${API_BASE}/system/version`, {
      cache: 'no-store',
      signal: controller.signal
    })
    return !UPSTREAM_DOWN_STATUSES.has(response.status)
  } catch (_error) {
    return false
  } finally {
    clearTimeout(abortTimer)
  }
}

async function pollWhileUpdating() {
  // Keep the displayed stage current; a vanished file mid-update (final
  // restart window) just leaves the last stage showing.
  const stage = await fetchUpdateStage()
  if (stage) stageMessage.value = stage.message

  // The update is over when the API answers again — on the new version, or
  // on the old one after a failed update. Either way the page reloads into
  // whatever is actually serving, once its services are up.
  if (!await isApiReachable()) return
  // An overlapping tick (a slow probe) already got here
  if (reloading.value || !visible.value) return
  logger.info('API reachable again, waiting for services before reloading')
  clearInterval(pollTimer)
  pollTimer = null
  reloading.value = true
  readinessAbort = new AbortController()
  const proceed = await waitForServicesReady({
    signal: readinessAbort.signal,
    onProgress: (text) => { readinessMessage.value = text }
  })
  if (!proceed) return
  readinessAbort = null
  window.location.reload()
}

/** Hide the overlay and stop all polling (also used by tests). */
function deactivateUpdateOverlay() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (readinessAbort) {
    readinessAbort.abort()
    readinessAbort = null
  }
  apiFailedDuringCheck = false
  visible.value = false
  reloading.value = false
  stageMessage.value = ''
  readinessMessage.value = ''
}

export function useUpdateOverlay() {
  return {
    visible,
    stageMessage,
    reloading,
    readinessMessage,
    checkForActiveUpdate,
    checkForUpdateAtBoot,
    deactivateUpdateOverlay
  }
}
