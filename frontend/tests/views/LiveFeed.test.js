import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import LiveFeed from '@/views/LiveFeed.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock socket.io client
const onMock = vi.fn()
const emitMock = vi.fn()
const disconnectMock = vi.fn()
const ioMock = vi.hoisted(() => vi.fn())

vi.mock('socket.io-client', () => ({
  io: ioMock
}))

// Mock BirdDetectionList component
vi.mock('@/views/BirdDetectionList.vue', () => ({
  default: {
    name: 'BirdDetectionList',
    props: ['detections'],
    template: '<div class="bird-detection-list-stub" />'
  }
}))

// Mock the Safari decoded-stream composable so tests never load the WASM decoder.
// canDecode defaults to true (decoder available); individual tests override it.
const icecastMock = vi.hoisted(() => ({
  canDecode: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  isActive: { value: false }
}))
vi.mock('@/composables/useIcecastStream', () => ({
  useIcecastStream: vi.fn(() => icecastMock)
}))

// Mozilla UA string Safari matches (no "chrome"/"android"), shared by Safari tests.
const SAFARI_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
const withUserAgent = async (ua, fn) => {
  const original = navigator.userAgent
  Object.defineProperty(navigator, 'userAgent', { value: ua, configurable: true })
  try {
    await fn()
  } finally {
    Object.defineProperty(navigator, 'userAgent', { value: original, configurable: true })
  }
}

