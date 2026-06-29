<template>
  <div class="flex flex-col items-center w-full max-w-3xl mx-auto p-2 sm:p-4">
    <div class="bg-white rounded-lg shadow-md p-3 sm:p-4 w-full max-w-4xl">
      <!-- Degraded fallback (no live Web Audio graph): only Safari versions where
           the WASM decoder can't load. Everywhere else the canvas below renders,
           including Safari via the decoded path. -->
      <div
        v-if="!showProcessing"
        class="w-full h-32 mb-3 sm:mb-4 bg-gray-800 rounded-lg flex items-center justify-center"
      >
        <div class="text-center text-white">
          <div class="text-xl mb-2">
            🍎
          </div>
          <div class="text-sm">
            Live spectrogram not available in this browser
          </div>
          <div class="text-xs text-gray-400 mt-1">
            Audio plays normally
          </div>
        </div>
      </div>
      <canvas
        v-else
        ref="spectrogramCanvas"
        class="w-full h-36 sm:h-48 mb-3 sm:mb-4 rounded-lg"
      />
      <div
        v-if="streams.length > 1"
        class="flex flex-wrap gap-2 mb-3 sm:mb-4"
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
      <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 sm:gap-4 mb-3 sm:mb-4">
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
           spectrogram; gain only changes what you hear. Shown whenever a live Web
           Audio graph carries signal (showProcessing): every browser except a
           Safari that can't load the decoder, where audio still plays but the
           graph would be inert. -->
      <div
        v-if="streamUrl && showProcessing"
        class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 sm:gap-y-3 mb-3 sm:mb-4 px-5 py-2.5 sm:py-3 sm:px-[22px] bg-gray-50 rounded-xl"
      >
        <RangeSlider
          v-model="highpassHz"
          :min="0"
          :max="6000"
          :step="50"
          label="High-pass filter"
          :display-value="highpassLabel"
          input-id="live-highpass"
          aria-label="High-pass cutoff frequency"
        />

        <RangeSlider
          v-model="gainDb"
          :min="-12"
          :max="24"
          :step="1"
          label="Gain"
          :display-value="gainLabel"
          input-id="live-gain"
          aria-label="Playback gain"
        />
      </div>

      <audio
        ref="audioElement"
        :src="streamUrl"
        preload="none"
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
import RangeSlider from '@/components/RangeSlider.vue'
import api from '@/services/api'
import { SOCKET_PATH } from '@/services/baseUrl'
import { spectrogramColor, SPECTROGRAM_MAX_HZ, SPECTROGRAM_FLOOR_DB } from '@/utils/spectrogram'
import { createScrollPacer } from '@/utils/scrollPacer'
import { useIcecastStream } from '@/composables/useIcecastStream'

