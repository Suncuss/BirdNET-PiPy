/**
 * Tests for BirdDetails.vue recordings section
 */

import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import BirdDetails from '@/views/BirdDetails.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
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
    constructor() {}
    destroy() {}
    update() {}
    resize() {}
    static getChart() { return null }
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
  licenseType: 'CC BY-SA'
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
        'router-link': RouterLinkStub
      }
    }
  })
}

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
    const wrapper = mountComponent()
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
    const wrapper = mountComponent()
    await flushPromises()

    const recordingsCall = mockApi.get.mock.calls.find(call =>
      call[0].includes('/recordings')
    )
    expect(recordingsCall[1].params.limit).toBe(16)
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

  it('switches to best recordings when selector changes', async () => {
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

    // Find and change the select element
    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)

    await select.setValue('best')
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

    // Change sort
    const select = wrapper.find('select')
    await select.setValue('best')
    await flushPromises()

    // Should be back on page 1 - find in the pagination section (buttons with single digit text)
    const paginationButtons = wrapper.findAll('button').filter(btn =>
      /^[1-4]$/.test(btn.text())
    )
    const page1Button = paginationButtons.find(btn => btn.text() === '1')
    expect(page1Button).toBeTruthy()
    expect(page1Button.classes()).toContain('bg-green-600')
  })

  it('shows selector with correct options', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)

    const options = select.findAll('option')
    expect(options.length).toBe(2)
    expect(options[0].text()).toBe('Most Recent')
    expect(options[0].element.value).toBe('recent')
    expect(options[1].text()).toBe('Best Recordings')
    expect(options[1].element.value).toBe('best')
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
