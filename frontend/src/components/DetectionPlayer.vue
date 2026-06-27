<template>
  <!-- Loading -->
  <div
    v-if="loading"
    class="flex items-center justify-center py-20"
  >
    <Spinner class="h-8 w-8 text-green-600" />
    <span class="ml-3 text-gray-500">Loading detection…</span>
  </div>

  <!-- Not found -->
  <div
    v-else-if="error || !recording"
    class="p-10 text-center"
  >
    <h1 class="text-xl font-semibold text-gray-900 mb-2">
      Detection not found
    </h1>
    <p class="text-gray-500 mb-6">
      This detection could not be found. It may have been removed.
    </p>
    <slot name="not-found-action" />
  </div>

  <!-- Loaded -->
  <div
    v-else
    class="px-5 sm:px-9 pt-4 sm:pt-5 pb-4 sm:pb-5"
  >
    <!-- Header -->
    <div class="flex items-start justify-between gap-6">
      <div class="min-w-0">
        <router-link
          :to="{ name: 'BirdDetails', params: { name: recording.common_name } }"
          class="block text-[22px] sm:text-[26px] leading-tight font-bold tracking-tight text-gray-900 hover:text-green-600 transition-colors break-words"
        >
          {{ displayName }}
        </router-link>
        <p
          v-if="recording.scientific_name"
          class="italic text-[13px] leading-snug text-gray-500 mt-0.5"
        >
          {{ recording.scientific_name }}
        </p>
        <p class="text-[13px] leading-snug text-gray-500 mt-0.5">
          {{ formattedTimestamp }}
        </p>
      </div>

      <!-- Confidence -->
      <div
        v-if="confidenceInt != null"
        class="shrink-0 text-right"
      >
        <div
          class="font-bold leading-none tracking-tight tabular-nums"
          :class="confidenceColor"
        >
          <span class="text-[28px]">{{ confidenceInt }}</span><span class="text-[16px]">%</span>
        </div>
        <div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mt-1">
          Confidence
        </div>
        <div class="w-[110px] h-[5px] rounded-full bg-gray-200 overflow-hidden ml-auto mt-2">
          <div
            class="h-full bg-current"
            :class="confidenceColor"
            :style="{ width: confidenceInt + '%' }"
          />
        </div>
      </div>
    </div>

    <!-- Media present: spectrogram + transport + filters -->
    <template v-if="hasMedia">
      <!-- Spectrogram (hero) — rendered on the fly from the audio -->
      <div
        ref="specWrap"
        class="relative mt-4 rounded-xl overflow-hidden border border-gray-200 bg-gray-950 cursor-pointer select-none"
        @pointerdown="onSeekPointer"
      >
        <canvas
          ref="specCanvas"
          class="w-full block h-[180px] sm:[@media(min-height:640px)]:h-[270px]"
        />
        <!-- Playhead -->
        <div
          v-show="duration"
          class="absolute top-0 bottom-0 w-px bg-white/80 pointer-events-none shadow-[0_0_4px_rgba(255,255,255,0.8)]"
          :style="{ left: progressPercent }"
        />
        <!-- Spectrogram still computing -->
        <div
          v-if="audioState === 'loading'"
          class="absolute inset-0 flex items-center justify-center text-gray-300 text-sm"
        >
          <Spinner class="h-5 w-5 text-green-500" />
          <span class="ml-2">Analyzing audio…</span>
        </div>
        <div
          v-else-if="audioState === 'error'"
          class="absolute inset-0 flex items-center justify-center text-gray-300 text-sm px-4 text-center"
        >
          {{ audioError }}
        </div>
      </div>

      <!-- Transport -->
      <div class="flex items-center justify-between flex-wrap gap-y-3 gap-x-4 mt-3">
        <div class="flex items-center gap-3">
          <button
            type="button"
            class="flex items-center justify-center h-8 w-8 sm:h-9 sm:w-9 shrink-0 rounded-full bg-green-600 text-white shadow-[0_2px_8px_rgba(22,163,74,0.35)] hover:bg-green-700 disabled:opacity-50 transition-colors"
            :title="isPlaying ? 'Pause' : 'Play'"
            :disabled="audioState !== 'ready'"
            @click="togglePlay"
          >
            <font-awesome-icon
              :icon="isPlaying ? ['fas', 'pause'] : ['fas', 'play']"
              class="h-3.5 w-3.5"
              :class="{ 'ml-0.5': !isPlaying }"
            />
          </button>
          <span class="text-sm tabular-nums text-gray-800">
            {{ clock(currentTime) }} <span class="text-gray-400">/ {{ clock(duration) }}</span>
          </span>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 border rounded-md px-2.5 sm:px-3 h-8 sm:h-9 text-[13px] font-medium transition-colors"
            :class="copied
              ? 'border-green-600 text-green-700 bg-green-50'
              : 'border-gray-200 bg-white text-gray-700 hover:border-green-600 hover:text-green-600'"
            :title="copied ? 'Link copied' : 'Copy share link'"
            @click="share"
          >
            <font-awesome-icon
              :icon="copied ? ['fas', 'check'] : ['fas', 'arrow-up-from-bracket']"
              class="h-3.5 w-3.5"
            />
            <span class="hidden sm:inline">{{ copied ? 'Copied' : 'Share' }}</span>
          </button>
          <a
            :href="audioUrl"
            :download="downloadName"
            class="inline-flex items-center gap-1.5 border border-gray-200 bg-white rounded-md px-2.5 sm:px-3 h-8 sm:h-9 text-[13px] font-medium text-gray-700 hover:border-green-600 hover:text-green-600 transition-colors"
            title="Download original audio"
          >
            <font-awesome-icon
              :icon="['fas', 'download']"
              class="h-3.5 w-3.5"
            />
            <span class="hidden sm:inline">Download</span>
          </a>
        </div>
      </div>

      <!-- Filter controls (live, non-destructive) -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 mt-4 px-5 py-3 sm:px-[22px] bg-gray-50 rounded-xl">
        <!-- High-pass -->
        <div>
          <div class="flex justify-between items-center text-[13px] mb-2">
            <label
              for="highpass"
              class="text-gray-600"
            >High-pass filter</label>
            <span class="font-medium tabular-nums text-gray-800">{{ highpassLabel }}</span>
          </div>
          <input
            id="highpass"
            v-model.number="highpassHz"
            type="range"
            min="0"
            max="6000"
            step="50"
            class="w-full cursor-pointer"
            :style="{ '--fill': highpassFill }"
            aria-label="High-pass cutoff frequency"
          >
        </div>

        <!-- Gain -->
        <div>
          <div class="flex justify-between items-center text-[13px] mb-2">
            <label
              for="gain"
              class="text-gray-600"
            >Gain</label>
            <span class="font-medium tabular-nums text-gray-800">{{ gainLabel }}</span>
          </div>
          <input
            id="gain"
            v-model.number="gainDb"
            type="range"
            min="-12"
            max="24"
            step="1"
            class="w-full cursor-pointer"
            :style="{ '--fill': gainFill }"
            aria-label="Playback gain"
          >
        </div>
      </div>
    </template>

    <!-- Media cleaned up -->
    <div
      v-else
      class="mt-6 rounded-xl border border-gray-200 bg-gray-50 px-6 py-12 text-center text-[13px] text-gray-500"
    >
      The audio for this detection is no longer available.
    </div>

    <!-- Conditions -->
    <div
      v-if="hasWeatherData"
      class="mt-[26px]"
    >
      <div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
        Conditions
      </div>
      <div class="flex items-center gap-2.5 mt-3">
        <span class="text-[26px] leading-none">{{ weatherDescription.icon }}</span>
        <span class="text-[22px] font-bold tabular-nums text-gray-900">{{ formattedTemp }}</span>
        <span class="text-[15px] text-gray-500">{{ weatherDescription.desc }}</span>
      </div>
      <dl
        v-if="weatherStats.length"
        class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-px mt-3 bg-gray-200 border border-gray-200 rounded-xl overflow-hidden"
      >
        <div
          v-for="stat in weatherStats"
          :key="stat.label"
          class="bg-white px-4 py-2"
          :class="{ 'hidden sm:block': stat.hideOnMobile }"
        >
          <dt class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            {{ stat.label }}
          </dt>
          <dd class="text-base font-semibold tabular-nums text-gray-900 mt-0.5">
            {{ stat.value }}<span
              v-if="stat.unit"
              class="text-xs text-gray-500 ml-1"
            >{{ stat.unit }}</span>
          </dd>
        </div>
      </dl>
    </div>

    <!-- Metadata -->
    <div
      v-if="hasFilteredExtraData"
      class="mt-4 border-t border-gray-200 divide-y divide-gray-100"
    >
      <div
        v-for="row in metadataRows"
        :key="row.key"
        class="flex justify-between items-start gap-4 py-2 text-sm"
      >
        <span class="text-gray-500">{{ row.label }}</span>
        <a
          v-if="row.href"
          :href="row.href"
          target="_blank"
          rel="noopener noreferrer"
          :title="`View ${row.value} on eBird`"
          class="text-gray-800 tabular-nums text-right break-all underline-offset-2 hover:text-green-600 hover:underline transition-colors"
        >{{ row.value }}</a>
        <span
          v-else
          class="text-gray-800 tabular-nums text-right break-all"
        >{{ row.value }}</span>
      </div>
    </div>

    <!-- Footer -->
    <p
      v-if="hasWeatherData"
      class="mt-3 text-xs text-gray-400"
    >
      Weather from
      <a
        href="https://open-meteo.com/"
        target="_blank"
        rel="noopener noreferrer"
        class="underline-offset-2 hover:text-gray-600 hover:underline"
      >Open-Meteo</a>
    </p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faPlay, faPause, faDownload, faArrowUpFromBracket, faCheck } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