export default {
  name: 'LiveFeed',
  components: {
    BirdDetectionList,
    Spinner,
    RangeSlider
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

    // Time-axis density of the live scroll: how many 1 px columns of spectrum are
    // painted per second of wall-clock. 120 matches the scroll speed Chrome
    // produced on a 120 Hz ProMotion display (one column per frame), now applied
    // consistently on every browser and refresh rate — previously the scroll
    // advanced one column per animation frame, so its speed tracked the refresh
    // rate and frame drops (Safari's decode path lagged Chrome). On a 60 Hz display
    // this paints ~2 px per analyser snapshot (the panel yields only 60/s), which
    // is fine. ~7 s of history spans a typical canvas width. Tunable: lower for a
    // slower scroll / more visible history, raise to match a 144 Hz monitor.
    const COLUMNS_PER_SEC = 120
    // Wall-clock scroll pacing (see @/utils/scrollPacer): converts elapsed real
    // time into whole columns to advance, so the scroll speed is identical across
    // browsers and refresh rates instead of tracking the rAF cadence.
    const scrollPacer = createScrollPacer(COLUMNS_PER_SEC)
    // Precomputed rgb() string for each 0–255 analyser intensity, so the per-bin
    // draw loop is a single array lookup instead of recomputing the colormap (3
    // pow() calls plus an array and a template string) for every bin every frame.
    const SPECTROGRAM_RGB_LUT = Array.from({ length: 256 }, (_, v) => {
      const [r, g, b] = spectrogramColor(v / 255)
      return `rgb(${r}, ${g}, ${b})`
    })
    let socket
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)

    // Safari can't tap a live Icecast stream through createMediaElementSource
    // (see useIcecastStream), so on Safari we decode the MP3 ourselves and feed
    // the same Web Audio graph. useDecodedStream is true once we've confirmed the
    // WASM decoder loads; if it can't, we fall back to plain <audio> playback and
    // hide the spectrogram + filters (the previous Safari behaviour). Non-Safari
    // browsers never use this path.
    const useDecodedStream = ref(isSafari)
    // Whether to show the spectrogram canvas + filter controls: whenever a live
    // Web Audio graph carries signal — every non-Safari browser, plus Safari when
    // the decoded path is available.
    const showProcessing = computed(() => !isSafari || useDecodedStream.value)

    // The decoded-stream player (Safari). Callbacks are thin wrappers so they
    // resolve the handlers defined later in setup; the graph accessors read the
    // nodes built by initAudioContext at call time.
    const icecast = useIcecastStream({
      getContext: () => audioContext,
      getDestination: () => highpassNode,
      onPlaying: () => handleAudioPlaying(),
      onEnded: () => handleAudioEnded(),
      onError: () => handleDrop(() => showError('Audio stream error'))
    })

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

    const initAudioContext = () => {
      if (!audioContext) {
        // Non-Safari taps the <audio> element via MediaElementSource and pins the
        // rate to 44.1 kHz. Safari decodes the stream itself and schedules PCM
        // buffers (which resample to the context rate), so let it use its native
        // rate rather than forcing one.
        audioContext = new (window.AudioContext || window.webkitAudioContext)(
          isSafari ? {} : { sampleRate: 44100 }
        );
        // On iOS, Web Audio is silenced by the hardware mute switch unless the
        // page declares a 'playback' audio session. The <audio> element wasn't
        // subject to that; declaring it keeps the decoded path audible with the
        // ringer off, matching the old behaviour. (Safari 16.4+, harmless else.)
        if (isSafari) {
          try {
            if (navigator.audioSession) navigator.audioSession.type = 'playback';
          } catch { /* not supported — degrade silently */ }
        }
        analyser = audioContext.createAnalyser();
        // Tuned to match the detection-detail spectrogram (@/utils/spectrogram):
        // same 1024-pt FFT, light temporal smoothing for crispness without
        // flicker, and an ~80 dB display window. The reference stays fixed
        // (absolute dB) rather than per-clip peak — per-clip normalization is
        // impossible on a live stream, and a fixed reference keeps brightness
        // stable over time.
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.25;
        // Dynamic-range window shared with the detail view (SPECTROGRAM_FLOOR_DB),
        // with the ceiling positioned so a typical loud call (~-30 dBFS) reaches
        // full brightness; the floor follows from the shared range (= -110 dB).
        analyser.maxDecibels = -30;
        analyser.minDecibels = analyser.maxDecibels - SPECTROGRAM_FLOOR_DB;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        const binHz = audioContext.sampleRate / analyser.fftSize;
        spectrogramBins = Math.min(
          analyser.frequencyBinCount,
          Math.round(SPECTROGRAM_MAX_HZ / binHz)
        );
        // High-pass + gain inserted into the chain. The analyser is a transparent
        // pass-through tapping the post-high-pass signal, so the live spectrogram
        // reflects the filter but not gain (gain only changes what you hear):
        //   <source> → highpass → analyser → gain → destination
        // <source> is the MediaElementSource (non-Safari) or the scheduled decode
        // buffers from useIcecastStream (Safari) — both feed highpass.
        highpassNode = audioContext.createBiquadFilter();
        highpassNode.type = 'highpass';
        applyHighpass();
        gainNode = audioContext.createGain();
        gainNode.gain.value = dbToGain(gainDb.value);

        highpassNode.connect(analyser);
        analyser.connect(gainNode);
        gainNode.connect(audioContext.destination);

        // Non-Safari taps the <audio> element. Safari can't (the graph would be
        // inert), so on Safari useIcecastStream feeds highpass with decode buffers.
        if (!isSafari) {
          // The stream is same-origin (nginx proxies /stream/), so the element is
          // never CORS-tainted and createMediaElementSource needs no crossorigin.
          source = audioContext.createMediaElementSource(audioElement.value);
          source.connect(highpassNode);
        }
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
      // Reset the scroll pacing so a later resume starts fresh instead of jumping
      // forward by all the wall-clock time that elapsed while stopped.
      scrollPacer.reset()
      // Safari's decoded path: tear down the fetch + decoder session too. This is
      // the single choke point hit by every stop/drop/give-up, so the decoder is
      // always freed (idempotent — safe to call when already stopped).
      if (useDecodedStream.value) icecast.stop()
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

    // Point the <audio> element at the live mount. Resetting src first forces a
    // fresh HTTP connection (load() alone reuses the cached one) so Start jumps to
    // the live head instead of replaying buffered audio.
    const armElement = () => {
      audioElement.value.src = ''
      audioElement.value.src = streamUrl.value
      audioElement.value.load()
    }

    // silent=true suppresses the hard error banner so background reconnect
    // attempts don't flash "stream not available" on every try — scheduleReconnect
    // owns the user-facing "reconnecting (N/6)" / give-up messaging instead.
    const startAudio = async (silent = false) => {
      try {
        isLoading.value = true
        statusMessage.value = 'Initializing audio...'

        if (useDecodedStream.value) {
          // Safari: build the graph (no MediaElementSource) and let the decoder
          // feed it. start() resolves once connected, throws on connect failure.
          initAudioContext()
          await audioContext.resume()
          await icecast.start(streamUrl.value)
        } else if (!isSafari) {
          // Other browsers: tap the live <audio> element through Web Audio.
          initAudioContext()
          armElement()
          await audioContext.resume()
          await audioElement.value.play()
        } else {
          // Safari without a usable decoder: plain element playback, no Web Audio
          // graph (the spectrogram + filters stay hidden, as they did before).
          armElement()
          await audioElement.value.play()
        }
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

      handleDrop(() => showError(errorMessage))
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
        if (showProcessing.value && !animationId) {
          animationId = requestAnimationFrame(drawSpectrogram)
        }
      }
      if (isPlaying.value) {
        statusMessage.value = 'Icecast stream connected'
      }
    }

    // A playback drop, shared by the <audio> element's error/ended events and the
    // decoded stream's onError/onEnded callbacks so the reconnect policy lives in
    // one place. While the user still wants audio it's treated as a transient
    // RTSP/Icecast flap (GH #56) and rolls into the bounded reconnect loop;
    // otherwise onGiveUp surfaces the outcome (an error, or a manual-restart prompt).
    const handleDrop = (onGiveUp) => {
      isLoading.value = false
      stopPlayback()
      if (userWantsPlay) {
        scheduleReconnect()
      } else {
        onGiveUp()
      }
    }

    const handleAudioEnded = () => {
      console.log('[LiveFeed] Audio stream ended')
      handleDrop(() => { statusMessage.value = 'Stream ended - click Start to reconnect' })
    }

    const drawSpectrogram = (nowMs) => {
      animationId = requestAnimationFrame(drawSpectrogram)

      // Columns to advance this frame from elapsed wall-clock time (0 until at least
      // one is due), so the scroll speed is identical across browsers and refresh
      // rates. Returns 0 after a stall (e.g. a backgrounded tab) so we resume cleanly
      // rather than smearing one spectrum across the missed gap.
      const cols = scrollPacer.tick(nowMs)
      if (cols < 1) return

      analyser.getByteFrequencyData(dataArray)

      // Scroll the existing image left by `cols` px; the freed strip on the right is
      // fully repainted below. (Guarded against a zero-width copy.)
      if (cols < canvasWidth) {
        const shifted = canvasCtx.getImageData(cols, 0, canvasWidth - cols, canvasHeight)
        canvasCtx.putImageData(shifted, 0, 0)
      }

      // Paint the newest spectrum into the rightmost `cols` px. Only bins up to
      // SPECTROGRAM_MAX_HZ are drawn, stretched across the full canvas height so the
      // visible range is 0–12 kHz (matches the detail view). The same green colormap
      // as the detection-detail spectrogram keeps the two reading as one instrument.
      const bins = spectrogramBins || dataArray.length
      const x = canvasWidth - cols
      const rowH = canvasHeight / bins
      for (let i = 0; i < bins; i++) {
        canvasCtx.fillStyle = SPECTROGRAM_RGB_LUT[dataArray[i]]
        // +1 px height overlaps adjacent rows so a fractional rowH leaves no seams.
        canvasCtx.fillRect(x, canvasHeight - (i + 1) * rowH, cols, rowH + 1)
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
        if (showProcessing.value && !animationId) {
          animationId = requestAnimationFrame(drawSpectrogram)
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
      // Kick off the stream-config fetch now — it doesn't depend on the Safari
      // decoder probe below, so the two (and on Safari a ~80 kB decoder-chunk
      // download) run concurrently instead of serially.
      const configReady = fetchStreamConfig()

      // Safari can't tap a live stream via Web Audio, so confirm the WASM decoder
      // loads before committing to the decoded path; fall back to plain <audio>
      // playback (no spectrogram/filters) if it can't.
      if (isSafari) {
        useDecodedStream.value = await icecast.canDecode()
      }

      // Initialise the spectrogram canvas whenever we'll have a live graph to draw
      // (every non-Safari browser, plus Safari on the decoded path).
      if (showProcessing.value) {
        const canvas = spectrogramCanvas.value
        canvasCtx = canvas.getContext('2d', { willReadFrequently: true })
        canvasWidth = canvas.width = canvas.offsetWidth
        canvasHeight = canvas.height = canvas.offsetHeight

        // Idle background before playback: a near-floor green from the bottom of
        // the spectrogram colormap, so the empty canvas matches how a quiet stream
        // renders. The backing store is sized once here; on a window resize the
        // browser scales this bitmap (the spectrogram keeps scrolling, slightly
        // stretched) rather than clearing. Tune the 0.06 if too bright/dark.
        const [ir, ig, ib] = spectrogramColor(0.06)
        canvasCtx.fillStyle = `rgb(${ir}, ${ig}, ${ib})`
        canvasCtx.fillRect(0, 0, canvasWidth, canvasHeight)
      }

      await configReady
      
      initWebSocket()
    })

    onUnmounted(() => {
      userWantsPlay = false
      cancelReconnect()
      // Stop the decoded stream (Safari): aborts the fetch, frees the decoder, and
      // stops scheduled buffers before the context is torn down below. No-op
      // elsewhere (nothing was started).
      icecast.stop()
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
      isSafari,
      useDecodedStream,
      showProcessing,
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
</style>
