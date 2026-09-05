import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import Charts from '@/views/Charts.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'
import { deferred } from '../helpers/deferred'

vi.mock('@/composables/useFetchBirdData')

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock Chart.js to avoid canvas use. Hoisted as a vi.fn so tests can assert
// that a chart was actually constructed (vs. createTrendsChart bailing out
// at its `!trendsChart.value` early return).
const ChartCtor = vi.hoisted(() => {
  const fn = vi.fn(() => ({ destroy: vi.fn(), update: vi.fn() }))
  fn.register = vi.fn()
  fn.getChart = vi.fn()
  return fn
})
vi.mock('chart.js/auto', () => ({ default: ChartCtor }))

// useBirdCharts (used by the real composable mounted here, not mocked)
// calls useRouter() to deep-link heatmap-cell clicks to the Table view.
const mockRouter = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({
  useRouter: () => mockRouter
}))

// Mock AppDatePicker component to avoid PrimeVue dependency in tests
vi.mock('@/components/AppDatePicker.vue', () => ({
  default: {
    name: 'AppDatePicker',
    template: '<input type="date" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)" />',
    props: ['modelValue', 'disabled', 'max'],
    emits: ['update:modelValue', 'change']
  }
}))

const mockChartsState = () => ({
  hourlyBirdActivityData: ref([]),
  detailedBirdActivityData: ref([]),
  detailedBirdActivityError: ref(null),
  hourlyBirdActivityError: ref('skip chart'),
  fetchChartsData: vi.fn(),
  trendsData: ref({ labels: [], data: [] }),
  trendsError: ref(null),
  fetchTrendsData: vi.fn().mockResolvedValue({ labels: [], data: [] })
})

const mountCharts = () => mount(Charts, {
  global: {
    stubs: {
      'font-awesome-icon': true,
      'router-link': true
    }
  }
})