import api from '@/services/api'
import { getAudioUrl } from '@/services/media'
import { useTimeFormat } from '@/composables/useTimeFormat'
import { useAudioTransport } from '@/composables/useAudioTransport'
import { useDetectionInfo } from '@/composables/useDetectionInfo'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import { computeSpectrogram, renderSpectrogramPixels } from '@/utils/spectrogram'
import { confidenceColorClass, confidencePercent, formatMetadataKey, formatMetadataValue } from '@/utils/format'
import { recordingShareUrl } from '@/utils/detectionLinks'
import Spinner from '@/components/Spinner.vue'

library.add(faPlay, faPause, faDownload, faArrowUpFromBracket, faCheck)

// Identifies the recording to load. Shared by the standalone detail page and the
// in-table modal, so it takes the species/id as props rather than reading the route.
const props = defineProps({
  name: {
    type: String,
    required: true
  },
  id: {
    type: [String, Number],
    required: true
  }
})

const { formatTime } = useTimeFormat()
const {
  formatTemperature,
  convertWindSpeed, convertPrecipitation, convertPressure,
  windSpeedUnit, precipitationUnit, pressureUnit,
  useMetricUnits
} = useUnitSettings()

// --- Data ---
const recording = ref(null)
const loading = ref(true)
const error = ref(false)

