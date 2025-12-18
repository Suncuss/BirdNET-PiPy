import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import Charts from '@/views/Charts.vue'
import { useFetchBirdData } from '@/composables/useFetchBirdData'

vi.mock('@/composables/useFetchBirdData')

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock Chart.js to avoid canvas use
vi.mock('chart.js/auto', () => {
  const ChartMock = function () { return { destroy: vi.fn(), update: vi.fn() } }
  ChartMock.register = vi.fn()
  ChartMock.getChart = vi.fn()
  return { default: ChartMock }
})

const mockChartsState = () => ({
  hourlyBirdActivityData: ref([]),
  detailedBirdActivityData: ref([]),
  detailedBirdActivityError: ref(null),
  hourlyBirdActivityError: ref('skip chart'),
  fetchChartsData: vi.fn()
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
})
