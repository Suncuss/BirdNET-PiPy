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

vi.mock('socket.io-client', () => ({
  io: () => ({
    on: onMock,
    emit: emitMock,
    disconnect: disconnectMock
  })
}))

// Mock BirdDetectionList component
vi.mock('@/views/BirdDetectionList.vue', () => ({
  default: {
    name: 'BirdDetectionList',
    props: ['detections'],
    template: '<div class="bird-detection-list-stub" />'
  }
}))

describe('LiveFeed', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockApi.get.mockResolvedValue({
      data: {
        streams: [
          { source_id: 'source_0', label: 'Microphone', url: '/stream/source_0.mp3' }
        ]
      }
    })

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
    expect(wrapper.vm.streamUrl).toBe('/stream/source_0.mp3')
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

  describe('multi-stream source selection', () => {
    const multiStreamResponse = {
      data: {
        streams: [
          { source_id: 'source_0', label: 'Microphone', url: '/stream/source_0.mp3' },
          { source_id: 'source_1', label: 'RTSP Camera', url: '/stream/source_1.mp3' }
        ]
      }
    }

    it('populates streams and selects first source by default', async () => {
      mockApi.get.mockResolvedValueOnce(multiStreamResponse)
      const wrapper = mountLiveFeed()
      await flushPromises()

      expect(wrapper.vm.streams).toHaveLength(2)
      expect(wrapper.vm.selectedSourceId).toBe('source_0')
      expect(wrapper.vm.streamUrl).toBe('/stream/source_0.mp3')
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
      expect(wrapper.vm.streamUrl).toBe('/stream/source_1.mp3')
      expect(wrapper.vm.streamDescription).toBe('RTSP Camera')
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

    it('handleAudioError shows error and stops playback when playing', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      // Start playing first
      await wrapper.vm.toggleAudio()
      expect(wrapper.vm.isPlaying).toBe(true)

      // Simulate network error
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } }) // MEDIA_ERR_NETWORK

      expect(wrapper.vm.hasError).toBe(true)
      expect(wrapper.vm.statusMessage).toBe('Could not reach audio stream')
      expect(wrapper.vm.isPlaying).toBe(false)
    })

    it('handleAudioEnded updates status and stops playback', async () => {
      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.toggleAudio()
      expect(wrapper.vm.isPlaying).toBe(true)

      wrapper.vm.handleAudioEnded()

      expect(wrapper.vm.statusMessage).toBe('Stream ended - click Start to reconnect')
      expect(wrapper.vm.isPlaying).toBe(false)
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

      await wrapper.vm.toggleAudio()
      wrapper.vm.handleAudioError({ target: { error: { code: 2 } } })

      expect(wrapper.vm.hasError).toBe(true)

      // Advance timers past the 4000ms duration
      vi.advanceTimersByTime(4000)

      expect(wrapper.vm.hasError).toBe(false)
    })

    it('toggleAudio does not set isPlaying when audio fails to start', async () => {
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
        destination: {},
        resume: vi.fn().mockRejectedValue(new Error('audio failed'))
      })))

      const wrapper = mountLiveFeed()
      await flushPromises()

      await wrapper.vm.toggleAudio()

      expect(wrapper.vm.isPlaying).toBe(false)
      expect(wrapper.vm.hasError).toBe(true)
    })
  })
})
