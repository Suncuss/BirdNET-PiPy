<template>
  <div class="flex flex-col items-center w-full max-w-3xl mx-auto p-4">
    <div class="bg-white rounded-lg shadow-md p-4 w-full max-w-4xl">
      <div
        v-if="isSafari"
        class="w-full h-32 mb-4 bg-gray-800 rounded-lg flex items-center justify-center"
      >
        <div class="text-center text-white">
          <div class="text-xl mb-2">
            🍎
          </div>
          <div class="text-sm">
            Live spectrogram not available in Safari
          </div>
          <div class="text-xs text-gray-400 mt-1">
            Audio plays normally, but live audio filters aren't available either
          </div>
        </div>
      </div>
      <canvas
        v-else
        ref="spectrogramCanvas"
        class="w-full h-48 mb-4 rounded-lg"
      />
      <div
        v-if="streams.length > 1"
        class="flex flex-wrap gap-2 mb-4"
      >
        <button
          v-for="s in streams"
          :key="s.source_id"
          type="button"
          class="inline-flex items-center px-2.5 py-0.5 rounded-full border text-xs font-medium transition-colors"
          :class="s.source_id === selectedSourceId
            ? 'border-blue-200 bg-blue-50 text-gray-800'
            : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'"
          :disabled="isLoading"
          @click="selectSourceById(s.source_id)"
        >
          {{ s.label || s.source_id }}
        </button>
      </div>
      <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-4">
        <button
          class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 flex items-center justify-center min-w-[120px] flex-shrink-0 disabled:bg-gray-400 disabled:cursor-not-allowed"
          :disabled="isLoading || !streamUrl || hasError"
          @click="toggleAudio"
        >
          <template v-if="isLoading">
            <Spinner class="w-4 h-4 mr-2 text-white" />
            Loading...
          </template>
          <template v-else>
            {{ isPlaying ? 'Stop' : 'Start' }} Audio
          </template>
        </button>

        <div class="text-right">
          <span
            class="text-sm break-words"
            :class="hasError ? 'text-amber-600 animate-pulse-fast' : 'text-gray-500'"
          >Status: {{ statusMessage }}</span>
          <div
            v-if="streams.length <= 1"
            class="hidden sm:block text-xs text-gray-400 mt-1"
          >
            <template v-if="streamDescription">
              {{ streamDescription }}
            </template>
            <template v-else>
              ⚠️ No stream available
            </template>
          </div>
        </div>
      </div>

      <!-- Audio filters (live, non-destructive) — same high-pass + gain controls
           as the detection detail player. The high-pass also shapes the live
           spectrogram; gain only changes what you hear. Hidden on Safari: it
           doesn't route the live <audio> stream through Web Audio, so the filter
           graph carries no signal (same reason the spectrogram is unavailable). -->
      <div
        v-if="streamUrl && !isSafari"
        class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 mb-4 px-5 py-3 sm:px-[22px] bg-gray-50 rounded-xl"
      >
        <!-- High-pass -->
        <div>
          <div class="flex justify-between items-center text-[13px] mb-2">
            <label
              for="live-highpass"
              class="text-gray-600"
            >High-pass filter</label>
            <span class="font-medium tabular-nums text-gray-800">{{ highpassLabel }}</span>
          </div>
          <input
            id="live-highpass"
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
              for="live-gain"
              class="text-gray-600"
            >Gain</label>
            <span class="font-medium tabular-nums text-gray-800">{{ gainLabel }}</span>
          </div>
          <input
            id="live-gain"
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

      <audio
        ref="audioElement"
        :src="streamUrl"
        preload="none"
        crossorigin="anonymous"
        @error="handleAudioError"
        @stalled="handleAudioBuffering"
        @waiting="handleAudioBuffering"
        @playing="handleAudioPlaying"
        @ended="handleAudioEnded"
      />
      <BirdDetectionList :detections="birdDetections" />
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { io } from 'socket.io-client'
import BirdDetectionList from './BirdDetectionList.vue'
import Spinner from '@/components/Spinner.vue'
import api from '@/services/api'
import { SOCKET_PATH } from '@/services/baseUrl'
import { spectrogramColor } from '@/utils/spectrogram'

