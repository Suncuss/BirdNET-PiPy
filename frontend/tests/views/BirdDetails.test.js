/**
 * Tests for BirdDetails.vue recordings section
 */

import { mount, flushPromises, RouterLinkStub, enableAutoUnmount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import BirdDetails from '@/views/BirdDetails.vue'
import { useTimeFormat } from '@/composables/useTimeFormat'
import { deferred } from '../helpers/deferred'

enableAutoUnmount(afterEach)

// Real composable (not mocked): driving its singleton lets us assert the view
// reformats the backend's 24h "HH:00" peak time per the user's preference.
const { setTimeFormat } = useTimeFormat()

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn()
}))

const chartMockState = vi.hoisted(() => ({
  instances: []
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock vue-router
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { name: 'American Robin' }
  })
}))

// Mock Chart.js
vi.mock('chart.js/auto', () => ({
  default: class MockChart {
    constructor(canvas, config) {
      this.canvas = canvas
      this.config = config
      this.data = config.data
      this.options = config.options
      this.destroyed = false
      this.destroy = vi.fn(() => {
        this.destroyed = true
      })
      this.update = vi.fn()
      this.resize = vi.fn()
      chartMockState.instances.push(this)
    }

    static getChart(canvas) {
      return chartMockState.instances.find(chart => chart.canvas === canvas && !chart.destroyed) || null
    }
  }
}))

// Mock useSmartCrop composable
vi.mock('@/composables/useSmartCrop', () => ({
  useSmartCrop: () => ({
    calculateFocalPoint: vi.fn().mockResolvedValue('50% 50%'),
    processBirdImages: vi.fn().mockImplementation(async (birds) => {
      birds.forEach(bird => {
        bird.focalPoint = '50% 50%'
        bird.focalPointReady = true
      })
    }),
    useFocalPoint: () => ({
      focalPoint: { value: '50% 50%' },
      isReady: { value: true },
      updateFocalPoint: vi.fn().mockResolvedValue(undefined)
    }),
    clearCache: vi.fn()
  })
}))

const mockBirdDetails = {
  common_name: 'American Robin',
  display_common_name: 'Amsel',
  scientific_name: 'Turdus migratorius',
  total_visits: 50,
  first_detected: '2024-01-01T10:00:00',
  last_detected: '2024-01-15T14:30:00',
  average_confidence: 0.85,
  peak_activity_time: '06:00',
  seasonality: 'Year-round'
}

const mockImageData = {
  imageUrl: '/robin.jpg',
  pageUrl: 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
  authorName: 'John Doe',
  authorUrl: 'https://example.com/john',
  licenseType: 'CC BY-SA',
  hasCustomImage: false
}

const mockRecordings = [
  { id: 1, timestamp: '2024-01-15T14:30:00', confidence: 0.95, audio_filename: 'robin1.mp3', spectrogram_filename: 'robin1.webp' },
  { id: 2, timestamp: '2024-01-15T13:30:00', confidence: 0.92, audio_filename: 'robin2.mp3', spectrogram_filename: 'robin2.webp' },
  { id: 3, timestamp: '2024-01-15T12:30:00', confidence: 0.88, audio_filename: 'robin3.mp3', spectrogram_filename: 'robin3.webp' },
  { id: 4, timestamp: '2024-01-15T11:30:00', confidence: 0.85, audio_filename: 'robin4.mp3', spectrogram_filename: 'robin4.webp' },
  { id: 5, timestamp: '2024-01-15T10:30:00', confidence: 0.82, audio_filename: 'robin5.mp3', spectrogram_filename: 'robin5.webp' },
  { id: 6, timestamp: '2024-01-15T09:30:00', confidence: 0.80, audio_filename: 'robin6.mp3', spectrogram_filename: 'robin6.webp' },
  { id: 7, timestamp: '2024-01-15T08:30:00', confidence: 0.78, audio_filename: 'robin7.mp3', spectrogram_filename: 'robin7.webp' },
  { id: 8, timestamp: '2024-01-15T07:30:00', confidence: 0.75, audio_filename: 'robin8.mp3', spectrogram_filename: 'robin8.webp' }
]