describe('Charts', () => {
  let today

  beforeEach(() => {
    const now = new Date()
    vi.useFakeTimers().setSystemTime(now)
    today = now.toLocaleDateString('en-CA')
    useFetchBirdData.mockReturnValue(mockChartsState())

    mockApi.get.mockResolvedValue({ data: [] })
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('initializes with today as selected date', async () => {
    const wrapper = mountCharts()
    await flushPromises()

    expect(wrapper.vm.selectedDate).toBe(today)
  })

  it('calls fetchChartsData when date changes', async () => {
    const state = mockChartsState()
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountCharts()
    await flushPromises()

    wrapper.vm.selectedDate = '2024-01-10'
    await wrapper.vm.onDateChange()

    expect(state.fetchChartsData).toHaveBeenCalledWith('2024-01-10')
  })

  it('disables forward navigation when on today', async () => {
    const wrapper = mountCharts()
    await flushPromises()

    expect(wrapper.vm.canGoForward).toBe(false)
  })

  it('goes to previous and next day adjusting flags', async () => {
    const state = mockChartsState()
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountCharts()
    await flushPromises()

    wrapper.vm.previousDay()
    expect(wrapper.vm.selectedDate).not.toBe(today)
    expect(wrapper.vm.canGoForward).toBe(true)

    wrapper.vm.goToToday()
    expect(state.fetchChartsData).toHaveBeenCalled()
    expect(wrapper.vm.selectedDate).toBeTypeOf('string')
  })

  it('treats empty detailed data as empty dataset', async () => {
    const wrapper = mountCharts()
    await flushPromises()

    expect(wrapper.vm.isDataEmpty).toBe(true)
  })

  it('shows error message when detailedBirdActivityError exists', async () => {
    const state = mockChartsState()
    state.detailedBirdActivityError.value = 'Failed to load'
    useFetchBirdData.mockReturnValue(state)

    const wrapper = mountCharts()
    await flushPromises()

    expect(wrapper.text()).toContain('Failed to load')
  })

  it('searches and selects species by localized display name', async () => {
    mockApi.get.mockResolvedValue({
      data: [
        {
          common_name: 'American Robin',
          display_common_name: 'Amsel',
          scientific_name: 'Turdus migratorius'
        }
      ]
    })

    const wrapper = mountCharts()
    await flushPromises()

    // Typing filters by the localized display name (matchesBirdQuery searches
    // display_common_name too), so "Ams" reaches "Amsel".
    const input = wrapper.find('input[role="combobox"]')
    await input.setValue('Ams')

    // Scope to the combobox's own list — the trends range picker on the same
    // page also renders li[role=option].
    const comboRoot = input.element.parentElement
    const options = wrapper.findAll('li[role="option"]').filter(o => comboRoot.contains(o.element))
    expect(options).toHaveLength(1)
    expect(options[0].text()).toContain('Amsel')

    await options[0].trigger('mousedown')
    await flushPromises()

    // The picked object is the model; the field shows its display label.
    expect(wrapper.vm.selectedSpecies.common_name).toBe('American Robin')
    expect(input.element.value).toBe('Amsel')
  })

  describe('Detection Trends', () => {
    it('initializes trends with 30 day default', async () => {
      const wrapper = mountCharts()
      await flushPromises()

      expect(wrapper.vm.trendsTimeRange).toBe('30')
    })

    it('initializes trends end date to today', async () => {
      const wrapper = mountCharts()
      await flushPromises()

      expect(wrapper.vm.trendsEndDate).toBe(today)
    })

    it('disables forward navigation when end date is today', async () => {
      const wrapper = mountCharts()
      await flushPromises()

      expect(wrapper.vm.canGoForwardTrends).toBe(false)
    })

    it('enables forward navigation after navigating back', async () => {
      const state = mockChartsState()
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      wrapper.vm.previousTrendsPeriod()
      await flushPromises()

      expect(wrapper.vm.canGoForwardTrends).toBe(true)
    })

    it('calls fetchTrendsData when time range changes', async () => {
      const state = mockChartsState()
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      // Reset the mock to check for new calls
      state.fetchTrendsData.mockClear()

      wrapper.vm.trendsTimeRange = '7'
      await wrapper.vm.onTrendsTimeRangeChange()
      await flushPromises()

      expect(state.fetchTrendsData).toHaveBeenCalled()
    })

    it('shows error message when trendsChartError exists', async () => {
      const wrapper = mountCharts()
      await flushPromises()

      wrapper.vm.trendsChartError = 'Failed to load trends'
      await flushPromises()

      expect(wrapper.text()).toContain('Failed to load trends')
    })

    it('goToTodayTrends resets end date to today', async () => {
      const state = mockChartsState()
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      // Navigate back first
      wrapper.vm.previousTrendsPeriod()
      await flushPromises()

      expect(wrapper.vm.trendsEndDate).not.toBe(today)

      // Reset to today
      wrapper.vm.goToTodayTrends()
      await flushPromises()

      expect(wrapper.vm.trendsEndDate).toBe(today)
    })
  })

  describe('Loading and error states', () => {
    it('shows fetching indicator for activity overview while initial fetch is pending', async () => {
      const state = mockChartsState()
      const pending = deferred()
      state.fetchChartsData = vi.fn(() => pending.promise)
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      // Critical: an in-flight fetch must NOT masquerade as an empty day.
      expect(wrapper.text()).toContain('Fetching the latest data')
      expect(wrapper.text()).not.toContain('No bird activity recorded')

      pending.resolve()
      await flushPromises()

      // After the fetch settles with empty data, empty state takes over.
      expect(wrapper.text()).toContain('No bird activity recorded')
    })

    it('shows fetching indicator for trends chart while initial fetch is pending', async () => {
      const state = mockChartsState()
      const pending = deferred()
      state.fetchTrendsData = vi.fn(() => pending.promise)
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      // Activity overview already settled (its mock resolves immediately);
      // trends fetch is still pending, so trends must show the fetching
      // indicator rather than the empty-period text.
      expect(wrapper.text()).toContain('No bird activity recorded')
      expect(wrapper.text()).toContain('Fetching the latest data')
      expect(wrapper.text()).not.toContain('No detection data available')

      pending.resolve({ labels: [], data: [] })
      await flushPromises()

      expect(wrapper.text()).toContain('No detection data available')
    })

    it('surfaces an error when fetchTrendsData returns null (swallowed network error)', async () => {
      const state = mockChartsState()
      // The real composable catches network errors and returns null.
      state.fetchTrendsData = vi.fn().mockResolvedValue(null)
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()

      // Critical: a fetch failure must NOT masquerade as an empty period.
      expect(wrapper.text()).toContain('Failed to load detection trends')
      expect(wrapper.text()).not.toContain('No detection data available')
    })

    it('draws the trends chart on initial load (canvas must be in DOM before createTrendsChart runs)', async () => {
      const state = mockChartsState()
      state.fetchTrendsData = vi.fn().mockResolvedValue({
        labels: ['2026-05-19', '2026-05-20'],
        data: [10, 20]
      })
      useFetchBirdData.mockReturnValue(state)

      ChartCtor.mockClear()
      mountCharts()
      await flushPromises()

      // Regression: trendsLoadedOnce must flip BEFORE the nextTick that swaps
      // the loading placeholder for the <canvas>, otherwise createTrendsChart's
      // `!trendsChart.value` early return fires and Chart.js is never invoked —
      // user sees a blank canvas until they trigger a refetch.
      expect(ChartCtor).toHaveBeenCalled()
    })

    it('clears the trends error after a successful refetch', async () => {
      const state = mockChartsState()
      state.fetchTrendsData = vi.fn().mockResolvedValue(null)
      useFetchBirdData.mockReturnValue(state)

      const wrapper = mountCharts()
      await flushPromises()
      expect(wrapper.text()).toContain('Failed to load detection trends')

      // Restore a successful response, then navigate to trigger a refetch.
      state.fetchTrendsData.mockResolvedValue({
        labels: ['2026-05-19', '2026-05-20'],
        data: [10, 20]
      })
      wrapper.vm.previousTrendsPeriod()
      await flushPromises()

      expect(wrapper.text()).not.toContain('Failed to load detection trends')
      expect(wrapper.text()).not.toContain('No detection data available')
    })
  })
})
