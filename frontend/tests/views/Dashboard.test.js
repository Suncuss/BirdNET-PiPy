import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, defineComponent, nextTick } from 'vue'
import Dashboard from '@/views/Dashboard.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'
import { useAppStatus } from '@/composables/useAppStatus'
import { useAudioPlayer } from '@/composables/useAudioPlayer'
import { useBirdCharts } from '@/composables/useBirdCharts'
import { useSystemUpdate } from '@/composables/useSystemUpdate'

vi.mock('@/composables/useFetchBirdData')
vi.mock('@/composables/useAppStatus')
vi.mock('@/composables/useAudioPlayer')
vi.mock('@/composables/useBirdCharts')
vi.mock('@/composables/useSystemUpdate')
vi.mock('@/services/media', () => ({
  getAudioUrl: vi.fn((f) => f ? `/audio/${f}` : null),
  getSpectrogramUrl: vi.fn((f) => `/spectrograms/${f}`)
}))

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
  hasLoadedOnce: ref(true),
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
  let mockStopAudio

  beforeEach(() => {
    vi.useFakeTimers()
    mockStopAudio = vi.fn()
    useFetchBirdData.mockReturnValue(baseState())
    useAppStatus.mockReturnValue({
      locationConfigured: ref(true),
      isRestarting: ref(false),
      setLocationConfigured: vi.fn(),
      setRestarting: vi.fn(),
      isReady: vi.fn(() => true)
    })
    useAudioPlayer.mockReturnValue({
      currentPlayingId: ref(null),
      togglePlay: vi.fn(),
      stopAudio: mockStopAudio,
      isPlaying: vi.fn(),
      isLoading: ref(false),
      error: ref(null),
      clearError: vi.fn()
    })
    useBirdCharts.mockReturnValue({
      createTotalObservationsChart: vi.fn(),
      createHourlyActivityHeatmap: vi.fn(),
      createHourlyActivityChart: vi.fn()
    })
    useSystemUpdate.mockReturnValue({
      checkForUpdates: vi.fn().mockResolvedValue({}),
      showUpdateIndicator: ref(false)
    })
    getContextSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(mockCanvasContext)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('shows loading state before first fetch completes', async () => {
    const state = baseState()
    state.hasLoadedOnce = ref(false)
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    const text = wrapper.text()

    // All sections should show loading text
    expect(text.match(/Fetching the latest data\.\.\./g)).toHaveLength(5)

    // Empty/error messages should NOT be visible
    expect(text).not.toContain('No bird activity recorded yet for today')
    expect(text).not.toContain('No observations available yet.')
    expect(text).not.toContain('No recent observations available.')
    expect(text).not.toContain('No summary data available for this period.')
    expect(text).not.toContain('skip chart')
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

  describe('keep-alive behavior', () => {
    const Placeholder = defineComponent({
      name: 'Placeholder',
      template: '<div>placeholder</div>'
    })

    const mountInKeepAlive = () => {
      const showDashboard = ref(true)
      const wrapper = mount(defineComponent({
        components: { Dashboard, Placeholder },
        setup() { return { showDashboard } },
        template: `
          <keep-alive include="Dashboard">
            <Dashboard v-if="showDashboard" />
            <Placeholder v-else />
          </keep-alive>
        `
      }), {
        global: {
          stubs: { 'font-awesome-icon': true, 'router-link': true }
        }
      })
      return { wrapper, showDashboard }
    }

    it('deactivation stops polling intervals', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Deactivate
      showDashboard.value = false
      await nextTick()

      // Advance past polling interval — polling should be stopped
      vi.advanceTimersByTime(20000)
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)
    })

    it('deactivation stops audio playback', async () => {
      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      // Deactivate
      showDashboard.value = false
      await nextTick()

      expect(mockStopAudio).toHaveBeenCalled()
    })

    it('activation after deactivation triggers data refresh and polling', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Deactivate
      showDashboard.value = false
      await nextTick()

      // Reactivate
      showDashboard.value = true
      await nextTick()
      await flushPromises()

      // Should have fetched again on reactivation
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('first activation does not duplicate fetch', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      mountInKeepAlive()
      await flushPromises()

      // Only one fetch from onMounted/startDashboard, not a second from onActivated
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)
    })

    it('visibility handler does not run when deactivated', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Deactivate
      showDashboard.value = false
      await nextTick()

      state.fetchDashboardData.mockClear()

      // Simulate visibility change while deactivated
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()

      // Handler should be gated by isActive — no fetch
      expect(state.fetchDashboardData).not.toHaveBeenCalled()
    })

    it('deactivation during in-flight visibility fetch prevents polling restart', async () => {
      const state = baseState()
      let resolveFetch
      state.fetchDashboardData
        .mockResolvedValueOnce()  // startDashboard
        .mockImplementationOnce(() => new Promise(resolve => { resolveFetch = resolve }))  // visibility handler
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      // Trigger visibility handler (tab becomes visible) — fetch is deferred
      document.dispatchEvent(new Event('visibilitychange'))

      // Deactivate while visibility fetch is pending
      showDashboard.value = false
      await nextTick()

      // Resolve the deferred fetch
      resolveFetch()
      await flushPromises()

      // Advance timers — polling should NOT be running
      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only 2 calls: startDashboard + visibility handler, no interval-driven ones
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('deactivation during in-flight activation fetch prevents polling restart', async () => {
      const state = baseState()
      let resolveFetch
      // First call (startDashboard) resolves immediately; second (onActivated) is deferred
      state.fetchDashboardData
        .mockResolvedValueOnce()
        .mockImplementationOnce(() => new Promise(resolve => { resolveFetch = resolve }))
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      // Deactivate then reactivate — onActivated calls fetchDashboardData (deferred)
      showDashboard.value = false
      await nextTick()
      showDashboard.value = true
      await nextTick()

      // Deactivate again while fetch is still pending
      showDashboard.value = false
      await nextTick()

      // Now resolve the deferred fetch
      resolveFetch()
      await flushPromises()

      // Advance timers — polling should NOT be running
      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only the 2 explicit fetchDashboardData calls, no interval-driven ones
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('rapid reactivation discards stale activation fetch', async () => {
      const state = baseState()
      let resolveStale
      state.fetchDashboardData
        .mockResolvedValueOnce()  // startDashboard
        .mockImplementationOnce(() => new Promise(resolve => { resolveStale = resolve }))  // stale onActivated
        .mockResolvedValue()  // fresh onActivated
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      await flushPromises()

      // Deactivate then reactivate — onActivated #1 starts (deferred fetch)
      showDashboard.value = false
      await nextTick()
      showDashboard.value = true
      await nextTick()

      // Quickly deactivate and reactivate again — onActivated #2 starts and completes
      showDashboard.value = false
      await nextTick()
      showDashboard.value = true
      await nextTick()
      await flushPromises()

      state.fetchDashboardData.mockClear()

      // Resolve stale #1 — it should bail out (activationId changed)
      resolveStale()
      await flushPromises()

      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only interval-driven fetches from #2's polling, not doubled by #1
      expect(state.fetchDashboardData.mock.calls.length).toBe(2)
    })

    it('visibility handler still works after deactivation during initial startDashboard', async () => {
      const state = baseState()
      let resolveFetch
      // First call (startDashboard) is deferred so we can deactivate mid-fetch
      state.fetchDashboardData
        .mockImplementationOnce(() => new Promise(resolve => { resolveFetch = resolve }))
        .mockResolvedValue()
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard } = mountInKeepAlive()
      // startDashboard is awaiting fetchDashboardData — deactivate before it resolves
      showDashboard.value = false
      await nextTick()

      // Resolve the initial fetch — startDashboard bails out via isActive check
      resolveFetch()
      await flushPromises()

      // Reactivate — onActivated fetches and starts polling
      showDashboard.value = true
      await nextTick()
      await flushPromises()

      state.fetchDashboardData.mockClear()

      // Simulate tab becoming visible — visibility handler should work
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()

      // Handler was registered before the await, so it should fire
      expect(state.fetchDashboardData).toHaveBeenCalled()
    })
  })
})
