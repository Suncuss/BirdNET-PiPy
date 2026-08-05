/**
 * Shared reader for the host's update-progress stage file, written by
 * install.sh during a native update and served statically by the nginx
 * container that stays up through it (see frontend/nginx.conf).
 *
 * Two consumers: the update banner's stage poll (useServiceRestart) and the
 * boot-time overlay shown to visitors who load the app mid-update
 * (useUpdateOverlay).
 */
import { BASE } from '@/services/baseUrl'

export const UPDATE_PROGRESS_URL = BASE + 'update-progress'

/**
 * Fetch and validate the stage file.
 *
 * Resolves to {message, timestamp} (timestamp may be null) or null on ANY
 * failure — endpoint absent (HA, older stack), server down, malformed body.
 * Never rejects. Raw fetch on purpose: the axios client is rooted at /api,
 * which is down for the whole window this file exists to cover.
 */
export async function fetchUpdateStage(url = UPDATE_PROGRESS_URL) {
  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) return null
    const data = await response.json()
    if (typeof data?.message !== 'string' || !data.message) return null
    return {
      message: data.message,
      timestamp: typeof data.timestamp === 'string' ? data.timestamp : null
    }
  } catch (_error) {
    return null
  }
}

/**
 * True when the stage's timestamp is recent enough to describe a live
 * update. Future timestamps (clock skew) count as fresh; missing or
 * unparseable ones do not — after a failed update the file can linger until
 * the next dispatch or stack start, and a stale stage must not dress up an
 * unrelated outage as an update in progress.
 */
export function isStageFresh(timestamp, maxAgeMs) {
  if (!timestamp) return false
  const parsed = Date.parse(timestamp)
  if (!Number.isFinite(parsed)) return false
  return Date.now() - parsed < maxAgeMs
}