const mockDistribution = {
  labels: ['Jan', 'Feb', 'Mar'],
  data: [10, 20, 15]
}

const mountComponent = () => {
  return mount(BirdDetails, {
    global: {
      stubs: {
        'router-link': RouterLinkStub,
        // Stub the modal so this page-level test doesn't need to mount its candidate grid.
        BirdImageModal: true
      }
    }
  })
}

beforeEach(() => {
  chartMockState.instances.length = 0
})

describe('BirdDetails Recordings Section', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Setup default API mock responses
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/bird/') && url.includes('/recordings')) {
        return Promise.resolve({ data: mockRecordings })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: mockDistribution })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: mockImageData })
      }
      return Promise.resolve({ data: {} })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads most recent recordings by default', async () => {
    mountComponent()
    await flushPromises()

    // Verify API call with sort=recent (default)
    const recordingsCall = mockApi.get.mock.calls.find(call =>
      call[0].includes('/recordings')
    )
    expect(recordingsCall).toBeTruthy()
    expect(recordingsCall[1].params.sort).toBe('recent')
    expect(recordingsCall[1].params.limit).toBe(16)
  })

  it('fetches with limit=16', async () => {
    mountComponent()
    await flushPromises()

    const recordingsCall = mockApi.get.mock.calls.find(call =>
      call[0].includes('/recordings')
    )
    expect(recordingsCall[1].params.limit).toBe(16)
  })

  it('displays localized common name when provided', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('Amsel')
  })

  it('displays 4 recordings per page', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // Should show first 4 recordings on page 1
    const audioElements = wrapper.findAll('audio')
    expect(audioElements.length).toBe(4)
  })

  it('shows pagination when more than 4 recordings', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // With 8 recordings, should have 2 pages
    const paginationButtons = wrapper.findAll('button').filter(btn =>
      /^[1-4]$/.test(btn.text())
    )
    expect(paginationButtons.length).toBe(2)
  })

  it('navigates between pages (frontend pagination)', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // Click page 2
    const page2Button = wrapper.findAll('button').find(btn => btn.text() === '2')
    expect(page2Button).toBeTruthy()
    await page2Button.trigger('click')
    await flushPromises()

    // Should not make a new API call (frontend pagination)
    const recordingsCalls = mockApi.get.mock.calls.filter(call =>
      call[0].includes('/recordings')
    )
    expect(recordingsCalls.length).toBe(1) // Only initial call
  })

  it('switches to best recordings when pill toggle is clicked', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // Clear mock calls from initial load
    vi.clearAllMocks()
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return Promise.resolve({ data: mockRecordings })
      }
      return Promise.resolve({ data: {} })
    })

    // Find and click the "Best" pill button
    const bestButton = wrapper.findAll('button').find(btn =>
      btn.text().includes('Best')
    )
    expect(bestButton).toBeTruthy()

    await bestButton.trigger('click')
    await flushPromises()

    // Verify new API call with sort=best
    const recordingsCall = mockApi.get.mock.calls.find(call =>
      call[0].includes('/recordings')
    )
    expect(recordingsCall).toBeTruthy()
    expect(recordingsCall[1].params.sort).toBe('best')
  })

  it('resets to page 1 when sort changes', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // Navigate to page 2
    const page2Button = wrapper.findAll('button').find(btn => btn.text() === '2')
    if (page2Button) {
      await page2Button.trigger('click')
      await flushPromises()
    }

    // Click the "Best" pill button to change sort
    const bestButton = wrapper.findAll('button').find(btn =>
      btn.text().includes('Best')
    )
    await bestButton.trigger('click')
    await flushPromises()

    // Should be back on page 1 - find in the pagination section (buttons with single digit text)
    const paginationButtons = wrapper.findAll('button').filter(btn =>
      /^[1-4]$/.test(btn.text())
    )
    const page1Button = paginationButtons.find(btn => btn.text() === '1')
    expect(page1Button).toBeTruthy()
    expect(page1Button.classes()).toContain('bg-green-600')
  })

  it('shows pill toggle with correct options', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    // Find pill toggle container (bg-gray-100 distinguishes it from the buttons inside)
    const pillContainer = wrapper.find('.bg-gray-100.rounded-full')
    expect(pillContainer.exists()).toBe(true)

    const pillButtons = pillContainer.findAll('button')
    expect(pillButtons.length).toBe(2)
    expect(pillButtons[0].text()).toContain('Recent')
    expect(pillButtons[1].text()).toContain('Best')
  })

  it('shows empty state when no recordings', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: mockDistribution })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: mockImageData })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('No recordings available')
  })

  it('does not show pagination when 4 or fewer recordings', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return Promise.resolve({ data: mockRecordings.slice(0, 4) }) // Only 4 recordings
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: mockDistribution })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: mockImageData })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountComponent()
    await flushPromises()

    // Should have recordings displayed
    const audioElements = wrapper.findAll('audio')
    expect(audioElements.length).toBe(4)

    // But no pagination buttons (1, 2, 3, 4)
    const paginationButtons = wrapper.findAll('button').filter(btn =>
      /^[1-4]$/.test(btn.text())
    )
    expect(paginationButtons.length).toBe(0)
  })
})

