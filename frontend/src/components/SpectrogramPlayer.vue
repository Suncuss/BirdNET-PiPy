<template>
  <div
    ref="rootEl"
    class="overflow-hidden"
  >
    <!-- Spectrogram: a static, labelled plot (title + frequency axis + colorbar)
         covering only the detected window, so it is NOT a faithful time axis of
         the audio — we don't scrub on it. Click to open it full size. -->
    <div
      class="bg-gray-900"
      :class="showExpand ? 'cursor-zoom-in' : ''"
      @click="showExpand && $emit('expand')"
    >
      <!-- Reserve the image's slot height before it loads, so paging to
           as-yet-uncached recordings doesn't collapse the grid to zero height
           and jump the page scroll. Only the ~4.18:1 aspect ratio matters here
           (w-full drives the real width). 1066x255 are the *measured* output
           dims of generate_spectrogram (matplotlib savefig bbox_inches='tight',
           NOT figsize×dpi) — re-measure if its figsize/dpi/title/labels change.
           Going stale only causes a small residual shift, not a break. -->
      <img
        :src="spectrogramUrl"
        alt="Spectrogram"
        width="1066"
        height="255"
        class="w-full block"
      >
    </div>

    <!-- Controls. The generated spectrogram bakes in a ~11%-of-height white
         margin below the plot (no x-axis labels); pull this white row up over it
         so the controls sit close to the plot. The strip is a fixed fraction of
         the image width, so a percentage margin scales at any card size.
         NOTE: -2.5% is tuned to backend `generate_spectrogram` (backend/core/
         utils.py: subplots_adjust(bottom=0.1) + savefig bbox_inches='tight').
         The real fix is to stop baking that bottom margin server-side; if those
         knobs change, re-tune (or remove) this value. -->
    <div
      class="relative z-10 flex items-center p-2 pb-1 sm:p-3 sm:pb-1.5 bg-white"
      :class="sizes.gap"
      style="margin-top: -2.5%"
    >
      <button
        type="button"
        class="flex items-center justify-center shrink-0 rounded-full bg-green-600 text-white hover:bg-green-700 transition-colors"
        :class="sizes.play"
        :title="isPlaying ? 'Pause' : 'Play'"
        @click="togglePlay"
      >
        <font-awesome-icon
          :icon="isPlaying ? ['fas', 'pause'] : ['fas', 'play']"
          :class="[sizes.playIcon, { 'ml-0.5': !isPlaying }]"
        />
      </button>

      <!-- The real scrubber: a seek bar driven by audio time, independent of the
           spectrogram image. Custom-styled (see <style>) so the hover state is a
           calm deep green rather than the browser's bright native accent. -->
      <input
        type="range"
        class="seek flex-1 min-w-0 disabled:opacity-60"
        :style="{ '--seek-fill': progressPercent }"
        min="0"
        :max="duration || 1"
        step="0.01"
        :value="currentTime"
        :disabled="!duration"
        aria-label="Seek"
        @input="seekTo(Number($event.target.value))"
      >

      <span
        v-if="!compact"
        class="text-xs tabular-nums text-gray-500 whitespace-nowrap"
      >
        {{ clock(currentTime) }} / {{ clock(duration) }}
      </span>

      <div class="flex items-center shrink-0">
        <a
          :href="audioUrl"
          :download="downloadName"
          class="flex items-center justify-center rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          :class="sizes.box"
          title="Download audio"
        >
          <font-awesome-icon
            :icon="['fas', 'download']"
            :class="sizes.icon"
          />
        </a>

        <router-link
          :to="{ name: 'BirdRecording', params: { name: recording.common_name, id: recording.id } }"
          class="flex items-center justify-center rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          :class="sizes.box"
          title="View detection details"
        >
          <font-awesome-icon
            :icon="['fas', 'circle-info']"
            :class="sizes.icon"
          />
        </router-link>
      </div>
    </div>

    <audio
      ref="audioEl"
      :src="audioUrl"
      preload="metadata"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faPlay, faPause, faDownload, faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

