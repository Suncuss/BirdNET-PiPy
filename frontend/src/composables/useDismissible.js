import { ref } from 'vue'

/**
 * A localStorage-backed "dismissed until" timer, for banners/indicators the
 * user can snooze for a fixed duration. Call once at module scope so the
 * dismissed state is shared (singleton) across all consumers.
 *
 * @param {string} storageKey - localStorage key holding the expiry timestamp
 * @param {number} durationMs - how long one dismissal lasts
 * @returns {{ isDismissed: () => boolean, dismiss: () => void }}
 */
export function useDismissible(storageKey, durationMs) {
  const load = () => {
    try {
      const stored = localStorage.getItem(storageKey)
      return stored ? parseInt(stored, 10) : null
    } catch {
      return null
    }
  }

  const dismissedUntil = ref(load())

  // A function, not a computed: the result depends on the current time, so a
  // computed would cache a stale value until `dismissedUntil` next changes.
  // Callers invoke it inside their own computed, which re-reads it each run.
  const isDismissed = () =>
    dismissedUntil.value !== null && Date.now() < dismissedUntil.value

  const dismiss = () => {
    const expiry = Date.now() + durationMs
    dismissedUntil.value = expiry
    try {
      localStorage.setItem(storageKey, String(expiry))
    } catch {
      // localStorage unavailable — dismissal just won't persist across reloads
    }
  }

  return { isDismissed, dismiss }
}
