import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import LiveFeed from '@/views/LiveFeed.vue'

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

const fetchMock = vi.fn()

const createFetchResponse = (data, ok = true) => ({
  ok,
  json: async () => data
})

describe('LiveFeed', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock.mockResolvedValue(createFetchResponse({
      stream_url: 'http://example.com/stream',
      stream_type: 'icecast'
    }))
    vi.stubGlobal('fetch', fetchMock)
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

    expect(fetchMock).toHaveBeenCalledWith('/api/stream/config')
    expect(wrapper.vm.streamUrl).toBe('http://example.com/stream')
    expect(wrapper.vm.streamType).toBe('icecast')
  })

  it('handles missing stream by updating status message', async () => {
    fetchMock.mockResolvedValueOnce(createFetchResponse({ stream_url: '', stream_type: 'none' }))
    const wrapper = mountLiveFeed()
    await flushPromises()

    expect(wrapper.text()).toContain('No audio stream available')
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
})
