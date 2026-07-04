<template>
  <div>
    <div class="flex justify-between items-center text-[13px] mb-2">
      <label
        :for="inputId"
        class="text-gray-600"
      >{{ label }}</label>
      <span class="font-medium tabular-nums text-gray-800">{{ displayValue }}</span>
    </div>
    <input
      :id="inputId"
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="modelValue"
      class="w-full cursor-pointer"
      :style="{ '--fill': fill }"
      :aria-label="ariaLabel"
      @input="$emit('update:modelValue', Number($event.target.value))"
    >
  </div>
</template>

<script>
import { computed } from 'vue'

// Shared labelled range slider: the green-fill high-pass/gain control used by the
// Live Feed and the detection player, which carried this markup + CSS verbatim.
// The parent owns value formatting (passed in as displayValue) and the actual
// audio wiring; this only renders the control and emits a numeric model value.
export default {
  name: 'RangeSlider',
  props: {
    modelValue: { type: Number, required: true },
    min: { type: Number, required: true },
    max: { type: Number, required: true },
    step: { type: Number, default: 1 },
    label: { type: String, default: '' },
    // Pre-formatted current value shown at the right of the label row
    // (e.g. "1500 Hz", "Off", "+6 dB").
    displayValue: { type: String, default: '' },
    // id for the <input> and the label's `for`, kept stable so existing selectors
    // and the label↔input a11y association keep working.
    inputId: { type: String, required: true },
    ariaLabel: { type: String, default: '' }
  },
  emits: ['update:modelValue'],
  setup (props) {
    // Green fill fraction (0–100%) for the portion of the track left of the thumb,
    // driven into the WebKit track gradient via the --fill CSS var so the filled
    // look is identical across browsers (Firefox uses ::-moz-range-progress, which
    // fills automatically). Generic (value−min)/(max−min) reproduces each old call
    // site's per-slider formula exactly.
    const fill = computed(() => {
      const span = props.max - props.min
      const frac = span > 0 ? (props.modelValue - props.min) / span : 0
      return `${Math.max(0, Math.min(1, frac)) * 100}%`
    })
    return { fill }
  }
}
</script>

<style scoped>
/* Range sliders — cross-browser so the track/thumb render the same on iOS Safari
   and desktop. Thin 4px track with the app's green fill up to the thumb (--fill)
   and a 16px green thumb with a white ring. */
input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  /* Block + zero margin drops the inline-baseline descender gap below the input
     and the UA's default margin, which otherwise leave extra space under the
     track and make it sit slightly high (off-centre) in its row. */
  display: block;
  margin: 0;
  /* Register taps/drags immediately on touch (no double-tap-zoom delay). */
  touch-action: manipulation;
}

/* WebKit/Blink size the <input> box to the track height and let the thumb overflow
   it (the thumb is centred on the track by its negative margin-top below). That
   bottom overflow pokes past the track into the grey panel's padding, so the
   label + slider read as bottom-heavy / not centred. Reserve that overflow plus the
   label row's ~4px top line-leading so the control sits centred in its panel.
   Firefox sizes the box to contain the thumb (no overflow), so it's scoped out by
   the @supports test. The values derive from the thumb/track sizes set below — keep
   them in sync if those change. */
@supports selector(::-webkit-slider-thumb) {
  input[type="range"] {
    margin-bottom: 10px; /* (16px thumb − 4px track) / 2 overflow + ~4px leading */
  }
  @media (pointer: coarse) {
    input[type="range"] {
      margin-bottom: 11px; /* (20px thumb − 6px track) / 2 overflow + ~4px leading */
    }
  }
}

/* WebKit has no progress pseudo-element, so paint the fill as a gradient;
   Firefox uses ::-moz-range-progress. */
input[type="range"]::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 9999px;
  background: linear-gradient(
    to right,
    theme('colors.green.600') var(--fill, 0%),
    theme('colors.gray.200') var(--fill, 0%)
  );
}

input[type="range"]::-moz-range-track {
  height: 4px;
  border-radius: 9999px;
  background-color: theme('colors.gray.200');
}

input[type="range"]::-moz-range-progress {
  height: 4px;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
}

input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
  cursor: pointer;
  margin-top: -6px;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

input[type="range"]::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
  cursor: pointer;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

input[type="range"]:hover::-webkit-slider-thumb {
  background-color: theme('colors.green.700');
}

input[type="range"]:hover::-moz-range-thumb {
  background-color: theme('colors.green.700');
}

/* Touch devices: grow the track and thumb so the control is easy to grab and not
   easy to miss (the 16px/4px desktop target is well under the ~44px touch
   guideline). `pointer: coarse` matches touch-primary devices (phones, tablets)
   and leaves the desktop mouse slider unchanged. Keep each vendor pseudo-element
   in its own rule — a combined selector list is dropped wholesale by each engine
   when it doesn't recognise one of the prefixes. */
@media (pointer: coarse) {
  input[type="range"]::-webkit-slider-runnable-track {
    height: 6px;
  }
  input[type="range"]::-moz-range-track {
    height: 6px;
  }
  input[type="range"]::-moz-range-progress {
    height: 6px;
  }
  input[type="range"]::-webkit-slider-thumb {
    width: 20px;
    height: 20px;
    margin-top: -7px; /* re-center on the 6px track: -(20 - 6) / 2 */
  }
  input[type="range"]::-moz-range-thumb {
    width: 20px;
    height: 20px;
  }
}
</style>