import { getAudioUrl, getSpectrogramUrl } from '@/services/media'
import { useAudioTransport } from '@/composables/useAudioTransport'

library.add(faPlay, faPause, faDownload, faCircleInfo)

const props = defineProps({
  recording: {
    type: Object,
    required: true
  },
  // Whether the spectrogram is click-to-expand. The parent owns the modal (via
  // @expand), so a parent that doesn't render one can switch this off.
  showExpand: {
    type: Boolean,
    default: true
  }
})

defineEmits(['expand'])

const audioUrl = computed(() => getAudioUrl(props.recording?.audio_filename, props.recording?.audio_sig))
const spectrogramUrl = computed(() => getSpectrogramUrl(props.recording?.spectrogram_filename, props.recording?.spectrogram_sig))
const downloadName = computed(() => props.recording?.audio_filename || 'recording.mp3')

// --- Audio playback (shared transport; `--seek-fill` uses progressPercent) ---
const audioEl = ref(null)
const { isPlaying, currentTime, duration, progressPercent, clock, togglePlay, seekTo } =
  useAudioTransport(audioEl)

// --- Compact mode ---
// Drop the time label when the player itself is too narrow for it (not the
// viewport — cards go 1→2 columns, so width isn't monotonic with screen size).
const COMPACT_WIDTH_PX = 340
const rootEl = ref(null)
const compact = ref(false)
let resizeObserver = null

// One size tier for the whole control strip — everything shrinks a step in
// compact mode. Kept in one place so the two icon buttons can't drift apart and
// so size tweaks live in a single object.
const sizes = computed(() => compact.value
  ? { gap: 'gap-1', play: 'h-4 w-4', playIcon: 'h-2 w-2', box: 'h-6 w-5', icon: 'h-3 w-3' }
  : { gap: 'gap-2', play: 'h-6 w-6', playIcon: 'h-2.5 w-2.5', box: 'h-8 w-7', icon: 'h-3.5 w-3.5' }
)

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !rootEl.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    const width = entry?.contentRect?.width ?? 0
    if (width > 0) compact.value = width < COMPACT_WIDTH_PX
  })
  resizeObserver.observe(rootEl.value)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
/* Custom seek bar — matches the app's slider convention (Settings.vue): a thin
   gray track with a green fill and a deep-green-on-hover thumb, instead of the
   browser's bright native `accent-color` highlight. */
.seek {
  -webkit-appearance: none;
  appearance: none;
  height: 0.375rem;
  border-radius: 9999px;
  background: transparent;
  cursor: pointer;
}
.seek:disabled {
  cursor: default;
}

/* Track + green fill — Chrome, Safari, Edge */
.seek::-webkit-slider-runnable-track {
  height: 0.375rem;
  border-radius: 9999px;
  background: linear-gradient(
    to right,
    theme('colors.green.600') var(--seek-fill, 0%),
    theme('colors.gray.200') var(--seek-fill, 0%)
  );
}

/* Track + green fill — Firefox (progress fills natively) */
.seek::-moz-range-track {
  height: 0.375rem;
  border-radius: 9999px;
  background-color: theme('colors.gray.200');
}
.seek::-moz-range-progress {
  height: 0.375rem;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
}

/* Thumb — Chrome, Safari, Edge */
.seek::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 0.875rem;
  height: 0.875rem;
  margin-top: -0.25rem;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
  border: 2px solid white;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  transition: background-color 0.15s ease;
}

/* Thumb — Firefox */
.seek::-moz-range-thumb {
  width: 0.875rem;
  height: 0.875rem;
  border-radius: 9999px;
  background-color: theme('colors.green.600');
  border: 2px solid white;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  transition: background-color 0.15s ease;
}

/* Hover: a calmer, deeper green rather than the bright native highlight */
.seek:hover::-webkit-slider-thumb {
  background-color: theme('colors.green.700');
}
.seek:hover::-moz-range-thumb {
  background-color: theme('colors.green.700');
}
</style>