export default {
  name: 'LiveFeed',
  components: {
    BirdDetectionList,
    Spinner
  },
  setup() {
    const spectrogramCanvas = ref(null)
    const audioElement = ref(null)
    const isPlaying = ref(false)
    const isLoading = ref(false)
    const hasError = ref(false)
    const statusMessage = ref('Click Start to begin')
    const birdDetections = ref([])
    const streams = ref([])
    const selectedSourceId = ref('')

    // Live, non-destructive processing controls (mirrors DetectionPlayer.vue).
    const highpassHz = ref(0)
    const gainDb = ref(0)
    const highpassLabel = computed(() => (highpassHz.value > 0 ? `${highpassHz.value} Hz` : 'Off'))
    const gainLabel = computed(() => `${gainDb.value > 0 ? '+' : ''}${gainDb.value} dB`)
    // Fill fraction (0–100%) for the green portion of each slider track.
    const highpassFill = computed(() => `${(highpassHz.value / 6000) * 100}%`)
    const gainFill = computed(() => `${((gainDb.value + 12) / 36) * 100}%`)

    const currentSource = computed(() =>
      streams.value.find(s => s.source_id === selectedSourceId.value)
    )
    const streamUrl = computed(() => currentSource.value?.url || '')
    const streamDescription = computed(() => currentSource.value?.label || '')

    let audioContext, analyser, source, highpassNode, gainNode, dataArray, animationId
    let canvasCtx, canvasWidth, canvasHeight
    // Number of low-frequency FFT bins actually drawn — capped to ~12 kHz so the
    // live spectrogram's vertical range matches the detection-detail player.
    let spectrogramBins

    // Top of the displayed frequency range. Birds sit in the low end; the upper
    // half of the full 0–22 kHz analyser range is mostly empty, so cap it here
    // to match the detection-detail spectrogram (@/utils/spectrogram).
    const SPECTROGRAM_MAX_HZ = 12000
    let socket
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)

    // Live-feed auto-reconnect (GH #56): an unstable RTSP source (e.g. a Wyze
    // camera) can end its audio track every ~20s, which makes the Icecast mount
    // briefly disappear. Without this the user had to press Start again after
    // every drop. userWantsPlay tracks intent so reconnects only run while the
    // user expects audio; the attempt counter resets on a successful resume.
    let userWantsPlay = false
    let reconnectTimer = null
    let reconnectAttempts = 0
    let errorClearTimer = null
    const MAX_RECONNECT_ATTEMPTS = 6
    const RECONNECT_BASE_MS = 2000
    const RECONNECT_MAX_MS = 10000

    const dbToGain = (db) => Math.pow(10, db / 20)

    const applyHighpass = () => {
      if (!highpassNode) return
      // A biquad at ~10 Hz is effectively a bypass; >0 engages the cutoff.
      highpassNode.frequency.value = highpassHz.value > 0 ? highpassHz.value : 10
    }

    const initAudioContext = async () => {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 44100
        });
        analyser = audioContext.createAnalyser();
        // Tuned to match the detection-detail spectrogram (@/utils/spectrogram):
        // same 1024-pt FFT, light temporal smoothing for crispness without
        // flicker, and an ~80 dB display window. The reference stays fixed
        // (absolute dB) rather than per-clip peak — per-clip normalization is
        // impossible on a live stream, and a fixed reference keeps brightness
        // stable over time.
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.25;
        // 80 dB window (matches the detail view's floorDb) positioned so a
        // typical loud call (~-30 dBFS) reaches full brightness.
        analyser.minDecibels = -110;
        analyser.maxDecibels = -30;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        const binHz = audioContext.sampleRate / analyser.fftSize;
        spectrogramBins = Math.min(
          analyser.frequencyBinCount,
          Math.round(SPECTROGRAM_MAX_HZ / binHz)
        );
        audioElement.value.crossOrigin = 'anonymous';
        source = audioContext.createMediaElementSource(audioElement.value);

        // High-pass + gain inserted into the chain. The analyser is a transparent
        // pass-through tapping the post-high-pass signal, so the live spectrogram
        // reflects the filter but not gain (gain only changes what you hear):
        //   source → highpass → analyser → gain → destination
        highpassNode = audioContext.createBiquadFilter();
        highpassNode.type = 'highpass';
        applyHighpass();
        gainNode = audioContext.createGain();
        gainNode.gain.value = dbToGain(gainDb.value);

        source.connect(highpassNode);
        highpassNode.connect(analyser);
        analyser.connect(gainNode);
        gainNode.connect(audioContext.destination);
      }
    }

    watch(highpassHz, applyHighpass)
    watch(gainDb, (db) => {
      if (gainNode) gainNode.gain.value = dbToGain(db)
    })

    const showError = (message, duration = 4000) => {
      statusMessage.value = message
      hasError.value = true
      // Track the clear timer so re-entry doesn't leak timers and onUnmounted
      // can cancel a pending write to hasError after teardown.
      if (errorClearTimer) {
        clearTimeout(errorClearTimer)
      }
      errorClearTimer = setTimeout(() => {
        hasError.value = false
        errorClearTimer = null
      }, duration)
    }

    const stopPlayback = () => {
      isPlaying.value = false
      if (animationId) {
        cancelAnimationFrame(animationId)
        animationId = null
      }
    }

    const probeStreamError = async () => {
      try {
        const response = await fetch(streamUrl.value, { method: 'HEAD' })
        console.error(`[LiveFeed] Stream probe: HTTP ${response.status} from ${streamUrl.value}`)
        if (response.status === 404 || response.status === 403) {
          return 'Audio stream is not available'
        } else if (response.status === 401) {
          return 'Authentication required'
        } else if (response.status >= 500) {
          return 'Stream server error'
        }
        return 'Could not start audio playback'
      } catch (fetchError) {
        console.error(`[LiveFeed] Stream probe failed: ${fetchError.message}`)
        return 'Could not reach stream server'
      }
    }

    // silent=true suppresses the hard error banner so background reconnect
    // attempts don't flash "stream not available" on every try — scheduleReconnect
    // owns the user-facing "reconnecting (N/6)" / give-up messaging instead.
    const startAudio = async (silent = false) => {
      try {
        isLoading.value = true
        statusMessage.value = 'Initializing audio...'

        initAudioContext()
        // Force a fresh connection so Start jumps to the live head instead of buffered audio.
        // Reset src to force a new HTTP connection (load() alone reuses cached connection)
        audioElement.value.src = ''
        audioElement.value.src = streamUrl.value
        audioElement.value.load()
        await audioContext.resume()
        await audioElement.value.play()
        statusMessage.value = 'Icecast stream connected'
        return true
      } catch (error) {
        console.error(`[LiveFeed] Playback failed: ${error.name}: ${error.message}`)
        // Check if it might be an auth error (nginx returns 401 for unauthenticated requests)
        if (error.name === 'NotAllowedError' || error.message?.includes('401')) {
          if (!silent) showError('Authentication required')
          // Always surface auth so the login flow can run — retrying won't fix it.
          window.dispatchEvent(new Event('auth:required'))
        } else {
          // Probe the stream URL to diagnose why playback failed
          const userMessage = await probeStreamError()
          if (!silent) showError(userMessage)
          if (userMessage === 'Authentication required') {
            window.dispatchEvent(new Event('auth:required'))
          }
        }
        return false
      } finally {
        isLoading.value = false
      }
    }

    const stopAudio = async () => {
      // Explicit stop: drop the intent and cancel any pending reconnect.
      userWantsPlay = false
      cancelReconnect()
      try {
        await audioElement.value.pause()
        statusMessage.value = 'Audio stopped'
      } catch (error) {
        console.error(`[LiveFeed] Stop failed: ${error.message}`)
        statusMessage.value = 'Error stopping audio'
      }
    }

    const handleAudioError = (event) => {
      // Ignore errors when idle (e.g., empty src on page load). Keep handling them
      // while a reconnect is pending (userWantsPlay) so a flapping mount recovers.
      if (!isPlaying.value && !isLoading.value && !userWantsPlay) {
        return
      }

      const error = event.target.error
      const errorCodes = {
        [MediaError.MEDIA_ERR_ABORTED]: 'MEDIA_ERR_ABORTED',
        [MediaError.MEDIA_ERR_NETWORK]: 'MEDIA_ERR_NETWORK',
        [MediaError.MEDIA_ERR_DECODE]: 'MEDIA_ERR_DECODE',
        [MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED]: 'MEDIA_ERR_SRC_NOT_SUPPORTED',
      }
      console.error(
        `[LiveFeed] Audio error: code=${error?.code} (${errorCodes[error?.code] || 'unknown'}), message="${error?.message || 'none'}", src="${streamUrl.value}"`
      )

      let errorMessage = 'Audio stream error'
      if (error) {
        switch (error.code) {
          case MediaError.MEDIA_ERR_ABORTED:
            errorMessage = 'Audio stream was interrupted'
            break
          case MediaError.MEDIA_ERR_NETWORK:
            errorMessage = 'Could not reach audio stream'
            break
          case MediaError.MEDIA_ERR_DECODE:
            errorMessage = 'Audio stream interrupted'
            break
          case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMessage = 'Audio stream is not available'
            break
        }
      }

      isLoading.value = false
      stopPlayback()
      // A drop while the user wants audio is usually a transient RTSP/Icecast flap
      // (GH #56) — try to reconnect instead of giving up. Show the error otherwise.
      if (userWantsPlay) {
        scheduleReconnect()
      } else {
        showError(errorMessage)
      }
    }

    const handleAudioBuffering = () => {
      console.log('[LiveFeed] Audio stream buffering')
      if (isPlaying.value) {
        statusMessage.value = 'Stream buffering...'
      }
    }

    const handleAudioPlaying = () => {
      // A successful resume — whether ours or a browser-driven recovery — clears
      // any pending reconnect (so a stale timer can't tear down a stream that has
      // already come back) and the consecutive-failure budget (so a stream that
      // flaps every ~20s but recovers never exhausts its reconnect attempts).
      cancelReconnect()
      if (!isPlaying.value && userWantsPlay) {
        // The element recovered on its own before our timer fired — reflect the
        // live state and resume the spectrogram so the UI matches reality.
        isPlaying.value = true
        if (!isSafari && !animationId) {
          drawSpectrogram()
        }
      }
      if (isPlaying.value) {
        statusMessage.value = 'Icecast stream connected'
      }
    }

    const handleAudioEnded = () => {
      console.log('[LiveFeed] Audio stream ended')
      stopPlayback()
      if (userWantsPlay) {
        scheduleReconnect()
      } else {
        statusMessage.value = 'Stream ended - click Start to reconnect'
      }
    }

    const drawSpectrogram = () => {
      animationId = requestAnimationFrame(drawSpectrogram)

      analyser.getByteFrequencyData(dataArray)

      let imageData = canvasCtx.getImageData(1, 0, canvasWidth - 1, canvasHeight)
      canvasCtx.fillRect(0, 0, canvasWidth, canvasHeight)
      canvasCtx.putImageData(imageData, 0, 0)

      // Draw only the bins up to SPECTROGRAM_MAX_HZ, stretched across the full
      // canvas height so the visible range is 0–12 kHz (matches the detail view).
      const bins = spectrogramBins || dataArray.length
      for (let i = 0; i < bins; i++) {
        // Map the analyser's 0–255 intensity through the same green colormap as
        // the detection-detail spectrogram so the two read as one instrument.
        const [r, g, b] = spectrogramColor(dataArray[i] / 255)
        canvasCtx.beginPath()
        canvasCtx.strokeStyle = `rgb(${r}, ${g}, ${b})`
        canvasCtx.moveTo(canvasWidth - 1, canvasHeight - (i * canvasHeight / bins))
        canvasCtx.lineTo(canvasWidth - 1, canvasHeight - ((i + 1) * canvasHeight / bins))
        canvasCtx.stroke()
      }
    }

    const cancelReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      reconnectAttempts = 0
    }

    // Try to (re)connect playback. On success resume the spectrogram and mark playing.
    const attemptPlay = async (silent = false) => {
      const success = await startAudio(silent)
      if (success) {
        reconnectAttempts = 0
        if (!isSafari && !animationId) {
          drawSpectrogram()
        }
        isPlaying.value = true
      }
      return success
    }

    // Schedule a bounded, backed-off reconnect while the user still wants audio.
    // Bridges the brief Icecast mount gap when an unstable RTSP source drops (GH #56).
    const scheduleReconnect = () => {
      if (!userWantsPlay || reconnectTimer) {
        return
      }
      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        userWantsPlay = false
        stopPlayback()
        showError('Audio source keeps dropping — click Start to retry', 6000)
        return
      }
      reconnectAttempts += 1
      const delay = Math.min(RECONNECT_BASE_MS * reconnectAttempts, RECONNECT_MAX_MS)
      statusMessage.value = `Stream dropped — reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null
        if (!userWantsPlay) {
          return
        }
        const success = await attemptPlay(true)
        if (!success) {
          scheduleReconnect()
        }
      }, delay)
    }

    const startPlayback = async () => {
      userWantsPlay = true
      cancelReconnect()
      // Silent even on the first try: a transient failure rolls straight into
      // the bounded reconnect loop, which surfaces status (and any give-up error).
      const success = await attemptPlay(true)
      if (!success) {
        scheduleReconnect()
      }
    }

    const toggleAudio = async () => {
      if (isPlaying.value) {
        stopPlayback()
        await stopAudio()
      } else {
        await startPlayback()
      }
    }

    const selectSourceById = async (sourceId) => {
      if (sourceId === selectedSourceId.value) return
      if (!streams.value.some(s => s.source_id === sourceId)) return
      const wasPlaying = isPlaying.value
      if (wasPlaying) {
        stopPlayback()
        await stopAudio()
      }
      selectedSourceId.value = sourceId
      if (wasPlaying) {
        await startPlayback()
      }
    }

    const fetchStreamConfig = async () => {
      try {
        const { data: config } = await api.get('/stream/config')
        streams.value = config.streams || []
        selectedSourceId.value = streams.value[0]?.source_id || ''

        if (!streamUrl.value) {
          statusMessage.value = 'No audio stream configured'
        }
      } catch (error) {
        console.error(`[LiveFeed] Stream config fetch failed: ${error.message}`)
        showError('Could not load stream settings')
      }
    }

    const initWebSocket = () => {
      socket = io({ path: SOCKET_PATH })

      socket.on('connect', () => {
        console.log('[LiveFeed] WebSocket connected')
      })

      socket.on('disconnect', (reason) => {
        console.log(`[LiveFeed] WebSocket disconnected: ${reason}`)
      })

      socket.on('bird_detected', (detection) => {
        
        // Find existing detection for this bird species
        const existingIndex = birdDetections.value.findIndex(
          d => d.common_name === detection.common_name
        )
        
        if (existingIndex !== -1) {
          // Bird already exists - update it and move to top
          const existingDetection = birdDetections.value[existingIndex]
          
          // Update the existing detection with new data
          existingDetection.timestamp = detection.timestamp
          existingDetection.confidence = detection.confidence
          existingDetection.scientific_name = detection.scientific_name
          existingDetection.bird_song_file_name = detection.bird_song_file_name
          existingDetection.spectrogram_file_name = detection.spectrogram_file_name
          existingDetection.justUpdated = true
          
          // Remove from current position and move to top
          birdDetections.value.splice(existingIndex, 1)
          birdDetections.value.unshift(existingDetection)
          
          // Clear the highlight after animation
          setTimeout(() => {
            existingDetection.justUpdated = false
          }, 1000)
        } else {
          // New bird - add to top
          detection.justUpdated = false
          birdDetections.value.unshift(detection)
        }
        
        // Keep only the most recent 8 unique birds
        if (birdDetections.value.length > 8) {
          birdDetections.value = birdDetections.value.slice(0, 8)
        }
      })
    }

    onMounted(async () => {
      // Only initialize canvas for non-Safari browsers
      if (!isSafari) {
        const canvas = spectrogramCanvas.value
        canvasCtx = canvas.getContext('2d', { willReadFrequently: true })
        canvasWidth = canvas.width = canvas.offsetWidth
        canvasHeight = canvas.height = canvas.offsetHeight

        // Idle background before playback: a near-floor green pulled from the
        // bottom of the spectrogram colormap, so the empty canvas matches how a
        // quiet stream renders (was a leftover dark purple from the old rainbow
        // map). Tune the 0.06 if it reads too bright/dark.
        const [ir, ig, ib] = spectrogramColor(0.06)
        canvasCtx.fillStyle = `rgb(${ir}, ${ig}, ${ib})`
        canvasCtx.fillRect(0, 0, canvasWidth, canvasHeight)
      }

      // Fetch stream configuration first
      await fetchStreamConfig()
      
      initWebSocket()
    })

    onUnmounted(() => {
      userWantsPlay = false
      cancelReconnect()
      if (errorClearTimer) {
        clearTimeout(errorClearTimer)
        errorClearTimer = null
      }

      if (animationId) {
        cancelAnimationFrame(animationId)
        animationId = null
      }

      if (source) {
        source.disconnect()
        source = null
      }
      if (highpassNode) {
        highpassNode.disconnect()
        highpassNode = null
      }
      if (gainNode) {
        gainNode.disconnect()
        gainNode = null
      }
      if (analyser) {
        analyser.disconnect()
        analyser = null
      }

      if (audioElement.value) {
        audioElement.value.pause()
        audioElement.value.src = ''
        audioElement.value.load()
      }

      dataArray = null
      canvasCtx = null

      if (audioContext) {
        audioContext.close()
        audioContext = null
      }

      isPlaying.value = false

      if (socket) {
        socket.disconnect()
        socket = null
      }
    })

    return {
      spectrogramCanvas,
      audioElement,
      isPlaying,
      isLoading,
      hasError,
      statusMessage,
      toggleAudio,
      birdDetections,
      streams,
      selectedSourceId,
      streamUrl,
      streamDescription,
      highpassHz,
      gainDb,
      highpassLabel,
      gainLabel,
      highpassFill,
      gainFill,
      isSafari,
      selectSourceById,
      handleAudioError,
      handleAudioBuffering,
      handleAudioPlaying,
      handleAudioEnded
    }
  }
}
</script>

<style scoped>
.animate-pulse-fast {
  animation: pulse-error 2s ease-in-out 2;
}

@keyframes pulse-error {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}

/* Range sliders — cross-browser so the track/thumb render the same on iOS Safari
   and desktop. Thin 4px track with the app's green fill up to the thumb (--fill)
   and a 16px green thumb with a white ring. Same primitive as DetectionPlayer.vue
   and Settings.vue — if this needs to change in more than one place, promote it to
   a shared <RangeSlider> component. */
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
