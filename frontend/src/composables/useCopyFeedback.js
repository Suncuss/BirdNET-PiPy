import { ref, onUnmounted } from 'vue'
import { copyText } from '@/utils/clipboard'

/**
 * Copy text to the clipboard and flash a transient "copied" confirmation.
 *
 * `copied` holds the key of the most recent successful copy (defaults to
 * `true` when no key is given) and resets to `null` after `resetMs`. Pass a
 * key when one handler serves many items (e.g. a list of share buttons) so the
 * caller can light up just the one that was copied: `copied.value === item.id`.
 *
 * The reset timer is cleared on the owning component's unmount.
 *
 * @param {number} [resetMs=2000]
 * @returns {{ copied: import('vue').Ref<*>, copy: (text: string, key?: *) => Promise<boolean> }}
 */
export function useCopyFeedback(resetMs = 2000) {
  const copied = ref(null)
  let timer = null

  const copy = async (text, key = true) => {
    if (!(await copyText(text))) return false
    copied.value = key
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { copied.value = null }, resetMs)
    return true
  }

  onUnmounted(() => {
    if (timer) clearTimeout(timer)
  })

  return { copied, copy }
}
