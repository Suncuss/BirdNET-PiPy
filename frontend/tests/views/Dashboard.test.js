import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import Dashboard from '@/views/Dashboard.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'
import { useAppStatus } from '@/composables/useAppStatus'

vi.mock('@/composables/useFetchBirdData')
vi.mock('@/composables/useAppStatus')

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
  setActivityOrder: vi.fn(),
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
    useAppStatus.mockReturnValue({
      locationConfigured: ref(true),
      isRestarting: ref(false),
      setLocationConfigured: vi.fn(),
      setRestarting: vi.fn(),
      isReady: vi.fn(() => true)
    })
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

  it('initializes spectrogram canvas when dashboard starts with data', async () => {
    const state = baseState()
    // Simulate fetchDashboardData populating the data
    state.fetchDashboardData.mockImplementation(() => {
      state.latestObservationData.value = {
        common_name: 'Robin',
        scientific_name: 'Turdus migratorius',
        timestamp: '2024-01-01T12:00:00Z',
        bird_song_file_name: 'test.mp3'
      }
    })
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    // Canvas should exist and be initialized after startDashboard runs
    expect(wrapper.find({ ref: 'spectrogramCanvas' }).exists()).toBe(true)
    expect(getContextSpy).toHaveBeenCalled()
  })

  it('does not reinitialize canvas on data refresh', async () => {
    const state = baseState()
    state.fetchDashboardData.mockImplementation(() => {
      state.latestObservationData.value = {
        common_name: 'Robin',
        scientific_name: 'Turdus migratorius',
        timestamp: '2024-01-01T12:00:00Z',
        bird_song_file_name: 'test.mp3'
      }
    })
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    // Canvas initialized once
    expect(getContextSpy).toHaveBeenCalledTimes(1)

    // Simulate data refresh (happens every 4.5 seconds)
    state.latestObservationData.value = {
      common_name: 'Blue Jay',
      scientific_name: 'Cyanocitta cristata',
      timestamp: '2024-01-01T12:05:00Z',
      bird_song_file_name: 'test2.mp3'
    }
    await flushPromises()

    // Canvas should NOT be reinitialized
    expect(getContextSpy).toHaveBeenCalledTimes(1)
  })
})
