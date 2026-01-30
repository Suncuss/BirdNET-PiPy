import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import Dashboard from '@/views/Dashboard.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'

vi.mock('@/composables/useFetchBirdData')

// Mock chart libraries
vi.mock('chart.js/auto', () => {
  const ChartMock = function () { return { destroy: vi.fn(), update: vi.fn() } }
  ChartMock.register = vi.fn()
  ChartMock.getChart = vi.fn()
  return { default: ChartMock }
})
vi.mock('chartjs-chart-matrix', () => ({
  MatrixController: {},
  MatrixElement: {}
}))

const baseState = () => ({
  hourlyBirdActivityData: ref([]),
  detailedBirdActivityData: ref([]),
  latestObservationData: ref(null),
  recentObservationsData: ref([]),
  summaryData: ref({}),
  hourlyBirdActivityError: ref('skip chart'),
  detailedBirdActivityError: ref(null),
  latestObservationError: ref(null),
  recentObservationsError: ref(null),
  summaryError: ref(null),
  latestObservationimageUrl: ref('/default_bird.webp'),
  fetchDashboardData: vi.fn(),
  fetchChartsData: vi.fn()
})

const mockCanvasContext = {
  fillStyle: '',
  fillRect: vi.fn(),
  getImageData: vi.fn(() => ({ data: [] })),
  putImageData: vi.fn(),
  beginPath: vi.fn(),
  stroke: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  clearRect: vi.fn(),
  save: vi.fn(),
  restore: vi.fn(),
  fillText: vi.fn()
}

const mountDashboard = () => mount(Dashboard, {
  global: {
    stubs: {
      'font-awesome-icon': true,
      'router-link': true
    }
  }
})

describe('Dashboard', () => {
  let getContextSpy

  beforeEach(() => {
    vi.useFakeTimers()
    useFetchBirdData.mockReturnValue(baseState())
    getContextSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(mockCanvasContext)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('renders empty states when no data', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.text()).toContain('skip chart')
    expect(wrapper.text()).toContain('No observations available yet.')
    expect(wrapper.text()).toContain('No recent observations available.')
  })

  it('computes isDataEmpty as false when detailed activity has counts', async () => {
    const state = baseState()
    state.hourlyBirdActivityError = ref('skip chart')
    state.detailedBirdActivityData.value = [
      { species: 'Robin', hourlyActivity: [0, 1, 0] }
    ]
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.vm.isDataEmpty).toBe(false)
  })

  it('formats summary keys and values', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.vm.formatSummaryKey('mostActiveHour')).toBe('Most Active Hour')
    expect(wrapper.vm.formatSummaryValue('totalDetections', 1234)).toBe('1,234')
    expect(wrapper.vm.formatSummaryValue('mostActiveHour', '09:00')).toBe('09:00')
  })

  it('shows error messages when set', async () => {
    const state = baseState()
    state.hourlyBirdActivityError.value = 'Hourly fail'
    state.detailedBirdActivityError.value = 'Activity failed'
    state.latestObservationError.value = 'Latest failed'
    state.recentObservationsError.value = 'Recent failed'
    state.summaryError.value = 'Summary failed'
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.text()).toContain('Activity failed')
    expect(wrapper.text()).toContain('Latest failed')
    expect(wrapper.text()).toContain('Recent failed')
    expect(wrapper.text()).toContain('Summary failed')
    expect(wrapper.text()).toContain('Hourly fail')
  })

  it('formats timestamps to HH:MM', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    const formatted = wrapper.vm.formatTimestamp('2024-01-01T14:35:00Z')
    expect(formatted).toMatch(/\d{2}:\d{2}/)
  })

  it('initializes spectrogram canvas when latest observation data loads', async () => {
    const state = baseState()
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    // Canvas shouldn't exist yet (no data)
    expect(wrapper.find({ ref: 'spectrogramCanvas' }).exists()).toBe(false)

    // Simulate data loading
    state.latestObservationData.value = {
      common_name: 'Robin',
      scientific_name: 'Turdus migratorius',
      timestamp: '2024-01-01T12:00:00Z',
      bird_song_file_name: 'test.mp3'
    }
    await flushPromises()

    // Now canvas should exist and be initialized
    expect(wrapper.find({ ref: 'spectrogramCanvas' }).exists()).toBe(true)
    expect(getContextSpy).toHaveBeenCalled()
  })
})
