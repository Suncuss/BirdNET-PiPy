import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, defineComponent, nextTick } from 'vue'
import Dashboard from '@/views/Dashboard.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'
import { useAppStatus } from '@/composables/useAppStatus'
import { useAudioPlayer } from '@/composables/useAudioPlayer'
import { useBirdCharts } from '@/composables/useBirdCharts'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { useTimeFormat } from '@/composables/useTimeFormat'
import { recordingPath } from '@/utils/detectionLinks'
import { useAuth } from '@/composables/useAuth'

vi.mock('@/composables/useFetchBirdData')
vi.mock('@/composables/useAppStatus')
vi.mock('@/composables/useAudioPlayer')
vi.mock('@/composables/useBirdCharts')
vi.mock('@/composables/useSystemUpdate')
vi.mock('@/services/media', () => ({
  getAudioUrl: vi.fn((f) => f ? `/audio/${f}` : null),
  getSpectrogramUrl: vi.fn((f) => `/spectrograms/${f}`)
}))
// Dashboard itself doesn't read the route, but the real DetectionModal
// (rendered by most mounts here) watches it to self-dismiss on navigation.
vi.mock('vue-router', () => ({
  useRoute: () => ({ fullPath: '/' })
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
  summaryLoading: ref({}),
  summaryErrors: ref({}),
  latestObservationimageUrl: ref('default_bird.webp'),
  hasLoadedOnce: ref(true),
  fetchDashboardData: vi.fn(),
  fetchSummaryData: vi.fn(),
  setActivityOrder: vi.fn(),
  setRecentObsMode: vi.fn(),
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
  createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
  save: vi.fn(),
  restore: vi.fn(),
  fillText: vi.fn()
}

// happy-dom's document.hidden is a prototype getter; shadow it with an own
// property so tests can simulate tab visibility (removed again in afterEach).
const setTabHidden = (hidden) => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

const hideTab = () => {
  setTabHidden(true)
  document.dispatchEvent(new Event('visibilitychange'))
}

// Come back to the tab after awayMs, firing the 0-delay refresh poll if the
// return scheduled one (stale data).
const returnToTab = async (awayMs = 0) => {
  vi.advanceTimersByTime(awayMs)
  setTabHidden(false)
  document.dispatchEvent(new Event('visibilitychange'))
  vi.advanceTimersByTime(0)
  await flushPromises()
}

const mountDashboard = () => mount(Dashboard, {
  global: {
    stubs: {
      'font-awesome-icon': true,
      'router-link': true,
      'CenteredMessage': false // render real component for text assertions
    }
  }
})

describe('Dashboard', () => {
  let getContextSpy
  let mockStopAudio

  beforeEach(() => {
    vi.useFakeTimers()
    Object.values(mockCanvasContext).forEach((mock) => {
      if (vi.isMockFunction(mock)) mock.mockClear()
    })
    mockCanvasContext.getImageData.mockReturnValue({ data: [] })
    mockCanvasContext.createLinearGradient.mockImplementation(() => ({ addColorStop: vi.fn() }))
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
      freezeChart: vi.fn(),
      createTotalObservationsChart: vi.fn(),
      createHourlyActivityHeatmap: vi.fn(),
      createHourlyActivityChart: vi.fn(),
      speciesAxisLayout: ref({ ticks: [], axisLeft: 0, axisWidth: 0, rowHeight: 0 }),
      timeAxisLayout: ref({ ticks: [], axisLeft: 0, axisTop: 0, axisHeight: 0, colWidth: 0, date: null })
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
    vi.unstubAllGlobals()
    delete document.hidden  // drop any setTabHidden override (restores the prototype getter)
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
    // Force 24h so the most-active-hour assertion is locale-independent
    useTimeFormat().setTimeFormat('24h')
    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.vm.formatSummaryKey('mostActiveHour')).toBe('Most Active Hour')
    // Species-named keys (detections aren't only birds) label themselves
    expect(wrapper.vm.formatSummaryKey('mostCommonSpecies')).toBe('Most Common Species')
    expect(wrapper.vm.formatSummaryKey('rarestSpecies')).toBe('Rarest Species')
    expect(wrapper.vm.formatSummaryValue('totalDetections', 1234)).toBe('1,234')
    expect(wrapper.vm.formatSummaryValue('mostActiveHour', '09:00')).toBe('09:00')
    expect(wrapper.vm.formatSummaryValue('mostActiveHour', 'N/A')).toBe('N/A')

    // 12h mode formats the same value differently
    useTimeFormat().setTimeFormat('12h')
    expect(wrapper.vm.formatSummaryValue('mostActiveHour', '09:00')).toBe('9 AM')
  })

  it('lazy-loads a summary tab when its period has not been fetched', async () => {
    const state = baseState()
    state.summaryData.value = {
      today: { totalObservations: 12 }
    }
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    const weekButton = wrapper.findAll('button').find(b => b.text() === '7-Day')
    expect(weekButton).toBeTruthy()

    await weekButton.trigger('click')
    await flushPromises()

    expect(wrapper.vm.currentSummaryPeriod).toBe('week')
    expect(state.fetchSummaryData).toHaveBeenCalledWith('week')
  })

  it('reuses an already-loaded summary tab without another request', async () => {
    const state = baseState()
    state.summaryData.value = {
      today: { totalObservations: 12 },
      week: { totalObservations: 34 }
    }
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    const weekButton = wrapper.findAll('button').find(b => b.text() === '7-Day')
    await weekButton.trigger('click')
    await flushPromises()

    expect(wrapper.vm.currentSummaryPeriod).toBe('week')
    expect(state.fetchSummaryData).not.toHaveBeenCalled()
  })

  it('shows the existing loading treatment for a lazy summary tab', async () => {
    const state = baseState()
    state.summaryLoading.value = { week: true }
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountDashboard()
    await flushPromises()

    const weekButton = wrapper.findAll('button').find(b => b.text() === '7-Day')
    await weekButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Fetching the latest data...')
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

    mountDashboard()
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

  it('clamps live spectrogram rendering to available analyser bins', async () => {
    const state = baseState()
    state.latestObservationData.value = {
      common_name: 'Robin',
      scientific_name: 'Turdus migratorius',
      timestamp: '2024-01-01T12:00:00Z',
      confidence: 0.91,
      bird_song_file_name: 'low-rate.mp3'
    }
    useFetchBirdData.mockReturnValue(state)

    const addColorStop = vi.fn((_, color) => {
      if (typeof color !== 'string') {
        throw new Error(`Invalid spectrogram color: ${String(color)}`)
      }
    })
    mockCanvasContext.createLinearGradient.mockReturnValue({ addColorStop })
    // Capture the rAF callback so the test can drive draw frames with controlled
    // timestamps (the spectrogram is paced by wall-clock time, not per-frame).
    let drawFrame = null
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => { drawFrame = cb; return 1 }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    // happy-dom reports offsetWidth/Height 0 (no layout); give the canvas a real size
    // so initializeCanvas computes a non-zero backing store and the scroll can advance.
    vi.spyOn(HTMLCanvasElement.prototype, 'offsetWidth', 'get').mockReturnValue(600)
    vi.spyOn(HTMLCanvasElement.prototype, 'offsetHeight', 'get').mockReturnValue(200)
    vi.stubGlobal('Audio', vi.fn().mockImplementation(function MockAudio(src) {
      this.src = src
      this.crossOrigin = ''
      this.pause = vi.fn()
      const listeners = {}
      this.addEventListener = vi.fn((type, cb) => { listeners[type] = cb })
      // Fire 'playing' synchronously so the draw gate (audioClockRunning) is open
      // by the time the test drives the rAF draw frames below.
      this.play = vi.fn(() => {
        listeners.playing?.()
        return Promise.resolve()
      })
    }))

    const analyser = {
      fftSize: 1024,
      frequencyBinCount: 512,
      smoothingTimeConstant: 0.8,
      minDecibels: -100,
      maxDecibels: -30,
      connect: vi.fn(),
      // Non-silent waveform so the digital-silence gate lets the draw proceed.
      getFloatTimeDomainData: vi.fn((array) => { array.fill(0.05) }),
      getFloatFrequencyData: vi.fn((array) => {
        for (let i = 0; i < array.length; i++) {
          // Synthetic dB values spanning the full window so dbToLutIndex hits both clamps.
          array[i] = -120 + (i % 121)
        }
      })
    }
    const sourceNode = { connect: vi.fn() }
    vi.stubGlobal('AudioContext', vi.fn().mockImplementation(function MockAudioContext() {
      this.sampleRate = 22050
      this.state = 'running'
      this.destination = {}
      this.createAnalyser = vi.fn(() => analyser)
      this.createMediaElementSource = vi.fn(() => sourceNode)
      this.resume = vi.fn().mockResolvedValue()
      this.close = vi.fn().mockResolvedValue()
    }))

    const wrapper = mountDashboard()
    await flushPromises()

    wrapper.vm.playLatestObservation()

    // Wall-clock pacing: the first frame only establishes the time baseline (draws
    // nothing); the second, one normal frame later, paints one set of columns. (The
    // gap must stay below the pacer's stall threshold, or it would be dropped.)
    drawFrame(0)
    drawFrame(1000 / 60)

    expect(analyser.getFloatFrequencyData).toHaveBeenCalled()
    // 12 kHz cap exceeds available bins at 22050 Hz / fftSize 1024, so loop clamps to 512 bins.
    expect(mockCanvasContext.createLinearGradient).toHaveBeenCalledTimes(512)
    expect(addColorStop).toHaveBeenCalledTimes(1024)

    wrapper.unmount()
  })

  // When the clip runs out of samples the Web Audio graph goes silent slightly
  // before the media element fires 'pause'/'ended' (the element's clock trails
  // the graph by the output latency). The draw loop must freeze on that digital
  // silence instead of scrolling a strip of blank columns in at the right edge.
  it('freezes the scroll while the analyser carries only digital silence', async () => {
    const state = baseState()
    state.latestObservationData.value = {
      common_name: 'Robin',
      scientific_name: 'Turdus migratorius',
      timestamp: '2024-01-01T12:00:00Z',
      confidence: 0.91,
      bird_song_file_name: 'clip.mp3'
    }
    useFetchBirdData.mockReturnValue(state)

    let drawFrame = null
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => { drawFrame = cb; return 1 }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(HTMLCanvasElement.prototype, 'offsetWidth', 'get').mockReturnValue(600)
    vi.spyOn(HTMLCanvasElement.prototype, 'offsetHeight', 'get').mockReturnValue(200)
    vi.stubGlobal('Audio', vi.fn().mockImplementation(function MockAudio(src) {
      this.src = src
      this.crossOrigin = ''
      this.pause = vi.fn()
      const listeners = {}
      this.addEventListener = vi.fn((type, cb) => { listeners[type] = cb })
      this.play = vi.fn(() => {
        listeners.playing?.()
        return Promise.resolve()
      })
    }))

    // Waveform output the test flips between real signal and digital silence,
    // emulating the source running dry ahead of the 'pause'/'ended' events.
    let waveformAmplitude = 0.05
    const analyser = {
      fftSize: 1024,
      frequencyBinCount: 512,
      connect: vi.fn(),
      getFloatTimeDomainData: vi.fn((array) => { array.fill(waveformAmplitude) }),
      getFloatFrequencyData: vi.fn((array) => { array.fill(-60) })
    }
    vi.stubGlobal('AudioContext', vi.fn().mockImplementation(function MockAudioContext() {
      this.sampleRate = 22050
      this.state = 'running'
      this.destination = {}
      this.createAnalyser = vi.fn(() => analyser)
      this.createMediaElementSource = vi.fn(() => ({ connect: vi.fn() }))
      this.resume = vi.fn().mockResolvedValue()
      this.close = vi.fn().mockResolvedValue()
    }))

    const wrapper = mountDashboard()
    await flushPromises()

    wrapper.vm.playLatestObservation()

    // Baseline frame, then one normal frame later: columns get painted.
    drawFrame(0)
    drawFrame(1000 / 60)
    const paintedColumns = mockCanvasContext.createLinearGradient.mock.calls.length
    expect(paintedColumns).toBeGreaterThan(0)

    // The clip's samples run out; the graph now feeds pure zeros while the
    // media clock (and its events) lag behind. Nothing may scroll or paint.
    waveformAmplitude = 0
    drawFrame(2000 / 60)
    drawFrame(3000 / 60)
    expect(mockCanvasContext.createLinearGradient).toHaveBeenCalledTimes(paintedColumns)
    // The gate exits before the frequency read: both pre-silence frames read it
    // (baseline + painted), the silent frames added nothing.
    expect(analyser.getFloatFrequencyData).toHaveBeenCalledTimes(2)

    // Signal returns (e.g. user replays): the pacer was reset while frozen, so
    // one baseline frame re-arms it and the next paints again — no jump.
    waveformAmplitude = 0.05
    drawFrame(4000 / 60)
    expect(mockCanvasContext.createLinearGradient).toHaveBeenCalledTimes(paintedColumns)
    drawFrame(5000 / 60)
    expect(mockCanvasContext.createLinearGradient.mock.calls.length).toBeGreaterThan(paintedColumns)

    wrapper.unmount()
  })

  // The latest observation card (image, common + scientific names, timestamp)
  // and the recent observations list's names open THIS detection's player in
  // the in-place DetectionModal on a plain click, while staying real links to
  // the detection permalink so modified clicks (⌘/Ctrl/middle) open it in a
  // new tab.
  describe('detection links → detection detail modal', () => {
    const observation = {
      id: 42,
      common_name: 'Blue Jay',
      scientific_name: 'Cyanocitta cristata',
      timestamp: '2024-01-01T12:30:00Z',
      confidence: 0.93,
      bird_song_file_name: 'jay.mp3'
    }

    const mountWithModalStub = () => mount(Dashboard, {
      global: {
        stubs: {
          'font-awesome-icon': true,
          'router-link': true,
          DetectionModal: true,
          CenteredMessage: false
        }
      }
    })

    const setup = async () => {
      const state = baseState()
      state.latestObservationData.value = { ...observation }
      state.recentObservationsData.value = [{ ...observation }]
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountWithModalStub()
      await flushPromises()
      return wrapper
    }

    const birdNameLinks = (wrapper) => wrapper.findAll('a')
      .filter((a) => a.attributes('href') === recordingPath('Blue Jay', 42))

    it('all detection links are real hrefs to the permalink (new-tab clicks work)', async () => {
      const wrapper = await setup()

      // Latest card: image, common + scientific names; recent observations
      // row: name. Timestamp/confidence rows are deliberately plain text —
      // identity elements are the click targets, metadata isn't.
      const links = birdNameLinks(wrapper)
      expect(links).toHaveLength(4)
      expect(links.some(l => l.find('img').exists())).toBe(true)
      expect(wrapper.text()).toContain('93%')
      expect(wrapper.findAll('a').some(l => l.text().includes('93%'))).toBe(false)
    })

    it('a plain click opens the detection modal for that detection instead of navigating', async () => {
      const wrapper = await setup()

      for (const link of birdNameLinks(wrapper)) {
        await link.trigger('click')

        const modal = wrapper.findComponent({ name: 'DetectionModal' })
        expect(modal.props('isVisible')).toBe(true)
        expect(modal.props('id')).toBe(42)
        expect(modal.props('name')).toBe('Blue Jay')

        await modal.vm.$emit('close')
        expect(wrapper.findComponent({ name: 'DetectionModal' }).props('isVisible')).toBe(false)
      }
    })

    it('a modified click falls through to the link and does not open the modal', async () => {
      const wrapper = await setup()

      const preventDefault = vi.fn()
      wrapper.vm.onInfoClick({ metaKey: true, preventDefault }, observation)

      expect(preventDefault).not.toHaveBeenCalled()
      await nextTick()
      expect(wrapper.findComponent({ name: 'DetectionModal' }).props('isVisible')).toBe(false)
    })
  })

  it('hides the Bird Activity reverse toggle when data is empty', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    // Default state: hasLoadedOnce=true, no detailed activity data => isDataEmpty=true
    expect(wrapper.vm.isDataEmpty).toBe(true)
    const reverseButton = wrapper.findAll('button').find(b => b.text().includes('Reverse'))
    expect(reverseButton).toBeFalsy()
  })

  describe('activity overview row sizing', () => {
    const speciesRows = (n) => Array.from({ length: n }, (_, i) => ({
      species: `Species ${i}`,
      hourlyActivity: [1, ...Array(23).fill(0)]
    }))

    // Controllable matchMedia stub: Dashboard reads .matches at setup and
    // listens for 'change' — dispatch() drives a tier flip.
    const stubViewportTier = (matches) => {
      const listeners = new Set()
      const mql = {
        matches,
        addEventListener: (_, fn) => listeners.add(fn),
        removeEventListener: (_, fn) => listeners.delete(fn),
        dispatch (next) {
          this.matches = next
          listeners.forEach(fn => fn({ matches: next }))
        },
        get listenerCount () { return listeners.size }
      }
      vi.stubGlobal('matchMedia', vi.fn(() => mql))
      return mql
    }

    beforeEach(() => {
      const state = baseState()
      state.detailedBirdActivityData.value = speciesRows(20)
      useFetchBirdData.mockReturnValue(state)
    })

    it('renders 10 rows in the compact card on laptop-sized viewports', async () => {
      stubViewportTier(false)
      const wrapper = mountDashboard()
      await flushPromises()

      expect(useBirdCharts().createTotalObservationsChart.mock.lastCall[1]).toHaveLength(10)
      expect(wrapper.html()).toContain('lg:h-[375px]')
    })

    it('renders 15 rows in a taller card on tall desktop viewports', async () => {
      stubViewportTier(true)
      const wrapper = mountDashboard()
      await flushPromises()

      // Both canvases get the same sliced list (lockstep)
      expect(useBirdCharts().createTotalObservationsChart.mock.lastCall[1]).toHaveLength(15)
      expect(useBirdCharts().createHourlyActivityHeatmap.mock.lastCall[1]).toHaveLength(15)
      expect(wrapper.html()).toContain('lg:h-[500px]')
    })

    it('gates the tall tier on lg width and the tall-viewport height', async () => {
      stubViewportTier(false)
      mountDashboard()
      await flushPromises()

      expect(window.matchMedia).toHaveBeenCalledWith(
        '(min-width: 1024px) and (min-height: 1150px)'
      )
    })

    it('redraws with the new tier when the media query flips', async () => {
      const mql = stubViewportTier(false)
      const wrapper = mountDashboard()
      await flushPromises()

      mql.dispatch(true)
      await flushPromises()
      expect(useBirdCharts().createTotalObservationsChart.mock.lastCall[1]).toHaveLength(15)
      expect(wrapper.html()).toContain('lg:h-[500px]')

      mql.dispatch(false)
      await flushPromises()
      expect(useBirdCharts().createTotalObservationsChart.mock.lastCall[1]).toHaveLength(10)
      expect(wrapper.html()).toContain('lg:h-[375px]')
    })

    it('removes its media-query listener on unmount', async () => {
      const mql = stubViewportTier(false)
      const wrapper = mountDashboard()
      await flushPromises()
      expect(mql.listenerCount).toBe(1)

      wrapper.unmount()
      expect(mql.listenerCount).toBe(0)
    })
  })

  describe('unique species toggle', () => {
    it('renders pill toggle with All and Unique options', async () => {
      const wrapper = mountDashboard()
      await flushPromises()

      // Find the recent observations toggle container (pill group next to "Recent Observations" heading)
      const pillGroups = wrapper.findAll('.bg-gray-100.rounded-full')
      // There are multiple pill groups (summary periods, activity order, recent obs filter)
      // Find the one containing a button with text "Unique" or "Uniq"
      const recentObsGroup = pillGroups.find(g =>
        g.findAll('button').some(b => b.text().includes('Uniq'))
      )
      expect(recentObsGroup).toBeTruthy()
      expect(recentObsGroup.findAll('button').length).toBe(2)
    })

    it('Unique is selected by default', async () => {
      const wrapper = mountDashboard()
      await flushPromises()

      // Find the pill toggle buttons for recent observations filter
      const allButtons = wrapper.findAll('button')
      const uniqueBtn = allButtons.find(b => b.text().includes('Uniq') && b.classes().some(c => c.includes('bg-white')))
      expect(uniqueBtn).toBeTruthy()
    })

    it('clicking All calls setRecentObsMode instantly', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountDashboard()
      await flushPromises()

      // Find the All button inside the recent-obs pill group ("All" alone
      // would also match the summary "All Time" pill)
      const recentObsGroup = wrapper.findAll('.bg-gray-100.rounded-full').find(g =>
        g.findAll('button').some(b => b.text().includes('Uniq'))
      )
      const allBtn = recentObsGroup.findAll('button').find(b => b.text().includes('All'))
      expect(allBtn).toBeTruthy()

      await allBtn.trigger('click')
      await flushPromises()

      // setRecentObsMode should be called with 'all' (no network fetch)
      expect(state.setRecentObsMode).toHaveBeenCalledWith('all')
    })
  })

  describe('post-login refetch', () => {
    // Real (unmocked) useAuth singleton — reset so state can't leak
    afterEach(() => {
      useAuth().resetState()
    })

    const mountLoggedOut = ({ publicAccess = true } = {}) => {
      const auth = useAuth()
      auth.resetState()
      // Auth enabled, visitor not authenticated
      auth.authStatus.value.authEnabled = true
      auth.authStatus.value.publicAccess = publicAccess
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)
      const wrapper = mountDashboard()
      return { auth, state, wrapper }
    }

    it('refetches dashboard data as soon as login succeeds', async () => {
      const { auth, state } = mountLoggedOut()
      await flushPromises()
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Login flips isAuthenticated — must not wait for the next poll tick
      auth.authStatus.value.authenticated = true
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('does not refetch on auth-state churn while still logged out', async () => {
      const { auth, state } = mountLoggedOut()
      await flushPromises()
      state.fetchDashboardData.mockClear()

      auth.authStatus.value.publicFeatures = ['charts']
      await flushPromises()

      expect(state.fetchDashboardData).not.toHaveBeenCalled()
    })

    it('renders a blank shell behind the login modal when public access is off', async () => {
      const { auth, wrapper } = mountLoggedOut({ publicAccess: false })
      await flushPromises()

      // No panels, no error text — same empty shell as auth-guarded routes
      expect(wrapper.text()).not.toContain('Recent Observations')

      // Signing in mounts the dashboard content
      auth.authStatus.value.authenticated = true
      await flushPromises()
      expect(wrapper.text()).toContain('Recent Observations')
    })

    it('keeps the limited public dashboard visible when public access is on', async () => {
      const { wrapper } = mountLoggedOut({ publicAccess: true })
      await flushPromises()

      expect(wrapper.text()).toContain('Recent Observations')
    })
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
          stubs: { 'font-awesome-icon': true, 'router-link': true, 'CenteredMessage': false }
        }
      })
      // Toggle the keep-alive slot. deactivate() advances awayMs afterwards;
      // reactivate() fires the 0-delay refresh poll if activation scheduled one.
      const deactivate = async (awayMs = 0) => {
        showDashboard.value = false
        await nextTick()
        vi.advanceTimersByTime(awayMs)
      }
      const reactivate = async () => {
        showDashboard.value = true
        await nextTick()
        await flushPromises()
        vi.advanceTimersByTime(0)
        await flushPromises()
      }
      return { wrapper, showDashboard, deactivate, reactivate }
    }

    it('deactivation stops polling intervals', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { deactivate } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      await deactivate()

      // Advance past polling interval — polling should be stopped
      vi.advanceTimersByTime(20000)
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)
    })

    it('deactivation during in-flight poll tick prevents rescheduling', async () => {
      const state = baseState()
      let resolvePollFetch
      state.fetchDashboardData
        .mockResolvedValueOnce()  // startDashboard
        .mockImplementationOnce(() => new Promise(resolve => { resolvePollFetch = resolve }))  // poll tick
      useFetchBirdData.mockReturnValue(state)

      const { deactivate } = mountInKeepAlive()
      await flushPromises()

      // Fire the first poll tick — its fetch is deferred
      vi.advanceTimersByTime(9000)
      await flushPromises()

      // Deactivate while poll fetch is pending
      await deactivate()

      // Resolve the deferred poll fetch
      resolvePollFetch()
      await flushPromises()

      // Advance timers — poll should NOT have rescheduled itself
      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only 2 calls: startDashboard + the one poll tick, nothing after deactivation
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('deactivation stops audio playback', async () => {
      const { deactivate } = mountInKeepAlive()
      await flushPromises()

      await deactivate()

      expect(mockStopAudio).toHaveBeenCalled()
    })

    it('activation after a stale deactivation refreshes immediately and resumes polling', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { deactivate, reactivate } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Deactivate, then let the data go stale (>= poll interval)
      await deactivate(9000)

      // Reactivate — the immediate (0-delay) refresh poll should fire
      await reactivate()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)

      // And the regular cadence continues from there
      vi.advanceTimersByTime(9000)
      await flushPromises()
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(3)
    })

    it('quick away-and-back reactivation skips the refetch but resumes polling', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { deactivate, reactivate } = mountInKeepAlive()
      await flushPromises()

      // Deactivate for only 2 seconds — data is still fresh
      await deactivate(2000)
      await reactivate()

      // No immediate refetch
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Next poll fires 9s after the last fetch, not 9s after reactivation
      vi.advanceTimersByTime(7000)
      await flushPromises()
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

      const { deactivate } = mountInKeepAlive()
      await flushPromises()

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      await deactivate()

      state.fetchDashboardData.mockClear()

      // Simulate visibility change while deactivated
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()

      // Handler should be gated by isActive — no fetch
      expect(state.fetchDashboardData).not.toHaveBeenCalled()
    })

    it('deactivation during an in-flight return-refresh prevents polling restart', async () => {
      const state = baseState()
      let resolveFetch
      state.fetchDashboardData
        .mockResolvedValueOnce()  // startDashboard
        .mockImplementationOnce(() => new Promise(resolve => { resolveFetch = resolve }))  // return refresh
      useFetchBirdData.mockReturnValue(state)

      const { deactivate } = mountInKeepAlive()
      await flushPromises()

      // Hide, go stale, return — schedules the immediate refresh poll,
      // whose fetch is held open
      hideTab()
      await returnToTab(9000)

      // Deactivate while the refresh fetch is pending
      await deactivate()

      resolveFetch()
      await flushPromises()

      // Advance timers — polling should NOT be running
      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only 2 calls: startDashboard + the return refresh, no interval-driven ones
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('deactivation during an in-flight activation refresh prevents polling restart', async () => {
      const state = baseState()
      let resolveFetch
      // First call (startDashboard) resolves immediately; the activation refresh is deferred
      state.fetchDashboardData
        .mockResolvedValueOnce()
        .mockImplementationOnce(() => new Promise(resolve => { resolveFetch = resolve }))
      useFetchBirdData.mockReturnValue(state)

      const { deactivate, reactivate } = mountInKeepAlive()
      await flushPromises()

      // Deactivate, go stale, reactivate — the 0-delay refresh poll fires,
      // and its fetch is held open
      await deactivate(9000)
      await reactivate()

      // Deactivate again while the fetch is still pending
      await deactivate()

      // Now resolve the deferred fetch
      resolveFetch()
      await flushPromises()

      // Advance timers — polling should NOT be running
      vi.advanceTimersByTime(20000)
      await flushPromises()

      // Only the 2 fetchDashboardData calls, no interval-driven ones
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('rapid reactivation does not start a second poll loop', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)
      // Hold activation #1 open inside redrawCharts by deferring its first
      // chart draw (baseState is empty, so startDashboard never draws).
      let resolveRedraw
      useBirdCharts().createTotalObservationsChart.mockImplementationOnce(
        () => new Promise(resolve => { resolveRedraw = resolve })
      )

      const { showDashboard, deactivate, reactivate } = mountInKeepAlive()
      await flushPromises()

      // Deactivate and let the data go stale
      await deactivate(9000)

      // Reactivation #1 — blocked awaiting the deferred chart draw
      await reactivate()

      // Quickly deactivate and reactivate — #2 completes and starts polling.
      // Raw reactivation: reactivate()'s trailing 0-advance would fire the
      // stale refresh before the mockClear below expects it.
      await deactivate()
      showDashboard.value = true
      await nextTick()
      await flushPromises()

      // Release #1 — its activation is stale, so it must not start another loop
      resolveRedraw()
      await flushPromises()

      state.fetchDashboardData.mockClear()

      // Immediate stale refresh + one regular cycle: exactly one loop's worth
      vi.advanceTimersByTime(0)
      await flushPromises()
      vi.advanceTimersByTime(9000)
      await flushPromises()
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

      const { deactivate, reactivate } = mountInKeepAlive()
      // startDashboard is awaiting fetchDashboardData — deactivate before it resolves
      await deactivate()

      // Resolve the initial fetch — startDashboard bails out via isActive check
      resolveFetch()
      await flushPromises()

      // Reactivate — onActivated resumes polling
      await reactivate()

      state.fetchDashboardData.mockClear()

      // Hide, go stale, return — the handler registered during
      // startDashboard must drive the immediate refresh
      hideTab()
      await returnToTab(9000)

      // Handler was registered before the await, so it should fire
      expect(state.fetchDashboardData).toHaveBeenCalled()
    })

    it('coincident activation and visibility signals do not double-fetch', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      const { showDashboard, deactivate } = mountInKeepAlive()
      await flushPromises()

      // Deactivate and let the data go stale
      await deactivate(9000)

      // Reactivate and fire visibilitychange in the same beat
      showDashboard.value = true
      await nextTick()
      await flushPromises()
      document.dispatchEvent(new Event('visibilitychange'))

      vi.advanceTimersByTime(0)
      await flushPromises()

      // Exactly one stale refresh on top of the mount fetch
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })
  })

  describe('visibility-based polling', () => {
    it('hiding the tab stops polling', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      mountDashboard()
      await flushPromises()
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      hideTab()

      vi.advanceTimersByTime(30000)
      await flushPromises()
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)
    })

    it('does not keep polling in the background when the tab hides mid-fetch', async () => {
      const state = baseState()
      let resolvePollFetch
      state.fetchDashboardData
        .mockResolvedValueOnce()  // startDashboard
        .mockImplementationOnce(() => new Promise(resolve => { resolvePollFetch = resolve }))  // poll tick
      useFetchBirdData.mockReturnValue(state)

      mountDashboard()
      await flushPromises()

      // First poll tick starts; its fetch is held open
      vi.advanceTimersByTime(9000)
      await flushPromises()

      // Tab hides while the poll fetch is in flight — stopPolling has no
      // timer left to clear, only the generation bump can stop the loop
      hideTab()

      resolvePollFetch()
      await flushPromises()

      vi.advanceTimersByTime(30000)
      await flushPromises()

      // Only 2 calls: startDashboard + the one poll tick, nothing in the background
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('refreshes immediately on return when the data went stale while hidden', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      mountDashboard()
      await flushPromises()

      hideTab()

      // Away long enough for the data to go stale
      await returnToTab(60000)

      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })

    it('skips the refetch on return when the data is still fresh', async () => {
      const state = baseState()
      useFetchBirdData.mockReturnValue(state)

      mountDashboard()
      await flushPromises()

      hideTab()

      // Back after only 2 seconds
      await returnToTab(2000)

      // No immediate refetch — the data is only 2s old
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(1)

      // Polling resumes on the original cadence: 9s after the last fetch
      vi.advanceTimersByTime(7000)
      await flushPromises()
      expect(state.fetchDashboardData).toHaveBeenCalledTimes(2)
    })
  })
})