describe('BirdDetails Loading vs Empty States', () => {
  // Wire api.get with per-endpoint overrides; any omitted endpoint falls back
  // to the standard fixture.
  const setupApi = ({ recordings, distribution, image } = {}) => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return recordings ?? Promise.resolve({ data: mockRecordings })
      }
      if (url.includes('/detection_distribution')) {
        return distribution ?? Promise.resolve({ data: mockDistribution })
      }
      if (url.includes('/wikimedia_image')) {
        return image ?? Promise.resolve({ data: mockImageData })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      return Promise.resolve({ data: {} })
    })
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a recordings loader while the fetch is in flight, not the empty state', async () => {
    const pending = deferred()
    setupApi({ recordings: pending.promise.then(() => ({ data: mockRecordings })) })

    const wrapper = mountComponent()
    await flushPromises() // bird details resolve → page renders; recordings still pending

    expect(wrapper.text()).toContain('Loading recordings...')
    expect(wrapper.text()).not.toContain('No recordings available')

    pending.resolve()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Loading recordings...')
    expect(wrapper.findAll('audio').length).toBe(4)
  })

  it('shows the recordings empty state only once the fetch resolves empty', async () => {
    const pending = deferred()
    setupApi({ recordings: pending.promise.then(() => ({ data: [] })) })

    const wrapper = mountComponent()
    await flushPromises()

    // Still loading: must NOT prematurely claim there are no recordings.
    expect(wrapper.text()).not.toContain('No recordings available')

    pending.resolve()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Loading recordings...')
    expect(wrapper.text()).toContain('No recordings available')
  })

  it('shows a chart loader while the distribution fetch is in flight', async () => {
    const pending = deferred()
    setupApi({ distribution: pending.promise.then(() => ({ data: mockDistribution })) })

    const wrapper = mountComponent()
    await flushPromises() // page rendered; distribution still pending

    expect(wrapper.text()).toContain('Loading data...')
    expect(wrapper.text()).not.toContain('No detections in this period')

    pending.resolve()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Loading data...')
    expect(wrapper.text()).not.toContain('No detections in this period')
  })

  it('shows the chart empty state for a resolved period with no detections', async () => {
    setupApi({ distribution: Promise.resolve({ data: { labels: [], data: [] } }) })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Loading data...')
    expect(wrapper.text()).toContain('No detections in this period')
  })

  it('treats an all-zero distribution as empty (no bar-less chart)', async () => {
    setupApi({
      distribution: Promise.resolve({ data: { labels: ['Jan', 'Feb'], data: [0, 0] } })
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('No detections in this period')
  })

  it('keeps the chart visible when the period has detections', async () => {
    setupApi()

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Loading data...')
    expect(wrapper.text()).not.toContain('No detections in this period')
  })

  it('shows an error message when the initial chart fetch fails', async () => {
    const pending = deferred()
    setupApi({ distribution: pending.promise })

    const wrapper = mountComponent()
    pending.reject(new Error('boom'))
    await flushPromises()

    // Critical: a fetch failure must NOT masquerade as an empty period.
    expect(wrapper.text()).toContain("Couldn't load chart data")
    expect(wrapper.text()).not.toContain('No detections in this period')
    expect(wrapper.text()).not.toContain('Loading data...')
  })

  it('surfaces a re-fetch failure instead of leaving the prior chart visible', async () => {
    setupApi() // initial success
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.text()).not.toContain("Couldn't load chart data")

    // Re-mock the next distribution call to reject; navigate to a different
    // view to trigger updateChart.
    const pending = deferred()
    setupApi({ distribution: pending.promise })
    const dayButton = wrapper.findAll('button').find(btn => btn.text() === 'Day')
    expect(dayButton).toBeTruthy()
    await dayButton.trigger('click')
    pending.reject(new Error('boom'))
    await flushPromises()

    expect(wrapper.text()).toContain("Couldn't load chart data")
    expect(wrapper.text()).not.toContain('No detections in this period')
  })

  it('clears the chart error after a successful retry', async () => {
    const pending = deferred()
    setupApi({ distribution: pending.promise })
    const wrapper = mountComponent()
    pending.reject(new Error('boom'))
    await flushPromises()
    expect(wrapper.text()).toContain("Couldn't load chart data")

    // Restore a successful mock and trigger a navigation.
    setupApi()
    const dayButton = wrapper.findAll('button').find(btn => btn.text() === 'Day')
    await dayButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain("Couldn't load chart data")
    expect(wrapper.text()).not.toContain('No detections in this period')
  })
})

