<template>
  <canvas
    ref="spectrogramCanvas"
    :width="width"
    :height="height"
  />
</template>

<script>
import { ref, onMounted } from 'vue'

export default {
  name: 'Spectrogram',
  props: {
    audioUrl: {
      type: String,
      required: true
    },
    width: {
      type: Number,
      default: 400
    },
    height: {
      type: Number,
      default: 150
    }
  },
  setup(props) {
    const spectrogramCanvas = ref(null)

    const generateSpectrogram = async () => {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)()
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048

      try {
        const response = await fetch(props.audioUrl)
        const arrayBuffer = await response.arrayBuffer()
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)

        const offlineContext = new OfflineAudioContext(1, audioBuffer.length, audioBuffer.sampleRate)
        const source = offlineContext.createBufferSource()
        source.buffer = audioBuffer
        source.connect(analyser)
        analyser.connect(offlineContext.destination)

        source.start(0)
        const renderedBuffer = await offlineContext.startRendering()

        const canvas = spectrogramCanvas.value
        const ctx = canvas.getContext('2d')
        const bufferLength = analyser.frequencyBinCount
        const dataArray = new Uint8Array(bufferLength)

        const sliceWidth = canvas.width / renderedBuffer.length
        let x = 0

        for (let i = 0; i < renderedBuffer.length; i++) {
          analyser.getByteFrequencyData(dataArray)
          
          for (let j = 0; j < bufferLength; j++) {
            const y = (1 - dataArray[j] / 255) * canvas.height
            const hue = j / bufferLength * 360
            ctx.fillStyle = `hsl(${hue}, 100%, 50%)`
            ctx.fillRect(x, y, sliceWidth, 1)
          }

          x += sliceWidth
        }

      } catch (error) {
        console.error('Error generating spectrogram:', error)
      }
    }

    onMounted(() => {
      generateSpectrogram()
    })

    return {
      spectrogramCanvas
    }
  }
}
</script>