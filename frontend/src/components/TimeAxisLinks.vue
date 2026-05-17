<template>
  <div
    class="absolute left-0 w-full pointer-events-none time-axis-links"
    :style="containerStyle"
  >
    <router-link
      v-for="tick in visibleTicks"
      :key="tick.hour"
      :to="linkTo(tick)"
      class="absolute flex justify-center leading-none text-gray-700 hover:text-blue-600 hover:underline pointer-events-auto whitespace-nowrap transition-colors duration-200"
      :style="tickStyle(tick)"
      :title="formatHourLabel(tick.label)"
    >
      {{ formatHourLabel(tick.label) }}
    </router-link>
  </div>
</template>

<script>
import { useTimeFormat } from '@/composables/useTimeFormat'

// Responsive size of the hour-label overlay. MIN fits all 24 verbose
// ("12 AM" … "11 PM") labels at the narrowest width the heatmap is shown
// (iPad landscape, ≥1024px / ~25px columns). MAX matches the bar chart's
// x-axis number font (X_AXIS_TICK_FONT_SIZE in useBirdCharts.js) so the two
// label rows read at the same size on wide screens. Cosmetic only — chart
// layout/alignment is driven by X_AXIS_TICK_FONT_SIZE, not this.
const HOUR_LABEL_FONT_MIN_PX = 8
const HOUR_LABEL_FONT_MAX_PX = 11

// Per-font gap below the heatmap cells. The plots are bottom-aligned and
// Chart.js draws the bar numbers at chartArea.bottom + tickLength(8) +
// padding(3) = 11; +2 empirical because canvas text (baseline-drawn) sits
// ~2px below an HTML element's top, giving 13 at the 8px baseline. Larger
// fonts drop their baseline further, so each sits higher. Must cover
// MIN..MAX; hand-tuned, eyeball after building.
const LABEL_TOP_OFFSET_PX = { 8: 13, 9: 12, 10: 12, 11: 11 }

// Small breathing factor applied to the measured label width when deciding
// whether labels still fit (so adjacent labels don't visually kiss).
const LABEL_FIT_SAFETY = 1.06

// Fallback only: rough average glyph width as a fraction of font size for
// the Helvetica stack, used when canvas text measurement is unavailable
// (e.g. test env). Real layout uses measured pixel widths.
const GLYPH_WIDTH_RATIO = 0.62

// Cached offscreen 2d context for measuring real label widths at the
// overlay font. Falls back to the char estimate if unavailable.
let _measureCtx
function measureLabelWidth(text, fontPx) {
  try {
    if (_measureCtx === undefined) {
      const c = typeof document !== 'undefined' ? document.createElement('canvas') : null
      _measureCtx = (c && c.getContext) ? c.getContext('2d') : null
    }
    if (_measureCtx) {
      _measureCtx.font = `${fontPx}px 'Helvetica Neue','Helvetica','Arial',sans-serif`
      const w = _measureCtx.measureText(text).width
      if (w > 0) return w
    }
  } catch { /* fall through to estimate */ }
  return text.length * fontPx * GLYPH_WIDTH_RATIO
}

export default {
  name: 'TimeAxisLinks',
  props: {
    ticks: {
      type: Array,
      default: () => []
    },
    axisTop: {
      type: Number,
      default: 0
    },
    axisHeight: {
      type: Number,
      default: 0
    },
    colWidth: {
      type: Number,
      default: 0
    },
    date: {
      type: String,
      default: null
    }
  },
  setup() {
    const { formatHourLabel } = useTimeFormat()
    return { formatHourLabel }
  },
  computed: {
    containerStyle() {
      return {
        top: `${this.axisTop}px`,
        height: `${this.axisHeight}px`
      }
    },
    // Single source of truth for label sizing: the largest font (stepping
    // down from the ceiling) whose widest label fits a column with the
    // collision-safety margin, plus that widest measured width. Floors at MIN
    // so we never shrink below the iPad-landscape baseline; visibleTicks
    // reuses maxWidth for the last-resort thinning guard.
    labelFit() {
      const ticks = this.ticks || []
      if (ticks.length === 0 || this.colWidth <= 0) {
        return { px: HOUR_LABEL_FONT_MIN_PX, maxWidth: 0 }
      }
      for (let px = HOUR_LABEL_FONT_MAX_PX; px >= HOUR_LABEL_FONT_MIN_PX; px--) {
        let maxWidth = 0
        for (const tick of ticks) {
          const w = measureLabelWidth(String(this.formatHourLabel(tick.label)), px)
          if (w > maxWidth) maxWidth = w
        }
        if (maxWidth * LABEL_FIT_SAFETY <= this.colWidth || px === HOUR_LABEL_FONT_MIN_PX) {
          return { px, maxWidth }
        }
      }
      return { px: HOUR_LABEL_FONT_MIN_PX, maxWidth: 0 }
    },
    labelFontPx() {
      return this.labelFit.px
    },
    // Per-font top offset (see LABEL_TOP_OFFSET_PX). Falls back to the 8px
    // baseline for any size not in the map.
    labelTopPx() {
      return LABEL_TOP_OFFSET_PX[this.labelFontPx] ?? LABEL_TOP_OFFSET_PX[HOUR_LABEL_FONT_MIN_PX]
    },
    // Safety net: skip hours only if a label genuinely wouldn't fit its
    // column even at the floored font. At every width the heatmap is shown
    // (≥1024px → columns ≥ ~25px) an 8px label fits, so in practice all 24
    // render; this just prevents collisions if the layout ever gets narrower.
    // Always keeps hour 0 (midnight).
    visibleTicks() {
      const ticks = this.ticks || []
      if (ticks.length === 0 || this.colWidth <= 0) return ticks

      const step = Math.max(
        1,
        Math.ceil((this.labelFit.maxWidth * LABEL_FIT_SAFETY) / this.colWidth)
      )
      if (step === 1) return ticks
      return ticks.filter(tick => tick.hour % step === 0)
    }
  },
  methods: {
    linkTo(tick) {
      const query = { hour: tick.hour }
      if (this.date) query.date = this.date
      return { name: 'Table', query }
    },
    tickStyle(tick) {
      const w = Math.max(this.colWidth, 1)
      return {
        left: `${tick.x - w / 2}px`,
        width: `${w}px`,
        top: `${this.labelTopPx}px`,
        fontSize: `${this.labelFontPx}px`
      }
    }
  }
}
</script>

<style scoped>
/* Match Chart.js's default tick font so the overlay labels render at the same
   width as the canvas would. System fonts (Tailwind default) render visibly
   wider than Helvetica/Arial. */
.time-axis-links {
  font-family: 'Helvetica Neue', 'Helvetica', 'Arial', sans-serif;
}
</style>
