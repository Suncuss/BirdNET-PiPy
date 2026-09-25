/**
 * Decouple *when* a gallery card finishes loading from *when* it is shown.
 *
 * Loads run in parallel and finish in random order; showing each the moment
 * it lands makes the grid flicker at a random pace. The scheduler hands out
 * tickets in enqueue order (reading order — cards intersect the viewport
 * top-to-bottom) and reveals results in that same order, `gapMs` apart, so
 * the grid fills in as one calm wave.
 *
 * A slow card never stalls the wave: once the head has waited `holdMs`, the
 * scheduler skips past it, and the straggler reveals by itself when it lands.
 * Tickets settled with no result (nothing to show) cost no wave time.
 *
 * @param {object} opts
 * @param {(item: object, result: object) => void} opts.reveal
 * @param {number} [opts.gapMs]
 * @param {number} [opts.holdMs]
 */
export function createRevealScheduler({ reveal, gapMs = 90, holdMs = 1200 }) {
  let entries = []  // unrevealed tickets in enqueue order
  let gapTimer = null
  let hold = null  // { entry, timer }: waiting on an unsettled head

  const stopHold = () => {
    if (hold) clearTimeout(hold.timer)
    hold = null
  }

  const pump = () => {
    if (gapTimer) return
    while (entries.length && entries[0].settled && !entries[0].result) entries.shift()
    const head = entries[0]
    if (!head) {
      stopHold()
    } else if (head.settled) {
      stopHold()
      entries.shift()
      reveal(head.item, head.result)
      gapTimer = setTimeout(() => { gapTimer = null; pump() }, gapMs)
    } else if (hold?.entry !== head) {
      stopHold()
      hold = {
        entry: head,
        timer: setTimeout(() => {
          hold = null
          entries.shift()
          head.late = true  // reveals itself on settle, outside the wave
          pump()
        }, holdMs)
      }
    }
  }

  return {
    add(item) {
      const entry = { item, settled: false, result: null, late: false }
      entries.push(entry)
      return entry
    },
    settle(entry, result) {
      entry.settled = true
      entry.result = result
      if (entry.late) {
        if (result) reveal(entry.item, result)
        return
      }
      pump()
    },
    reset() {
      clearTimeout(gapTimer)
      gapTimer = null
      stopHold()
      entries = []
    }
  }
}