const fetchRecording = async () => {
  loading.value = true
  error.value = false
  try {
    const { data } = await api.get(`/bird/${props.name}/recording/${props.id}`)
    recording.value = data
  } catch {
    recording.value = null
    error.value = true
  } finally {
    loading.value = false
  }
}

// --- Derived metadata ---
const { hasWeatherData, weatherData, weatherDescription, filteredExtraData, hasFilteredExtraData } =
  useDetectionInfo(recording)
const hasMedia = computed(() => !!recording.value?.has_media)
const displayName = computed(
  () => recording.value?.display_common_name || recording.value?.common_name || ''
)
const audioUrl = computed(() => getAudioUrl(recording.value?.audio_filename))
const downloadName = computed(() => recording.value?.audio_filename || 'recording.mp3')

// --- Share: copy a permalink to this detection. common_name is the untranslated
// English key the share route needs (display_common_name is the localized label).
const { copied, copy } = useCopyFeedback()
const share = () => {
  const name = recording.value?.common_name
  if (!name || recording.value?.id == null) return
  copy(recordingShareUrl(name, recording.value.id))
}

const confidenceInt = computed(() => confidencePercent(recording.value?.confidence))
const confidenceColor = computed(() => confidenceColorClass(recording.value?.confidence))
const formattedTimestamp = computed(() => {
  const ts = recording.value?.timestamp
  if (!ts) return ''
  const d = new Date(ts)
  const datePart = isNaN(d.getTime())
    ? ts
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  return `${datePart} · ${formatTime(ts)}`
})

