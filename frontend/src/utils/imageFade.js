/**
 * Swap an image's display fields with a brief fade.
 *
 * Hides the image, synchronously applies the field changes, waits one frame
 * so the hidden state actually paints, then shows it again — the CSS opacity
 * transition fades the new image in. Without the frame wait the browser can
 * coalesce hide+show into one style update and skip the fade entirely.
 *
 * Once started it always completes — the image is never left hidden.
 *
 * @param {(visible: boolean) => void} setVisible - toggles the bound opacity state
 * @param {() => void} applyFields - synchronously applies the new image fields
 * @returns {Promise<void>}
 */
export async function swapImageWithFade(setVisible, applyFields) {
  setVisible(false)
  applyFields()
  await new Promise(resolve => requestAnimationFrame(resolve))
  setVisible(true)
}
