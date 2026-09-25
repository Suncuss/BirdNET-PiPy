/**
 * Gap for a horizontally scrolling row that guarantees a "peek": when the
 * items overflow, pick a spacing so the visible edge cuts through the middle
 * of an item instead of landing in the space between two. A half-visible
 * label is what tells people the row scrolls; a row that happens to end on a
 * gap looks finished.
 *
 * Returns baseGap when everything fits (nothing to hint at). Otherwise picks
 * the gap with the best cut, preferring the one closest to baseGap so the row
 * stays near its normal spacing, and settling for the nearest miss if no gap
 * is ideal.
 */

// Spacing the search may use: from links touching to visibly airy.
const MIN_GAP = 0
const MAX_GAP = 26

// The edge should fall within this slice of an item's label (its width minus
// itemPadding each side) — enough showing to read as a word, enough hidden to
// read as clipped.
const CUT_MIN = 0.35
const CUT_MAX = 0.7

// How far the edge is from an ideal cut at this gap: 0 inside the slice,
// 1 when it lands between items.
function cutMiss(itemWidths, gap, edge, paddingStart, itemPadding) {
  let x = paddingStart
  for (const w of itemWidths) {
    if (edge >= x && edge <= x + w) {
      const fraction = (edge - x - itemPadding) / (w - 2 * itemPadding)
      return Math.max(0, CUT_MIN - fraction, fraction - CUT_MAX)
    }
    x += w + gap
  }
  return 1
}

export function computePeekGap({
  itemWidths,
  viewportWidth,
  edgeInset = 0, // px at the trailing edge covered by an overlay (chevron)
  paddingStart = 0,
  paddingEnd = paddingStart,
  itemPadding = 0, // px of inner padding each side of an item's label
  baseGap = 4
}) {
  const edge = viewportWidth - edgeInset
  if (!itemWidths.length || edge <= 0) return baseGap

  const total = paddingStart + paddingEnd + itemWidths.reduce((sum, w) => sum + w, 0) +
    baseGap * (itemWidths.length - 1)
  if (total <= viewportWidth) return baseGap

  // Closest to baseGap first (the sort is stable, so the tighter gap wins a
  // tie); the strict < below then keeps the first of any equally good cuts.
  const candidates = Array.from({ length: MAX_GAP - MIN_GAP + 1 }, (_, i) => MIN_GAP + i)
    .sort((a, b) => Math.abs(a - baseGap) - Math.abs(b - baseGap))

  let best = baseGap
  let bestMiss = Infinity
  for (const gap of candidates) {
    const miss = cutMiss(itemWidths, gap, edge, paddingStart, itemPadding)
    if (miss < bestMiss) {
      best = gap
      bestMiss = miss
    }
  }
  return best
}
