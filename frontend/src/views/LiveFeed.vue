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
      <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-4">
        <button
          class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 flex items-center justify-center min-w-[120px] flex-shrink-0 disabled:bg-gray-400 disabled:cursor-not-allowed"
          :disabled="isLoading || !streamUrl || hasError"
          @click="toggleAudio"
        >
          <template v-if="isLoading">
            <div class="animate-spin w-4 h-4 rounded-full border-2 border-gray-100 border-t-blue-500 mr-2" />
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
          <div class="hidden sm:block text-xs text-gray-400 mt-1">
            <template v-if="streamDescription">
              {{ streamDescription }}
            </template>
            <template v-else-if="streamType === 'none'">
              ⚠️ No stream available
            </template>
            <template v-else>
              ❓ Unknown
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
import { ref, onMounted, onUnmounted } from 'vue'
import { io } from 'socket.io-client'
import BirdDetectionList from './BirdDetectionList.vue'
import api, { getAppBaseUrl } from '@/services/api'

export default {
  name: 'LiveFeed',
  components: {
    BirdDetectionList
  },
  setup() {
    const spectrogramCanvas = ref(null)
    const audioElement = ref(null)
    const isPlaying = ref(false)
    const isLoading = ref(false)
    const hasError = ref(false)
    const statusMessage = ref('Click Start to begin')
    const birdDetections = ref([])
    const streamUrl = ref('')
    const streamType = ref('none')
    const streamDescription = ref('')

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
        console.error('Error starting audio playback:', error)
        // Check if it might be an auth error (nginx returns 401 for unauthenticated requests)
        if (error.name === 'NotAllowedError' || error.message?.includes('401')) {
          showError('Authentication required - please log in')
          const appBase = getAppBaseUrl()
          window.location.href = `${appBase || ''}/?auth=required`
        } else {
          showError('Error starting audio playback')
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
        console.error('Error stopping audio playback:', error)
        statusMessage.value = 'Error stopping audio playback'
      }
    }

    const handleAudioError = (event) => {
      // Ignore errors when not actively playing (e.g., empty src on page load)
      if (!isPlaying.value && !isLoading.value) {
        return
      }

      const error = event.target.error
      console.error('Audio element error:', error)

      let errorMessage = 'Stream error'
      if (error) {
        switch (error.code) {
          case MediaError.MEDIA_ERR_ABORTED:
            errorMessage = 'Stream aborted'
            break
          case MediaError.MEDIA_ERR_NETWORK:
            errorMessage = 'Network error - stream unavailable'
            break
          case MediaError.MEDIA_ERR_DECODE:
            errorMessage = 'Stream decode error'
            break
          case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMessage = 'Stream format not supported'
            break
        }
      }

      showError(errorMessage)
      isLoading.value = false
      stopPlayback()
    }

    const handleAudioBuffering = () => {
      console.warn('Audio stream buffering')
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
      console.warn('Audio stream ended')
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

    const toggleAudio = async () => {
      if (isPlaying.value) {
        stopPlayback()
        await stopAudio()
      } else {
        const success = await startAudio()
        if (success) {
          if (!isSafari) {
            drawSpectrogram()
          }
          isPlaying.value = true
        }
      }
    }

    const applyStreamConfig = (config) => {
      const appBase = getAppBaseUrl()
      const rawStreamUrl = config.stream_url || ''
      streamUrl.value = rawStreamUrl.startsWith('/stream/')
        ? `${appBase}${rawStreamUrl}`
        : rawStreamUrl
      streamType.value = config.stream_type || 'none'
      streamDescription.value = config.description || ''

      if (!streamUrl.value || streamType.value === 'none') {
        statusMessage.value = 'No audio stream configured'
      }
    }

    const getFallbackStreamConfig = async () => {
      const { data: settings } = await api.get('/settings')
      const audio = settings?.audio || {}
      const recordingMode = audio.recording_mode || 'pulseaudio'
      const appBase = getAppBaseUrl()
      const localStreamUrl = `${appBase}/stream/stream.mp3`

      if (recordingMode === 'pulseaudio') {
        return {
          stream_url: localStreamUrl,
          stream_type: 'icecast',
          description: 'Local Icecast audio stream'
        }
      }

      if (recordingMode === 'rtsp' && audio.rtsp_url) {
        return {
          stream_url: localStreamUrl,
          stream_type: 'icecast',
          description: 'RTSP stream via Icecast'
        }
      }

      if (recordingMode === 'http_stream' && audio.stream_url) {
        return {
          stream_url: audio.stream_url,
          stream_type: 'custom',
          description: 'User-defined audio stream'
        }
      }

      return {
        stream_url: null,
        stream_type: 'none',
        description: 'No audio stream configured'
      }
    }

    const fetchStreamConfig = async () => {
      try {
        const { data: config } = await api.get('/stream/config')
        applyStreamConfig(config)
      } catch (error) {
        console.error('Error fetching stream config:', error)
        try {
          const fallbackConfig = await getFallbackStreamConfig()
          applyStreamConfig(fallbackConfig)
        } catch (fallbackError) {
          console.error('Error loading fallback stream config:', fallbackError)
          showError('Error loading stream configuration')
        }
      }
    }

    const initWebSocket = () => {
      const appBase = getAppBaseUrl()
      const socketPath = `${appBase || ''}/socket.io`
      socket = io({ path: socketPath })

      socket.on('connect', () => {})

      socket.on('disconnect', () => {})

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
      streamUrl,
      streamType,
      streamDescription,
      isSafari,
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
