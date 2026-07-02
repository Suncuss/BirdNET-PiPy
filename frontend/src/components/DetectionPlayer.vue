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
          <Spinner class="h-5 w-5 text-green-600" />
          <span class="ml-2">Analyzing audio…</span>
        </div>
        <div
          v-else-if="audioState === 'error'"
          class="absolute inset-0 flex items-center justify-center text-gray-300 text-sm px-4 text-center"
        >
          {{ audioError }}
        </div>
      </div>

      <!-- Analysis windows: which 3s slice of the clip the model flagged.
           Width-aligned with the spectrogram above (both span the container),
           so each tile sits under the audio it covers. Hidden whenever the
           clip layout can't be derived (see computeAnalysisSegments). -->
      <div
        v-if="analysisSegments.length"
        class="flex h-[14px] mt-1.5 rounded-md overflow-hidden"
        role="group"
        aria-label="Analysis windows"
      >
        <button
          v-for="seg in analysisSegments"
          :key="seg.start"
          type="button"
          class="relative min-w-0 border-r last:border-r-0 border-white transition-colors"
          :class="seg.tileClass"
          :style="seg.widthStyle"
          :title="seg.title"
          :aria-label="seg.title"
          @click="seekTo(seg.start)"
        >
          <span
            v-if="seg.role !== 'context'"
            class="absolute inset-0 flex items-center justify-center text-[9px] font-semibold uppercase tracking-wider pointer-events-none"
            :class="seg.textClass"
          >Detected</span>
        </button>
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
              : shareFailed
                ? 'border-red-500 text-red-600 bg-red-50'
                : 'border-gray-200 bg-white text-gray-700 hover:border-green-600 hover:text-green-600'"
            :title="copied ? 'Link copied' : shareFailed ? 'Couldn’t create share link — try again' : 'Copy share link'"
            @click="share"
          >
            <font-awesome-icon
              :icon="copied ? ['fas', 'check'] : ['fas', 'arrow-up-from-bracket']"
              class="h-3.5 w-3.5"
            />
            <span class="hidden sm:inline">{{ copied ? 'Copied' : shareFailed ? 'Failed' : 'Share' }}</span>
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
        <RangeSlider
          v-model="highpassHz"
          :min="0"
          :max="6000"
          :step="50"
          label="High-pass filter"
          :display-value="highpassLabel"
          input-id="highpass"
          aria-label="High-pass cutoff frequency"
        />

        <RangeSlider
          v-model="gainDb"
          :min="-12"
          :max="24"
          :step="1"
          label="Gain"
          :display-value="gainLabel"
          input-id="gain"
          aria-label="Playback gain"
        />
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
import { useAuth } from '@/composables/useAuth'
import { getAudioUrl } from '@/services/media'
import { useTimeFormat } from '@/composables/useTimeFormat'
import { useAudioBufferTransport } from '@/composables/useAudioBufferTransport'
import { useDetectionInfo } from '@/composables/useDetectionInfo'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import {
  computeSpectrogram,
  computeBaseBrightness,
  buildSpectrogramRgbaLut,
  spectrogramFilterRowOffsets,
  colorizeBrightness
} from '@/utils/spectrogram'
import { confidenceColorClass, confidencePercent, formatConfidence, formatMetadataKey, formatMetadataValue, progressPercentString } from '@/utils/format'
import { computeAnalysisSegments } from '@/utils/analysisSegments'
import { declarePlaybackAudioSession } from '@/utils/audioSession'
import { recordingShareUrl } from '@/utils/detectionLinks'
import Spinner from '@/components/Spinner.vue'
import RangeSlider from '@/components/RangeSlider.vue'

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
  },
  // Present when opened from a share link (?s=). Authorizes this one detection
  // and its media even on a private station (public access off).
  shareToken: {
    type: String,
    default: ''
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
    const url = `/bird/${props.name}/recording/${props.id}`
    const { data } = props.shareToken
      ? await api.get(url, { params: { s: props.shareToken } })
      : await api.get(url)
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
// A share-link viewer authorizes media with the share token (works even on a
// private station). We ALSO pass the payload's per-file signature when present,
// so an expired/tampered token falls back to the signature on a public-access
// station instead of breaking the audio outright.
const mediaQuery = computed(() => {
  const sig = recording.value?.audio_sig || ''
  if (!props.shareToken) return sig
  const tokenParam = `s=${encodeURIComponent(props.shareToken)}`
  return sig ? `${tokenParam}&${sig}` : tokenParam
})
const audioUrl = computed(() => getAudioUrl(recording.value?.audio_filename, mediaQuery.value))
const downloadName = computed(() => recording.value?.audio_filename || 'recording.mp3')

// --- Share: copy a link to this detection. common_name is the untranslated
// English key the share route needs (display_common_name is the localized label).
const { isAuthenticated } = useAuth()
const { copied, copy } = useCopyFeedback()
const shareFailed = ref(false)

const share = async () => {
  const name = recording.value?.common_name
  const id = recording.value?.id
  if (!name || id == null) return
  shareFailed.value = false
  // window.location may be the table URL (in-table modal), so we never reuse
  // it — the permalink is always rebuilt via recordingShareUrl.
  // Anonymous: copy a permalink carrying any token we arrived with (it keeps
  // the recipient authorized even on a private station).
  if (!isAuthenticated.value) {
    copy(recordingShareUrl(name, id, props.shareToken))
    return
  }
  // Owner: mint a scoped token so the recipient sees only this one detection.
  try {
    const { data } = await api.post(`/detections/${id}/share`)
    copy(recordingShareUrl(name, id, data.token))
  } catch {
    // Don't fake success with a dead link — surface the failure.
    shareFailed.value = true
  }
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
const audioState = ref('loading') // 'loading' | 'ready' | 'error'
const audioError = ref('') // message shown in the 'error' state

// Playback transport. We play the decoded AudioBuffer through an
// AudioBufferSourceNode rather than routing an <audio> element through
// createMediaElementSource: on WebKit that bridge stalls once at startup,
// glitching both the audio and the playhead in the first second (see
// useAudioBufferTransport). configure() is called from loadAudio once the
// buffer + filter chain exist.
const { isPlaying, currentTime, duration, progressPercent, clock, togglePlay, seekTo, seekToFraction, configure: configureTransport } =
  useAudioBufferTransport()

// --- Analysis-window bar: where in the clip the model flagged the bird ---
// Derived from data the payload already carries (timestamp − group_timestamp,
// overlap) plus the decoded duration; empty until the audio is ready. Migrated
// BirdNET-Pi rows are excluded — their clips were extracted by another tool,
// so the context-chunk layout this derivation assumes doesn't hold. Tile
// widths and titles are precomputed here so they don't rebuild on every frame
// the playback clock re-renders the view (same reason as metadataRows).
// Per-role presentation for the analysis-window bar tiles. Every detected
// window (this row's and its siblings') is the same green — only the tooltip
// distinguishes them; context audio stays gray.
// green-600 matches the play button — the view's primary green — so the bar
// reads as one system with the transport rather than a second, lighter green.
const DETECTED_TILE = { tile: 'bg-green-600 hover:bg-green-700', text: 'text-white' }
const SEGMENT_ROLES = {
  primary: { ...DETECTED_TILE, label: () => 'This detection' },
  sibling: {
    ...DETECTED_TILE,
    label: (seg) => {
      const pct = formatConfidence(seg.confidence)
      return `Also detected in this recording${pct ? ` · ${pct}` : ''}`
    }
  },
  context: { tile: 'bg-gray-200 hover:bg-gray-300', text: '', label: () => 'Context audio' }
}

const analysisSegments = computed(() => {
  const r = recording.value
  if (!r || !duration.value || r.extra?.original_file_name) return []
  return computeAnalysisSegments({
    timestamp: r.timestamp,
    groupTimestamp: r.group_timestamp,
    overlap: r.overlap,
    duration: duration.value,
    // Sibling windows of the same species in the same source recording — the
    // bar labels every window that fired, not just this row's (the display
    // dedup collapses those rows into the one being viewed).
    groupDetections: r.group_detections
  }).map(seg => {
    const role = SEGMENT_ROLES[seg.role]
    return {
      ...seg,
      widthStyle: { width: progressPercentString(seg.end - seg.start, duration.value) },
      tileClass: role.tile,
      textClass: role.text,
      title: `${role.label(seg)} · ${clock(seg.start)}–${clock(seg.end)}`
    }
  })
})

// Web Audio graph + the offscreen spectrogram base that the high-pass re-colours.
// The persistent chain is highpass -> gain -> destination; the transport's
// per-play AudioBufferSourceNode connects into highpassNode.
let audioCtx = null
let audioBuffer = null // decoded clip, played by the transport
let highpassNode = null
let gainNode = null
let spec = null // computeSpectrogram() result
let specBase = null // per-pixel brightness bytes (computeBaseBrightness), computed once
let specLut = null // 0–255 → RGBA colormap LUT
let specBaseCanvas = null // offscreen base at native frames×bins, re-coloured on filter change
let baseImageData = null // reusable ImageData backing specBaseCanvas
let rowOffsets = null // per-row brightness attenuation (≤ 0) from the high-pass response
let filterFreqs = null // bin centre frequencies (Hz), for getFrequencyResponse
let filterMag = null // scratch magnitude-response buffer
let filterPhase = null // scratch phase buffer (discarded)
let repaintRaf = null // coalesces slider-driven re-colours to one per frame

// Processing controls
const highpassHz = ref(0)
const gainDb = ref(0)
const highpassLabel = computed(() => (highpassHz.value > 0 ? `${highpassHz.value} Hz` : 'Off'))
const gainLabel = computed(() => `${gainDb.value > 0 ? '+' : ''}${gainDb.value} dB`)

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
    // Playback goes through the Web Audio graph (no <audio> element), which the
    // iOS mute switch silences unless a 'playback' session is declared.
    declarePlaybackAudioSession()
    audioBuffer = await audioCtx.decodeAudioData(buf)

    // Mono mix for the spectrogram.
    const mono = audioBuffer.numberOfChannels > 1
      ? mixToMono(audioBuffer)
      : audioBuffer.getChannelData(0)
    spec = computeSpectrogram(mono, audioBuffer.sampleRate, { fftSize: 1024, hop: 256 })

    // Build the filter chain now (silent while suspended) so the high-pass
    // filter's real frequency response is available to shade the spectrogram
    // before first play. Done before the base is painted so the initial image
    // already reflects any engaged high-pass (picture and audio stay in step).
    buildGraph()
    initFilterResponse()

    buildSpectrogramBase()
    drawSpectrogram()

    // Wire playback: an AudioBufferSourceNode feeds the filter chain, and the
    // playhead is derived from audioCtx.currentTime.
    configureTransport({ context: audioCtx, buffer: audioBuffer, destination: highpassNode })

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
  if (highpassNode || !audioCtx) return
  highpassNode = audioCtx.createBiquadFilter()
  highpassNode.type = 'highpass'
  applyHighpass()
  gainNode = audioCtx.createGain()
  gainNode.gain.value = dbToGain(gainDb.value)
  highpassNode.connect(gainNode).connect(audioCtx.destination)
}

const applyHighpass = () => {
  if (!highpassNode) return
  // A biquad at ~10 Hz is effectively a bypass; >0 engages the cutoff.
  highpassNode.frequency.value = highpassHz.value > 0 ? highpassHz.value : 10
}

// Allocate the scratch buffers for the biquad's frequency response (bin centre
// frequencies + magnitude/phase outputs). The magnitude response — the filter's
// ACTUAL 12 dB/oct slope, not a brick-wall guess — is what dims the spectrogram,
// so one filter spec drives both the audio and the picture (see repaintBase).
const initFilterResponse = () => {
  if (!spec) return
  filterFreqs = new Float32Array(spec.bins)
  for (let b = 0; b < spec.bins; b++) filterFreqs[b] = b * spec.binHz
  filterMag = new Float32Array(spec.bins)
  filterPhase = new Float32Array(spec.bins)
}

// Per-row brightness attenuation (≤ 0) for the current high-pass setting, read
// from the biquad's real magnitude response and mapped into the spectrogram's dB
// window — so a cut row simply walks down the green colormap, the same truthful
// effect LiveFeed's analyser shows by sitting after the filter. At Off, the
// offsets are zero and the base reproduces the raw clip.
const computeRowOffsets = () => {
  if (!rowOffsets) return
  if (highpassHz.value > 0 && highpassNode && filterFreqs) {
    highpassNode.getFrequencyResponse(filterFreqs, filterMag, filterPhase)
    spectrogramFilterRowOffsets(filterMag, rowOffsets)
  } else {
    rowOffsets.fill(0)
  }
}

// Re-colour the offscreen base from the current high-pass response. Cheap enough
// to run on every slider tick: an integer add + LUT lookup per pixel, no log/pow.
const repaintBase = () => {
  if (!specBase || !baseImageData || !specBaseCanvas) return
  computeRowOffsets()
  colorizeBrightness(specBase, rowOffsets, specLut, baseImageData.data)
  specBaseCanvas.getContext('2d').putImageData(baseImageData, 0, 0)
}

// Coalesce rapid slider input (the range fires on every value) into one
// re-colour + redraw per animation frame.
const scheduleRepaint = () => {
  if (repaintRaf != null) return
  repaintRaf = requestAnimationFrame(() => {
    repaintRaf = null
    repaintBase()
    drawSpectrogram()
  })
}

watch(highpassHz, () => {
  applyHighpass() // audio: immediate
  scheduleRepaint() // picture: coalesced to one redraw per frame
})
watch(gainDb, (db) => {
  if (gainNode) gainNode.gain.value = dbToGain(db)
})

// --- Spectrogram drawing ---
// Reduce the clip to per-pixel brightness bytes once (the expensive log-domain
// pass), then keep an offscreen base canvas at native resolution. The high-pass
// re-colours this base in place (repaintBase); resize just rescales it onto the
// visible canvas. Painted initially unfiltered (rowOffsets all zero).
const buildSpectrogramBase = () => {
  if (!spec) return
  specBase = computeBaseBrightness(spec)
  specLut = buildSpectrogramRgbaLut()
  rowOffsets = new Int16Array(specBase.height)
  baseImageData = new ImageData(specBase.width, specBase.height)
  specBaseCanvas = document.createElement('canvas')
  specBaseCanvas.width = specBase.width
  specBaseCanvas.height = specBase.height
  repaintBase()
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
  // The high-pass attenuation is already baked into specBaseCanvas (repaintBase),
  // so this is a straight rescale of the post-filter image.
  ctx.drawImage(specBaseCanvas, 0, 0, canvas.width, canvas.height)
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
  // The transport stops its own source + rAF via its onUnmounted; here we just
  // release the audio resources this view owns. Closing the context also
  // silences anything still connected.
  clearTimeout(resizeTimer)
  if (repaintRaf != null) cancelAnimationFrame(repaintRaf)
  window.removeEventListener('resize', onResize)
  if (audioCtx && audioCtx.state !== 'closed') audioCtx.close()
})
</script>
