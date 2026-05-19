<template>
  <div class="flex flex-col items-center w-full max-w-3xl mx-auto">
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
            Audio playback works normally
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { io } from 'socket.io-client'
import BirdDetectionList from './BirdDetectionList.vue'
import Spinner from '@/components/Spinner.vue'
import api from '@/services/api'
import { SOCKET_PATH } from '@/services/baseUrl'

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

    const currentSource = computed(() =>
      streams.value.find(s => s.source_id === selectedSourceId.value)
    )
    const streamUrl = computed(() => currentSource.value?.url || '')
    const streamDescription = computed(() => currentSource.value?.label || '')

    let audioContext, analyser, source, dataArray, animationId
    let canvasCtx, canvasWidth, canvasHeight
    let socket
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)

    const initAudioContext = async () => {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 44100
        });
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        audioElement.value.crossOrigin = 'anonymous';
        source = audioContext.createMediaElementSource(audioElement.value);
        source.connect(analyser);
        analyser.connect(audioContext.destination);

      }
    }

    const showError = (message, duration = 4000) => {
      statusMessage.value = message
      hasError.value = true
      setTimeout(() => {
        hasError.value = false
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

    const startAudio = async () => {
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
          showError('Authentication required')
          window.dispatchEvent(new Event('auth:required'))
        } else {
          // Probe the stream URL to diagnose why playback failed
          const userMessage = await probeStreamError()
          showError(userMessage)
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
      try {
        await audioElement.value.pause()
        statusMessage.value = 'Audio stopped'
      } catch (error) {
        console.error(`[LiveFeed] Stop failed: ${error.message}`)
        statusMessage.value = 'Error stopping audio'
      }
    }

    const handleAudioError = (event) => {
      // Ignore errors when not actively playing (e.g., empty src on page load)
      if (!isPlaying.value && !isLoading.value) {
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

      showError(errorMessage)
      isLoading.value = false
      stopPlayback()
    }

    const handleAudioBuffering = () => {
      console.log('[LiveFeed] Audio stream buffering')
      if (isPlaying.value) {
        statusMessage.value = 'Stream buffering...'
      }
    }

    const handleAudioPlaying = () => {
      if (isPlaying.value) {
        statusMessage.value = 'Icecast stream connected'
      }
    }

    const handleAudioEnded = () => {
      console.log('[LiveFeed] Audio stream ended')
      statusMessage.value = 'Stream ended - click Start to reconnect'
      stopPlayback()
    }

    const drawSpectrogram = () => {
      animationId = requestAnimationFrame(drawSpectrogram)

      analyser.getByteFrequencyData(dataArray)

      let imageData = canvasCtx.getImageData(1, 0, canvasWidth - 1, canvasHeight)
      canvasCtx.fillRect(0, 0, canvasWidth, canvasHeight)
      canvasCtx.putImageData(imageData, 0, 0)

      for (let i = 0; i < dataArray.length; i++) {
        let ratio = dataArray[i] / 255
        let hue = Math.round((ratio * 220) + 280 % 360)
        let sat = '100%'
        let lit = 10 + (70 * ratio) + '%'
        canvasCtx.beginPath()
        canvasCtx.strokeStyle = `hsl(${hue}, ${sat}, ${lit})`
        canvasCtx.moveTo(canvasWidth - 1, canvasHeight - (i * canvasHeight / dataArray.length))
        canvasCtx.lineTo(canvasWidth - 1, canvasHeight - ((i + 1) * canvasHeight / dataArray.length))
        canvasCtx.stroke()
      }
    }

    const startPlayback = async () => {
      const success = await startAudio()
      if (success) {
        if (!isSafari) {
          drawSpectrogram()
        }
        isPlaying.value = true
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

        canvasCtx.fillStyle = 'hsl(280, 100%, 10%)'
        canvasCtx.fillRect(0, 0, canvasWidth, canvasHeight)
      }

      // Fetch stream configuration first
      await fetchStreamConfig()
      
      initWebSocket()
    })

    onUnmounted(() => {
      if (animationId) {
        cancelAnimationFrame(animationId)
        animationId = null
      }

      if (source) {
        source.disconnect()
        source = null
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
</style>