describe('BirdDetails Chart Resize', () => {
  const setupApi = () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return Promise.resolve({ data: mockRecordings })
      }
      if (url.includes('/detection_distribution')) {
        return Promise.resolve({ data: mockDistribution })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: mockImageData })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      return Promise.resolve({ data: {} })
    })
  }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    window.innerWidth = 390
    window.innerHeight = 844
    setupApi()
  })

  afterEach(() => {
    vi.useRealTimers()
    window.innerWidth = 1024
    window.innerHeight = 768
    vi.restoreAllMocks()
  })

  it('updates tick density in place on resize without refetching or rebuilding the chart', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    const chart = chartMockState.instances.at(-1)
    const initialDistributionCalls = mockApi.get.mock.calls.filter(call =>
      call[0].includes('/detection_distribution')
    ).length
    const initialChartCount = chartMockState.instances.length

    expect(chart.options.scales.x.ticks.maxTicksLimit).toBe(10)

    window.innerWidth = 900
    window.innerHeight = 600
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(250)

    const distributionCalls = mockApi.get.mock.calls.filter(call =>
      call[0].includes('/detection_distribution')
    ).length

    expect(chart.options.scales.x.ticks.maxTicksLimit).toBe(31)
    expect(chart.update).toHaveBeenCalledWith('none')
    expect(chart.resize).not.toHaveBeenCalled()
    expect(distributionCalls).toBe(initialDistributionCalls)
    expect(chartMockState.instances.length).toBe(initialChartCount)

    wrapper.unmount()
  })
})

