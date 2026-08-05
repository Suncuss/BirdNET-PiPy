/**
 * Boot-time update overlay: explains the outage to anyone who loads (or
 * refreshes) the app while a native update has the backend down.
 *
 * The tab that initiated an update gets the staged banner via
 * waitForRestart; every other tab or fresh visitor would otherwise see a
 * rendered dashboard full of failed requests. The api service dispatches
 * 'api:unreachable' on backend-down errors (App.vue wires it to
 * checkForActiveUpdate here); activation then requires a FRESH stage in
 * /update-progress, so an ordinary outage — or a stage file left behind by
 * a failed update — never gets dressed up as an update in progress.
 *
 * Module-level singleton state, like useSystemUpdate: one overlay per page,
 * shared by the component and the trigger wiring.
 */
import { ref } from 'vue'
import { managedWaitActive } from './useServiceRestart'
import { fetchUpdateStage, isStageFresh } from '@/utils/updateStage'
import { API_BASE } from '@/services/baseUrl'
import { useLogger } from './useLogger'

// A local image build can sit in its "build" stage for tens of minutes
// without a rewrite, so freshness is generous. install.sh stamps a UTC
// timestamp per stage write exactly for this check.
const STAGE_MAX_AGE_MS = 60 * 60 * 1000
const POLL_INTERVAL_MS = 5000
// Grace after the API answers again before reloading into the new frontend.
const RELOAD_SETTLE_MS = 3000

const visible = ref(false)
const stageMessage = ref('')
const reloading = ref(false)

let checkInFlight = false
let pollTimer = null
let reloadTimer = null

const logger = useLogger('useUpdateOverlay')

/**
 * Called on every 'api:unreachable' event. Cheap no-op unless a fresh
 * update stage proves an update is actually running.
 */
async function checkForActiveUpdate() {
  if (visible.value || checkInFlight || managedWaitActive.value) return
  checkInFlight = true
  try {
    const stage = await fetchUpdateStage()
    if (!stage || !isStageFresh(stage.timestamp, STAGE_MAX_AGE_MS)) return
    // A managed wait may have started while the fetch was in flight
    if (managedWaitActive.value) return
    logger.info('Update in progress detected, showing overlay', stage)
    stageMessage.value = stage.message
    visible.value = true
    pollTimer = setInterval(pollWhileUpdating, POLL_INTERVAL_MS)
  } finally {
    checkInFlight = false
  }
}

async function pollWhileUpdating() {
  // Keep the displayed stage current; a vanished file mid-update (final
  // restart window) just leaves the last stage showing.
  const stage = await fetchUpdateStage()
  if (stage) stageMessage.value = stage.message

  // The update is over when the API answers again — on the new version, or
  // on the old one after a failed update. Either way the page reloads into
  // whatever is actually serving. Raw fetch: same-origin, no auth needed.
  try {
    const response = await fetch(`${API_BASE}/system/version`, { cache: 'no-store' })
    if (!response.ok) return
  } catch (_error) {
    return
  }
  logger.info('API reachable again, reloading')
  clearInterval(pollTimer)
  pollTimer = null
  reloading.value = true
  reloadTimer = setTimeout(() => {
    window.location.reload()
  }, RELOAD_SETTLE_MS)
}

/** Hide the overlay and stop all polling (also used by tests). */
function deactivateUpdateOverlay() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (reloadTimer) {
    clearTimeout(reloadTimer)
    reloadTimer = null
  }
  visible.value = false
  reloading.value = false
  stageMessage.value = ''
}

export function useUpdateOverlay() {
  return {
    visible,
    stageMessage,
    reloading,
    checkForActiveUpdate,
    deactivateUpdateOverlay
  }
}
