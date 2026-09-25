import { describe, it, expect } from 'vitest'
import { computePeekGap } from '@/utils/peekGap'

// The nav row as NavLinks.vue ships it: link widths for Dashboard / Gallery /
// Live Feed / Charts / Table / Settings (15px labels, 8px padding each side),
// strip padding 8 / 16, and a 28px chevron over the trailing edge.
const LINKS = [97, 69, 87, 65, 55, 78]
const NAV = { paddingStart: 8, paddingEnd: 16, itemPadding: 8, edgeInset: 28 }

// Where the edge falls inside whichever item it crosses, as a fraction of that
// item's label — or null when it lands in a gap / past the end.
const cutFraction = (itemWidths, gap, edge, paddingStart, itemPadding = 0) => {
  let x = paddingStart
  for (const w of itemWidths) {
    if (edge >= x && edge <= x + w) return (edge - x - itemPadding) / (w - 2 * itemPadding)
    x += w + gap
  }
  return null
}

describe('computePeekGap', () => {
  it('keeps the base gap when every item fits', () => {
    expect(computePeekGap({ itemWidths: LINKS, viewportWidth: 1200, paddingStart: 16 })).toBe(4)
  })

  it('counts trailing padding when deciding whether the row overflows', () => {
    // Items + gaps = 100; fits in 110 without padding, overflows with 16 + 16.
    const args = { itemWidths: [50, 46], viewportWidth: 110 }
    expect(computePeekGap({ ...args, baseGap: 4 })).toBe(4)
    expect(computePeekGap({ ...args, baseGap: 4, paddingStart: 16 })).toBe(12)
  })

  const navCut = (viewportWidth) => {
    const gap = computePeekGap({ itemWidths: LINKS, viewportWidth, ...NAV })
    return cutFraction(LINKS, gap, viewportWidth - NAV.edgeInset, NAV.paddingStart, NAV.itemPadding)
  }

  it('cuts through the middle of a label at the common phone widths', () => {
    for (const viewportWidth of [320, 360, 375, 390, 393, 412, 414, 430]) {
      const fraction = navCut(viewportWidth)
      expect(fraction, `width ${viewportWidth}`).toBeGreaterThanOrEqual(0.35)
      expect(fraction, `width ${viewportWidth}`).toBeLessThanOrEqual(0.7)
    }
  })

  it('never lands between items, and only narrowly misses the ideal cut, at any width', () => {
    for (let viewportWidth = 300; viewportWidth <= 480; viewportWidth++) {
      const fraction = navCut(viewportWidth)
      expect(fraction, `width ${viewportWidth}`).not.toBeNull()
      expect(fraction, `width ${viewportWidth}`).toBeGreaterThanOrEqual(0.25)
      expect(fraction, `width ${viewportWidth}`).toBeLessThanOrEqual(0.8)
    }
  })

  it('prefers the gap closest to the base spacing', () => {
    // Edge already cuts the second item in half at the base gap.
    expect(computePeekGap({ itemWidths: [100, 100, 100], viewportWidth: 154 })).toBe(4)
  })

  it('settles for the nearest miss when no gap gives a clean cut', () => {
    // One wide item: no gap can move it, so the base gap is as good as any.
    expect(computePeekGap({ itemWidths: [500], viewportWidth: 375 })).toBe(4)
  })

  it('falls back to the base gap for degenerate input', () => {
    expect(computePeekGap({ itemWidths: [], viewportWidth: 375 })).toBe(4)
    expect(computePeekGap({ itemWidths: LINKS, viewportWidth: 0 })).toBe(4)
  })
})
