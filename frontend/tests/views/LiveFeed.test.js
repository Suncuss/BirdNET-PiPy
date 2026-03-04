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
        stream_url: 'http://example.com/stream',
        stream_type: 'icecast'
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
    expect(wrapper.vm.streamUrl).toBe('http://example.com/stream')
    expect(wrapper.vm.streamType).toBe('icecast')
  })

  it('handles missing stream by updating status message', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { stream_url: '', stream_type: 'none' } })
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
      expect(wrapper.vm.statusMessage).toBe('Network error - stream unavailable')
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