// --- Conditions: weather metric strip + extra metadata, rendered inline ---
// Each metric splits the formatted number from its unit so the unit can render
// smaller/muted; percentages keep their "%" attached. Only present fields show.
const weatherStats = computed(() => {
  const w = weatherData.value
  if (!w) return []
  const prec = useMetricUnits.value ? 1 : 2
  const stats = []
  if (w.humidity != null) stats.push({ label: 'Humidity', value: `${w.humidity}%`, unit: '' })
  if (w.wind != null) stats.push({ label: 'Wind', value: convertWindSpeed(w.wind).toFixed(1), unit: windSpeedUnit.value })
  if (w.cloud_cover != null) stats.push({ label: 'Clouds', value: `${w.cloud_cover}%`, unit: '' })
  if (w.precip != null) stats.push({ label: 'Precip', value: convertPrecipitation(w.precip).toFixed(prec), unit: precipitationUnit.value })
  // Pressure is hidden on the 2-col mobile grid so the strip stays a clean 2×2
  // (5 items would leave the last one orphaned in its own row); shown from sm up.
  if (w.pressure != null) stats.push({ label: 'Pressure', value: convertPressure(w.pressure).toFixed(prec), unit: pressureUnit.value, hideOnMobile: true })
  return stats
})
const formattedTemp = computed(() => formatTemperature(weatherData.value?.temp))

// Precompute metadata rows so the snake_case→Title-case key formatting and value
// stringify run only when the data changes — not on every frame the playback
// clock re-renders the view.
const metadataRows = computed(() =>
  Object.entries(filteredExtraData.value || {}).map(([key, value]) => ({
    key,
    label: formatMetadataKey(key),
    value: formatMetadataValue(value),
    // The eBird code links out to its species page on ebird.org.
    href: key === 'ebird_code' && value ? `https://ebird.org/species/${value}` : null
  }))
)

// --- Audio + spectrogram ---
const specWrap = ref(null)
const specCanvas = ref(null)
const audioEl = ref(null) // created imperatively (see loadAudio)
const audioState = ref('loading') // 'loading' | 'ready' | 'error'
const audioError = ref('') // message shown in the 'error' state

// Shared transport. The graph is built at load (works while the context is
// suspended); the first play just needs a user gesture to resume the context.
const { isPlaying, currentTime, duration, progressPercent, clock, togglePlay, seekToFraction } =
  useAudioTransport(audioEl, {
    onBeforePlay: async () => {
      if (audioCtx?.state === 'suspended') await audioCtx.resume()
    }
  })

// Web Audio graph + the cached filter-response overlay that shades the spectrogram.
let audioCtx = null
let mediaSource = null
let highpassNode = null
let gainNode = null
let objectUrl = null
let spec = null // computeSpectrogram() result
let specBaseCanvas = null // base spectrogram painted once; redraws just rescale it
let filterFreqs = null // bin centre frequencies (Hz), for getFrequencyResponse
let filterMag = null // scratch magnitude-response buffer
let filterPhase = null // scratch phase buffer (discarded)
let filterOverlay = null // 1×bins attenuation overlay drawn over the base

// Processing controls
const highpassHz = ref(0)
const gainDb = ref(0)
const highpassLabel = computed(() => (highpassHz.value > 0 ? `${highpassHz.value} Hz` : 'Off'))
const gainLabel = computed(() => `${gainDb.value > 0 ? '+' : ''}${gainDb.value} dB`)