describe('LiveFeed', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockApi.get.mockResolvedValue({
      data: {
        streams: [
          { source_id: 'source_0', label: 'Microphone', url: 'stream/source_0.mp3' }
        ]
      }
    })
    ioMock.mockReset()
    ioMock.mockImplementation(() => ({
      on: onMock,
      emit: emitMock,
      disconnect: disconnectMock
    }))

    // Decoded-stream composable defaults: decoder available, connect succeeds.
    icecastMock.canDecode.mockReset().mockResolvedValue(true)
    icecastMock.start.mockReset().mockResolvedValue(true)
    icecastMock.stop.mockReset()

    // Mock MediaError constants (not available in jsdom)
    vi.stubGlobal('MediaError', {
      MEDIA_ERR_ABORTED: 1,
      MEDIA_ERR_NETWORK: 2,
      MEDIA_ERR_DECODE: 3,
      MEDIA_ERR_SRC_NOT_SUPPORTED: 4
    })
    vi.stubGlobal('Audio', vi.fn().mockImplementation(() => ({
      play: vi.fn().mockResolvedValue(),
      pause: vi.fn(),
      addEventListener: vi.fn(),
      currentTime: 0
    })))

    // Minimal AudioContext mock
    const resume = vi.fn().mockResolvedValue()
    vi.stubGlobal('AudioContext', vi.fn().mockImplementation(() => ({
      createAnalyser: () => ({
        fftSize: 0,
        frequencyBinCount: 0,
        getByteFrequencyData: vi.fn(),
        connect: vi.fn()
      }),
      createMediaElementSource: () => ({
        connect: vi.fn()
      }),
      createBiquadFilter: () => ({
        type: '',
        frequency: { value: 0 },
        connect: vi.fn()
      }),
      createGain: () => ({
        gain: { value: 0 },
        connect: vi.fn()
      }),
      destination: {},
      resume
    })))
    vi.stubGlobal('webkitAudioContext', AudioContext)

    // Canvas context mock
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillRect: vi.fn(),
      getImageData: vi.fn(() => ({ data: [] })),
      putImageData: vi.fn(),
      beginPath: vi.fn(),
      stroke: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      clearRect: vi.fn()
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountLiveFeed = () => mount(LiveFeed, {
    global: {
      stubs: {
        'font-awesome-icon': true
      }
    }
  })

  it('fetches stream config on mount and sets status', async () => {
    const wrapper = mountLiveFeed()
    await flushPromises()

    expect(mockApi.get).toHaveBeenCalledWith('/stream/config')
    expect(wrapper.vm.streamUrl).toBe('stream/source_0.mp3')
  })

  it('handles missing stream by updating status message', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { streams: [] } })
    const wrapper = mountLiveFeed()
    await flushPromises()

    expect(wrapper.text()).toContain('No audio stream configured')
  })

  it('toggles audio start/stop states', async () => {
    const wrapper = mountLiveFeed()
    await flushPromises()

    expect(wrapper.vm.isPlaying).toBe(false)
    await wrapper.vm.toggleAudio()
    expect(wrapper.vm.isPlaying).toBe(true)

    await wrapper.vm.toggleAudio()
    expect(wrapper.vm.isPlaying).toBe(false)
  })

  it('registers WebSocket listeners', async () => {
    mountLiveFeed()
    await flushPromises()

    expect(onMock).toHaveBeenCalledWith('connect', expect.any(Function))
    expect(onMock).toHaveBeenCalledWith('disconnect', expect.any(Function))
    expect(onMock).toHaveBeenCalledWith('bird_detected', expect.any(Function))
  })

  it('initializes socket.io with the base-path-aware socket.io path', async () => {
    mountLiveFeed()
    await flushPromises()

    expect(ioMock).toHaveBeenCalledWith({ path: '/socket.io' })
  })

  describe('multi-stream source selection', () => {
    const multiStreamResponse = {
      data: {
        streams: [
          { source_id: 'source_0', label: 'Microphone', url: 'stream/source_0.mp3' },
          { source_id: 'source_1', label: 'RTSP Camera', url: 'stream/source_1.mp3' }
        ]
      }
    }

    it('populates streams and selects first source by default', async () => {
      mockApi.get.mockResolvedValueOnce(multiStreamResponse)
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.vm.streams).toHaveLength(2)
      expect(wrapper.vm.selectedSourceId).toBe('source_0')
      expect(wrapper.vm.streamUrl).toBe('stream/source_0.mp3')
      expect(wrapper.vm.streamDescription).toBe('Microphone')
    })

    it('renders source pill buttons when multiple streams exist', async () => {
      mockApi.get.mockResolvedValueOnce(multiStreamResponse)
      const wrapper = mountLiveFeed()
      await flushPromises()

      const pills = wrapper.findAll('button.rounded-full')
      expect(pills).toHaveLength(2)
      expect(pills[0].text()).toBe('Microphone')
      expect(pills[1].text()).toBe('RTSP Camera')
      // First pill should have the active style
      expect(pills[0].classes()).toContain('bg-blue-50')
      expect(pills[1].classes()).not.toContain('bg-blue-50')
    })

    it('hides source pills when only one stream exists', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.findAll('button.rounded-full')).toHaveLength(0)
    })

    it('switches stream URL when a different pill is clicked', async () => {
      mockApi.get.mockResolvedValueOnce(multiStreamResponse)
      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.selectSourceById('source_1')

      expect(wrapper.vm.selectedSourceId).toBe('source_1')
      expect(wrapper.vm.streamUrl).toBe('stream/source_1.mp3')
      expect(wrapper.vm.streamDescription).toBe('RTSP Camera')
    })
  })

  describe('audio filters (high-pass + gain)', () => {
    it('renders the high-pass and gain sliders once a stream is configured', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.find('#live-highpass').exists()).toBe(true)
      expect(wrapper.find('#live-gain').exists()).toBe(true)
    })

    it('hides the filter panel when no stream is configured', async () => {
      mockApi.get.mockResolvedValueOnce({ data: { streams: [] } })
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.find('#live-highpass').exists()).toBe(false)
      expect(wrapper.find('#live-gain').exists()).toBe(false)
    })

    it('shows the spectrogram + filters in Safari when the decoder is available', async () => {
      // Safari now decodes the stream itself into Web Audio (useIcecastStream),
      // so the analyser-backed spectrogram and the filter graph carry signal —
      // the controls are live, not dead, and the fallback card is gone.
      await withUserAgent(SAFARI_UA, async () => {
        const wrapper = mountLiveFeed()
        await flushPromises()

        expect(wrapper.vm.isSafari).toBe(true)
        expect(wrapper.vm.useDecodedStream).toBe(true)
        expect(wrapper.find('canvas').exists()).toBe(true)
        expect(wrapper.find('#live-highpass').exists()).toBe(true)
        expect(wrapper.find('#live-gain').exists()).toBe(true)
        expect(wrapper.text()).not.toContain('not available in this browser')
      })
    })

    it('falls back to plain playback in Safari when the decoder cannot load', async () => {
      // No usable WASM decoder: keep audio playing via the <audio> element but
      // hide the (inert) spectrogram + filters, as Safari did before.
      icecastMock.canDecode.mockResolvedValue(false)
      await withUserAgent(SAFARI_UA, async () => {
        const wrapper = mountLiveFeed()
        await flushPromises()

        expect(wrapper.vm.isSafari).toBe(true)
        expect(wrapper.vm.useDecodedStream).toBe(false)
        expect(wrapper.find('canvas').exists()).toBe(false)
        expect(wrapper.find('#live-highpass').exists()).toBe(false)
        expect(wrapper.find('#live-gain').exists()).toBe(false)
        expect(wrapper.text()).toContain('not available in this browser')
      })
    })

    it('starts and stops the decoded stream in Safari via the composable', async () => {
      await withUserAgent(SAFARI_UA, async () => {
        const wrapper = mountLiveFeed()
        await flushPromises()
        expect(wrapper.vm.useDecodedStream).toBe(true)

        await wrapper.vm.toggleAudio()
        expect(icecastMock.start).toHaveBeenCalledWith('stream/source_0.mp3')
        expect(wrapper.vm.isPlaying).toBe(true)

        await wrapper.vm.toggleAudio()
        expect(icecastMock.stop).toHaveBeenCalled()
        expect(wrapper.vm.isPlaying).toBe(false)
      })
    })

    it('formats the high-pass label (Off at 0, Hz otherwise)', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.vm.highpassLabel).toBe('Off')
      wrapper.vm.highpassHz = 1500
      await flushPromises()
      expect(wrapper.vm.highpassLabel).toBe('1500 Hz')
    })

    it('formats the gain label with a sign', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.vm.gainLabel).toBe('0 dB')
      wrapper.vm.gainDb = 6
      await flushPromises()
      expect(wrapper.vm.gainLabel).toBe('+6 dB')
      wrapper.vm.gainDb = -6
      await flushPromises()
      expect(wrapper.vm.gainLabel).toBe('-6 dB')
    })
  })

  describe('error handling', () => {
    it('handleAudioError ignores errors when not playing or loading', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Simulate error event when not playing
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } })

      // hasError should remain false
      expect(wrapper.vm.hasError).toBe(false)
    })

    it('handleAudioError schedules a reconnect when a drop happens mid-playback', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Start playing first (records the user's intent to play)
      await wrapper.vm.toggleAudio()
      expect(wrapper.vm.isPlaying).toBe(true)

      // A network drop mid-playback is a transient RTSP/Icecast flap (GH #56):
      // playback stops but we reconnect instead of surfacing a hard error.
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } }) // MEDIA_ERR_NETWORK

      expect(wrapper.vm.isPlaying).toBe(false)
      expect(wrapper.vm.hasError).toBe(false)
      expect(wrapper.vm.statusMessage).toContain('reconnecting')
    })

    it('handleAudioError surfaces an error when there is no play intent', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // isPlaying without going through Start (no reconnect intent) -> show the error.
      wrapper.vm.isPlaying = true
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } }) // MEDIA_ERR_NETWORK

      expect(wrapper.vm.hasError).toBe(true)
      expect(wrapper.vm.statusMessage).toBe('Could not reach audio stream')
      expect(wrapper.vm.isPlaying).toBe(false)
    })

    it('handleAudioEnded schedules a reconnect when the user wants audio', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.toggleAudio()
      expect(wrapper.vm.isPlaying).toBe(true)

      wrapper.vm.handleAudioEnded()

      expect(wrapper.vm.isPlaying).toBe(false)
      expect(wrapper.vm.statusMessage).toContain('reconnecting')
    })

    it('handleAudioEnded prompts a manual restart when not playing', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // No Start -> no play intent -> the manual-restart prompt.
      wrapper.vm.handleAudioEnded()

      expect(wrapper.vm.statusMessage).toBe('Stream ended - click Start to reconnect')
    })

    it('handleAudioBuffering updates status only when playing', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Should not update when not playing
      wrapper.vm.handleAudioBuffering()
      expect(wrapper.vm.statusMessage).not.toBe('Stream buffering...')

      // Start playing
      await wrapper.vm.toggleAudio()
      wrapper.vm.handleAudioBuffering()
      expect(wrapper.vm.statusMessage).toBe('Stream buffering...')
    })

    it('handleAudioPlaying restores connected status when playing', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.toggleAudio()
      wrapper.vm.statusMessage = 'Stream buffering...'

      wrapper.vm.handleAudioPlaying()
      expect(wrapper.vm.statusMessage).toBe('Icecast stream connected')
    })

    it('hasError clears after timeout', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Use the no-intent path so showError runs (the mid-playback path reconnects).
      wrapper.vm.isPlaying = true
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } })

      expect(wrapper.vm.hasError).toBe(true)

      // Advance timers past the 4000ms duration
      vi.advanceTimersByTime(4000)

      expect(wrapper.vm.hasError).toBe(false)
    })

    it('rolls a failed start into a silent reconnect instead of flashing an error', async () => {
      // Mock AudioContext.resume to reject
      vi.stubGlobal('AudioContext', vi.fn().mockImplementation(() => ({
        createAnalyser: () => ({
          fftSize: 0,
          frequencyBinCount: 0,
          getByteFrequencyData: vi.fn(),
          connect: vi.fn()
        }),
        createMediaElementSource: () => ({
          connect: vi.fn()
        }),
        createBiquadFilter: () => ({
          type: '',
          frequency: { value: 0 },
          connect: vi.fn()
        }),
        createGain: () => ({
          gain: { value: 0 },
          connect: vi.fn()
        }),
        destination: {},
        resume: vi.fn().mockRejectedValue(new Error('audio failed'))
      })))

      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.toggleAudio()

      // No hard error banner — the bounded reconnect loop owns the messaging.
      expect(wrapper.vm.isPlaying).toBe(false)
      expect(wrapper.vm.hasError).toBe(false)
      expect(wrapper.vm.statusMessage).toContain('reconnecting')
    })

    it('handleAudioPlaying cancels a pending reconnect when the stream recovers on its own', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Start, then drop mid-playback so a reconnect timer is armed.
      await wrapper.vm.toggleAudio()
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } })
      expect(wrapper.vm.statusMessage).toContain('reconnecting')

      // The element recovers by itself before the timer fires.
      wrapper.vm.handleAudioPlaying()
      expect(wrapper.vm.isPlaying).toBe(true)
      expect(wrapper.vm.statusMessage).toBe('Icecast stream connected')

      // The stale reconnect timer must not fire and tear the stream back down.
      vi.advanceTimersByTime(15000)
      expect(wrapper.vm.isPlaying).toBe(true)
    })
  })
})