describe('BirdDetails Custom Image', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows wikimedia image and attribution when no custom image', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/bird/') && url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: { labels: [], data: [] } })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: { ...mockImageData, hasCustomImage: false } })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('Photo by')
    expect(wrapper.text()).toContain('John Doe')
    expect(wrapper.text()).not.toContain('Custom image')
  })

  it('shows custom image label when hasCustomImage is true', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/bird/') && url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: { labels: [], data: [] } })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: { ...mockImageData, hasCustomImage: true } })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('Custom image')
    expect(wrapper.text()).toContain('Revert to default')
  })

  it('renders the customize-image cog button (no inline upload control)', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/bird/') && url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: { labels: [], data: [] } })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: { ...mockImageData, hasCustomImage: false } })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountComponent()
    await flushPromises()

    const customizeButton = wrapper.find('button[title="Customize image"]')
    expect(customizeButton.exists()).toBe(true)

    // The legacy inline upload button + hidden file input must be gone.
    expect(wrapper.find('button[title="Upload custom image"]').exists()).toBe(false)
    expect(wrapper.find('input[type="file"]').exists()).toBe(false)
  })

  it('reverts to wikimedia on delete', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/bird/') && url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/bird/') && url.includes('/detection_distribution')) {
        return Promise.resolve({ data: { labels: [], data: [] } })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: mockBirdDetails })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: { ...mockImageData, hasCustomImage: true } })
      }
      return Promise.resolve({ data: {} })
    })
    mockApi.delete.mockResolvedValue({ data: { hasCustomImage: false } })

    const wrapper = mountComponent()
    await flushPromises()

    // Should show custom image state
    expect(wrapper.text()).toContain('Custom image')

    // Click revert
    const revertButton = wrapper.findAll('button').find(btn => btn.text().includes('Revert'))
    expect(revertButton).toBeTruthy()
    await revertButton.trigger('click')
    await flushPromises()

    // Should have called delete API
    expect(mockApi.delete).toHaveBeenCalledWith('/bird/American Robin/image')

    // Should now show wikimedia attribution
    expect(wrapper.text()).toContain('Photo by')
  })
})

describe('BirdDetails Most Activity Time formatting', () => {
  // The backend always sends peak_activity_time as a 24-hour "HH:00" string.
  // The view must run it through useTimeFormat so it honors the 12h/24h
  // preference, exactly like Dashboard's "Most Active Hour".
  const setupApi = (details = mockBirdDetails) => {
    mockApi.get.mockImplementation((url) => {
      if (url.includes('/recordings')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/detection_distribution')) {
        return Promise.resolve({ data: { labels: [], data: [] } })
      }
      if (url.includes('/wikimedia_image')) {
        return Promise.resolve({ data: mockImageData })
      }
      if (url.includes('/bird/')) {
        return Promise.resolve({ data: details })
      }
      return Promise.resolve({ data: {} })
    })
  }

  // Scope assertions to the "Most Activity Time" line so other parts of the
  // page can't accidentally satisfy (or break) the match.
  const activityLineText = (wrapper) => {
    const line = wrapper.findAll('p').find((p) => p.text().includes('Most Activity Time'))
    return line ? line.text() : ''
  }

  beforeEach(() => {
    vi.clearAllMocks()
    setupApi()
  })

  afterEach(() => {
    // Clear the shared explicit choice so the format never leaks across tests.
    setTimeFormat(null)
    vi.restoreAllMocks()
  })

  it('renders the peak hour in 24-hour form when that preference is set', async () => {
    setTimeFormat('24h')
    const wrapper = mountComponent()
    await flushPromises()

    expect(activityLineText(wrapper)).toContain('06:00')
  })

  it('reformats the peak hour to 12-hour form when that preference is set', async () => {
    setTimeFormat('12h')
    const wrapper = mountComponent()
    await flushPromises()

    // Regression guard: the raw 24h "06:00" must be converted, not echoed.
    const text = activityLineText(wrapper)
    expect(text).toContain('6 AM')
    expect(text).not.toContain('06:00')
  })

  it('shows no time (never the literal "null") when the backend reports no peak hour', async () => {
    setTimeFormat('24h')
    setupApi({ ...mockBirdDetails, peak_activity_time: null })
    const wrapper = mountComponent()
    await flushPromises()

    const text = activityLineText(wrapper)
    expect(text).toContain('Most Activity Time:')
    expect(text).not.toContain('null')
  })
})