// Fill fraction (0–100%) for the green portion of each slider track. Driven into
// the track gradient so the filled look is identical across browsers/platforms.
const highpassFill = computed(() => `${(highpassHz.value / 6000) * 100}%`)
const gainFill = computed(() => `${((gainDb.value + 12) / 36) * 100}%`)

const dbToGain = (db) => Math.pow(10, db / 20)

const loadAudio = async () => {
  if (typeof window === 'undefined' || !window.AudioContext) {
    audioError.value = 'Live audio analysis is not supported in this browser.'
    audioState.value = 'error'
    return
  }
  audioState.value = 'loading'
  audioError.value = ''
  try {
    const resp = await fetch(audioUrl.value)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const buf = await resp.arrayBuffer()

    // One context for both decoding and playback; starts suspended until play().
    audioCtx = new AudioContext()
    const audioBuffer = await audioCtx.decodeAudioData(buf.slice(0))
    duration.value = audioBuffer.duration

    // Mono mix for the spectrogram.
    const mono = audioBuffer.numberOfChannels > 1
      ? mixToMono(audioBuffer)
      : audioBuffer.getChannelData(0)
    spec = computeSpectrogram(mono, audioBuffer.sampleRate, { fftSize: 1024, hop: 256 })
    buildSpectrogramBase()
    drawSpectrogram()

    // Playback element fed from the same bytes (blob keeps it same-origin so the
    // MediaElementSource isn't muted by cross-origin rules).
    objectUrl = URL.createObjectURL(new Blob([buf]))
    const el = new Audio()
    el.src = objectUrl
    el.preload = 'auto'
    audioEl.value = el // useAudioTransport attaches its listeners off this ref

    // Build the graph now (silent while suspended) so the high-pass filter's
    // real frequency response can shade the spectrogram before first play.
    buildGraph()
    initFilterResponse()

    audioState.value = 'ready'
  } catch (e) {
    audioError.value = 'Could not load audio for analysis.'
    audioState.value = 'error'
    console.error('DetectionPlayer audio load failed:', e)
  }
}

const mixToMono = (audioBuffer) => {
  const n = audioBuffer.length
  const out = new Float32Array(n)
  for (let c = 0; c < audioBuffer.numberOfChannels; c++) {
    const ch = audioBuffer.getChannelData(c)
    for (let i = 0; i < n; i++) out[i] += ch[i]
  }
  const inv = 1 / audioBuffer.numberOfChannels
  for (let i = 0; i < n; i++) out[i] *= inv
  return out
}

const buildGraph = () => {
  if (mediaSource || !audioCtx || !audioEl.value) return
  mediaSource = audioCtx.createMediaElementSource(audioEl.value)
  highpassNode = audioCtx.createBiquadFilter()
  highpassNode.type = 'highpass'
  applyHighpass()
  gainNode = audioCtx.createGain()
  gainNode.gain.value = dbToGain(gainDb.value)
  mediaSource.connect(highpassNode).connect(gainNode).connect(audioCtx.destination)
}

const applyHighpass = () => {
  if (!highpassNode) return
  // A biquad at ~10 Hz is effectively a bypass; >0 engages the cutoff.
  highpassNode.frequency.value = highpassHz.value > 0 ? highpassHz.value : 10
}

// Shade the spectrogram with the filter's ACTUAL magnitude response (the biquad's
// 12 dB/oct slope), not a brick-wall guess — one filter spec drives both the
// audio and the picture. The overlay is a 1×bins alpha ramp; drawSpectrogram
// stretches it to a smooth vertical gradient.
const initFilterResponse = () => {
  if (!spec) return
  filterFreqs = new Float32Array(spec.bins)
  for (let b = 0; b < spec.bins; b++) filterFreqs[b] = b * spec.binHz
  filterMag = new Float32Array(spec.bins)
  filterPhase = new Float32Array(spec.bins)
  filterOverlay = document.createElement('canvas')
  filterOverlay.width = 1
  filterOverlay.height = spec.bins
  updateFilterOverlay()
}

