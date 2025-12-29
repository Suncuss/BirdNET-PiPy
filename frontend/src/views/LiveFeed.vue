<template>
  <div class="flex flex-col items-center w-full max-w-3xl mx-auto">
    <div class="bg-white rounded-lg shadow-md p-4 w-full max-w-4xl">
      <div v-if="isSafari" class="w-full h-32 mb-4 bg-gray-800 rounded-lg flex items-center justify-center">
        <div class="text-center text-white">
          <div class="text-xl mb-2">🍎</div>
          <div class="text-sm">Live spectrogram not available in Safari</div>
          <div class="text-xs text-gray-400 mt-1">Audio playback works normally</div>
        </div>
      </div>
      <canvas v-else ref="spectrogramCanvas" class="w-full h-48 mb-4 rounded-lg"></canvas>
      <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-4">
        <button @click="toggleAudio"
          class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 flex items-center justify-center min-w-[120px] flex-shrink-0 disabled:bg-gray-400 disabled:cursor-not-allowed"
          :disabled="isLoading || !streamUrl">
          <template v-if="isLoading">
            <div class="animate-spin w-4 h-4 rounded-full border-2 border-gray-100 border-t-blue-500 mr-2"></div>
            Loading...
          </template>
          <template v-else>
            {{ isPlaying ? 'Stop' : 'Start' }} Audio
          </template>
        </button>

        <div class="text-right">
          <span class="text-sm text-gray-500 break-words">Status: {{ statusMessage }}</span>
          <div class="text-xs text-gray-400 mt-1">
            <template v-if="streamType === 'icecast'">🎤 Local Icecast Stream</template>
            <template v-else-if="streamType === 'custom'">📡 Custom Stream</template>
            <template v-else-if="streamType === 'none'">⚠️ No stream available</template>
            <template v-else>❓ Unknown</template>
          </div>
        </div>
      </div>
      <audio ref="audioElement" :src="streamUrl" preload="none" crossorigin="anonymous"></audio>
      <BirdDetectionList :detections="birdDetections" />
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { io } from 'socket.io-client'
import BirdDetectionList from './BirdDetectionList.vue'
import api from '@/services/api'

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
    const statusMessage = ref('Click Start to begin')
    const birdDetections = ref([])
    const streamUrl = ref('')
    const streamType = ref('local')

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

        console.log('Audio context initialized:', audioContext.state);
      }
    }

    const startAudio = async () => {
      try {
        isLoading.value = true
        statusMessage.value = 'Initializing audio...'

        initAudioContext()
        // Force a fresh connection so Start jumps to the live head instead of buffered audio.
        audioElement.value.load()
        await audioContext.resume()
        await audioElement.value.play()
        statusMessage.value = 'Icecast stream connected'
        console.log('Audio playback started successfully')
      } catch (error) {
        console.error('Error starting audio playback:', error)
        // Check if it might be an auth error (nginx returns 401 for unauthenticated requests)
        if (error.name === 'NotAllowedError' || error.message?.includes('401')) {
          statusMessage.value = 'Authentication required - please log in'
          window.location.href = '/?auth=required'
        } else {
          statusMessage.value = 'Error starting audio playback'
        }
      } finally {
        isLoading.value = false
      }
    }

    const stopAudio = async () => {
      try {
        await audioElement.value.pause()
        statusMessage.value = 'Audio stopped'
        console.log('Audio playback stopped successfully')
      } catch (error) {
        console.error('Error stopping audio playback:', error)
        statusMessage.value = 'Error stopping audio playback'
      }
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
        cancelAnimationFrame(animationId)
        await stopAudio()
        isPlaying.value = false
      } else {
        await startAudio()
        if (!isLoading.value) {
          if (!isSafari) {
            drawSpectrogram()
          }
          isPlaying.value = true
        }
      }
    }

    const fetchStreamConfig = async () => {
      try {
        const { data: config } = await api.get('/stream/config')
        streamUrl.value = config.stream_url || ''
        streamType.value = config.stream_type || 'none'
        console.log(`Stream URL configured (${config.stream_type}):`, streamUrl.value)

        // Update status message based on stream availability
        if (!streamUrl.value || streamType.value === 'none') {
          statusMessage.value = 'No audio stream available (using direct microphone)'
        }
      } catch (error) {
        console.error('Error fetching stream config:', error)
        statusMessage.value = 'Error loading stream configuration'
      }
    }

    const initWebSocket = () => {
      // Use relative path for Socket.IO - nginx will proxy to the API server
      console.log('Connecting to WebSocket via nginx proxy')
      socket = io()

      socket.on('connect', () => {
        console.log('Connected to WebSocket')
        // Only update status if audio isn't playing
        if (!isPlaying.value) {
          statusMessage.value = 'WebSocket connected'
        }
      })

      socket.on('disconnect', () => {
        console.log('Disconnected from WebSocket')
        // Only update status if audio isn't playing
        if (!isPlaying.value) {
          statusMessage.value = 'WebSocket disconnected'
        }
      })

      socket.on('connect_error', (error) => {
        console.warn('WebSocket connection error (will auto-retry):', error.message)
        // Socket.IO will automatically reconnect, so just log it
      })

      socket.on('bird_detected', (detection) => {
        console.log('Bird detected:', detection)
        
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

        console.log('Canvas initialized:', canvasWidth, 'x', canvasHeight)
      } else {
        console.log('Safari detected - skipping canvas initialization')
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
      statusMessage,
      toggleAudio,
      birdDetections,
      streamUrl,
      streamType,
      isSafari
    }
  }
}
</script>
