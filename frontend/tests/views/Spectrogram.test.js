import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import Spectrogram from '@/views/Spectrogram.vue'

const decodeAudioData = vi.fn().mockResolvedValue({ length: 1, sampleRate: 48000 })

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8))
  }))

  vi.stubGlobal('OfflineAudioContext', vi.fn().mockImplementation(() => ({
    createBufferSource: () => ({
      connect: vi.fn(),
      start: vi.fn()
    }),
    createAnalyser: () => ({
      fftSize: 2048,
      frequencyBinCount: 1,
      getByteFrequencyData: vi.fn()
    }),
    destination: {},
    startRendering: vi.fn().mockResolvedValue({})
  })))

  vi.stubGlobal('AudioContext', vi.fn().mockImplementation(() => ({
    createAnalyser: () => ({
      fftSize: 2048,
      frequencyBinCount: 1,
      getByteFrequencyData: vi.fn(),
      connect: vi.fn()
    }),
    decodeAudioData
  })))
  vi.stubGlobal('webkitAudioContext', AudioContext)

  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    fillRect: vi.fn(),
    fillStyle: '',
    fillText: vi.fn()
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Spectrogram', () => {
  it('starts spectrogram generation on mount', async () => {
    mount(Spectrogram, {
      props: {
        audioUrl: '/audio/test.mp3'
      }
    })

    await flushPromises()

    expect(fetch).toHaveBeenCalledWith('/audio/test.mp3')
    expect(decodeAudioData).toHaveBeenCalled()
  })

  it('handles fetch errors gracefully', async () => {
    fetch.mockRejectedValueOnce(new Error('Network error'))

    mount(Spectrogram, {
      props: {
        audioUrl: '/audio/test.mp3'
      }
    })

    await flushPromises()

    expect(fetch).toHaveBeenCalledWith('/audio/test.mp3')
  })
})