const updateFilterOverlay = () => {
  if (!highpassNode || !spec || !filterFreqs) return
  highpassNode.getFrequencyResponse(filterFreqs, filterMag, filterPhase)
  const bins = spec.bins
  const img = new ImageData(1, bins)
  for (let r = 0; r < bins; r++) {
    const bin = bins - 1 - r // row 0 = top = high frequency
    const atten = 1 - Math.min(1, filterMag[bin]) // 0 in the passband, 1 fully cut
    img.data[r * 4 + 3] = Math.round(atten * 0.85 * 255) // black, variable alpha
  }
  filterOverlay.getContext('2d').putImageData(img, 0, 0)
}

watch(highpassHz, () => {
  applyHighpass()
  updateFilterOverlay()
  drawSpectrogram()
})
watch(gainDb, (db) => {
  if (gainNode) gainNode.gain.value = dbToGain(db)
})

// --- Spectrogram drawing ---
// Paint the (expensive) per-pixel pass once into an offscreen canvas. Redraws —
// on resize and on every high-pass slider tick — then only rescale this base and
// overlay the high-pass shading, so there's no per-pixel work on those paths.
const buildSpectrogramBase = () => {
  if (!spec) return
  const { data, width, height } = renderSpectrogramPixels(spec)
  specBaseCanvas = document.createElement('canvas')
  specBaseCanvas.width = width
  specBaseCanvas.height = height
  specBaseCanvas.getContext('2d').putImageData(new ImageData(data, width, height), 0, 0)
}

const drawSpectrogram = () => {
  const canvas = specCanvas.value
  const wrap = specWrap.value
  if (!canvas || !wrap || !specBaseCanvas) return

  const dpr = window.devicePixelRatio || 1
  const cssW = wrap.clientWidth || specBaseCanvas.width
  // Visual height is driven by the canvas's responsive Tailwind class
  // (h-[180px] by default, h-[270px] only when the viewport is ≥640px in both
  // width and height — so landscape phones, which are short, keep the compact
  // 180px). JS only matches the DPR backing-store resolution to whatever that
  // renders to.
  const cssH = canvas.clientHeight || 300
  canvas.width = Math.round(cssW * dpr)
  canvas.height = Math.round(cssH * dpr)

  const ctx = canvas.getContext('2d')
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(specBaseCanvas, 0, 0, canvas.width, canvas.height)

  // High-pass: dim each frequency row by the filter's real attenuation. The
  // 1×bins overlay stretches (with smoothing) into the filter's actual slope.
  if (highpassHz.value > 0 && filterOverlay) {
    ctx.drawImage(filterOverlay, 0, 0, canvas.width, canvas.height)
  }
}

// --- Seek by clicking the spectrogram (its x-axis is the audio timeline) ---
const onSeekPointer = (event) => {
  const wrap = specWrap.value
  if (!wrap) return
  const rect = wrap.getBoundingClientRect()
  if (!rect.width) return
  seekToFraction((event.clientX - rect.left) / rect.width)
}

// --- Resize: redraw the scaled spectrogram ---
let resizeTimer = null
const onResize = () => {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(drawSpectrogram, 150)
}

onMounted(async () => {
  await fetchRecording()
  if (hasMedia.value) {
    await nextTick() // let the canvas mount before we draw into it
    await loadAudio()
  }
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  // Transport listeners + rAF are torn down by useAudioTransport; here we stop
  // playback and release the audio resources this view owns.
  clearTimeout(resizeTimer)
  window.removeEventListener('resize', onResize)
  if (audioEl.value) audioEl.value.pause()
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  if (audioCtx && audioCtx.state !== 'closed') audioCtx.close()
})
</script>

<style scoped>
/* Range sliders — cross-browser so the track/thumb render the same on iOS Safari
   and desktop. Thin 4px track with the app's green fill up to the thumb (--fill)
   and a 16px green thumb with a white ring. Same base technique as Settings.vue;
   intentionally duplicated for now — if a third view needs this, promote it to a
   shared <RangeSlider> primitive. */
input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
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
</style>
