import { describe, it, expect } from 'vitest'
import { createScrollPacer } from '@/utils/scrollPacer'

describe('createScrollPacer', () => {
  it('returns 0 on the first tick to establish a time baseline', () => {
    const pacer = createScrollPacer(120)
    expect(pacer.tick(1000)).toBe(0)
  })

  it('advances at the configured columns-per-second regardless of frame cadence', () => {
    // Feed several seconds of frames at different refresh rates and sum the columns
    // painted. It must match columnsPerSec * seconds (within the <1 column still in
    // the fractional carry) in every case — that constancy is the whole point. A
    // per-frame scroll would instead scale with the rate (2x at 120 Hz vs 60 Hz).
    const rate = 120
    const seconds = 10
    const totalFor = (fps) => {
      const pacer = createScrollPacer(rate)
      const dt = 1000 / fps
      let total = 0
      for (let i = 0; i <= fps * seconds; i++) total += pacer.tick(i * dt)
      return total
    }
    for (const fps of [60, 120, 144, 90, 45]) {
      expect(Math.abs(totalFor(fps) - rate * seconds)).toBeLessThanOrEqual(1)
    }
  })

  it('only ever paints a whole, non-negative number of columns', () => {
    const pacer = createScrollPacer(120)
    const dt = 1000 / 90 // 1.333… columns owed per frame
    for (let i = 0; i <= 100; i++) {
      const cols = pacer.tick(i * dt)
      expect(Number.isInteger(cols)).toBe(true)
      expect(cols).toBeGreaterThanOrEqual(0)
    }
  })

  it('catches up a slow frame but drops a stall gap instead of smearing', () => {
    // A sub-threshold slow frame still advances, keeping the average rate accurate.
    const slow = createScrollPacer(120)
    slow.tick(0) // baseline
    expect(slow.tick(100)).toBe(12) // 100 ms * 120/s = 12 columns

    // A multi-second gap (rAF suspended while the tab is backgrounded, audio still
    // playing) must NOT return a huge catch-up burst — that smears one spectrum
    // across the canvas as horizontal banding. It returns 0 and rebaselines.
    const pacer = createScrollPacer(120)
    pacer.tick(0) // baseline
    expect(pacer.tick(5000)).toBe(0)
    // The next normal frame advances normally — no leftover backlog from the gap.
    const next = pacer.tick(5000 + 1000 / 60)
    expect(next).toBeGreaterThanOrEqual(1)
    expect(next).toBeLessThanOrEqual(3)
  })

  it('ignores a non-finite timestamp instead of poisoning its state', () => {
    const pacer = createScrollPacer(120)
    pacer.tick(1000) // baseline
    expect(pacer.tick(undefined)).toBe(0) // a stray non-rAF call
    expect(pacer.tick(NaN)).toBe(0)
    // State survived: a real frame a normal interval later still advances normally.
    expect(pacer.tick(1100)).toBe(12) // 100 ms * 120/s = 12 columns
  })

  it('reset() rebaselines so a resume does not jump forward', () => {
    const pacer = createScrollPacer(120)
    pacer.tick(1000)
    pacer.reset()
    // Even though 5 s of wall-clock passed, the first tick after reset only
    // re-establishes the baseline and paints nothing.
    expect(pacer.tick(6000)).toBe(0)
    expect(pacer.tick(6000 + 1000 / 60)).toBeGreaterThanOrEqual(1)
  })
})
