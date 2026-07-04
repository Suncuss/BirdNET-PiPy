// Paces a scrolling canvas (e.g. a live spectrogram) by wall-clock time so it
// advances at a fixed number of columns per second, independent of the display's
// requestAnimationFrame cadence. A naive scroll that steps a fixed number of
// pixels per frame runs faster on a 120 Hz display than a 60 Hz one and slower
// when a browser drops frames (Safari's decode path), so the same audio feature
// renders wider or narrower depending on the screen. Driving the step off elapsed
// real time instead makes one second of audio occupy the same width everywhere.
//
// Usage:
//   const pacer = createScrollPacer(120)   // 120 columns (px) per second
//   function frame (nowMs) {                // nowMs from requestAnimationFrame
//     const cols = pacer.tick(nowMs)        // columns due this frame
//     if (cols < 1) return                  // nothing to draw yet
//     // ...shift the canvas left by `cols` and paint `cols` new columns...
//   }
// Call reset() whenever the scroll stops (pause/stall) so a later resume starts
// fresh instead of jumping forward by all the time that elapsed while stopped.

// A gap between frames larger than this is a stall, not a slow frame: a
// backgrounded tab throttles or suspends requestAnimationFrame while audio keeps
// playing, so the next frame can be seconds later. The audio from that gap was
// never sampled, so "catching up" would just smear the one current spectrum
// across hundreds of columns — the horizontal banding seen on tab-return. Past
// this threshold we rebaseline and paint nothing instead. It sits well above any
// real frame interval (~8–33 ms, even ~100 ms under heavy jank) and well below a
// background throttle (~1 s), so normal slow frames still catch up smoothly.
const STALL_GAP_MS = 250

export function createScrollPacer (columnsPerSec) {
  // Previous frame's high-res timestamp (ms); null means "rebaseline on next tick".
  let lastMs = null
  // Fractional columns owed but not yet painted, carried between frames so the
  // average rate stays exact even though each frame paints a whole number.
  let debt = 0

  return {
    // Integer columns due since the last tick, given this frame's timestamp.
    // Returns 0 on the first tick (establishing the time baseline), whenever less
    // than a full column has accrued, and on the frame after a stall (the gap is
    // dropped rather than caught up — see STALL_GAP_MS).
    tick (nowMs) {
      // Defend the one numeric input: a non-finite timestamp (e.g. a stray draw
      // call made outside requestAnimationFrame) must not poison lastMs/debt with
      // NaN, which would silently freeze the scroll forever. Skip the frame instead.
      if (!Number.isFinite(nowMs)) return 0
      if (lastMs === null) {
        lastMs = nowMs
        return 0
      }
      const elapsedMs = nowMs - lastMs
      lastMs = nowMs
      // Stall (backgrounded tab, long jank): drop the gap and resume cleanly next
      // frame rather than smearing one spectrum across the missed columns.
      if (elapsedMs > STALL_GAP_MS) {
        debt = 0
        return 0
      }
      debt += (elapsedMs / 1000) * columnsPerSec
      const cols = Math.floor(debt)
      if (cols < 1) return 0
      debt -= cols
      return cols
    },

    // Forget accrued time and owed columns. The next tick rebaselines as if the
    // scroll were starting from scratch.
    reset () {
      lastMs = null
      debt = 0
    }
  }
}
