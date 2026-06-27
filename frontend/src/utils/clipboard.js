/**
 * Copy text to the clipboard, with a fallback for non-secure contexts.
 *
 * navigator.clipboard is only available in secure contexts (HTTPS or
 * localhost). BirdNET-PiPy is frequently reached over plain HTTP on a LAN,
 * where it is undefined — so fall back to a hidden <textarea> + execCommand,
 * which still works there.
 *
 * @param {string} text
 * @returns {Promise<boolean>} true if the copy succeeded
 */
export async function copyText(text) {
  if (!text) return false

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Permission denied or transient failure — fall through to the fallback.
    }
  }

  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
