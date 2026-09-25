import { mount, enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ExportModal from '@/components/ExportModal.vue'
import { API_BASE } from '@/services/baseUrl'

const mockApi = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/services/api', () => ({ default: mockApi, SLOW_QUERY_TIMEOUT: 45000 }))

enableAutoUnmount(afterEach)

const makeJob = (overrides = {}) => ({
  id: 'job1', state: 'preparing', rows_done: 250, rows_total: 1000, bytes: 0,
  filename: 'birdnet_detections_all_2026-09-24.zip', start_date: null, end_date: null,
  error: null, expires_at: null, ...overrides
})

// Route GETs by URL so the tests don't depend on call order.
let currentJob
let counts
const routeGet = (url, config) => {
  if (url === '/detections/export/jobs/current') {
    return Promise.resolve({ data: { job: currentJob, today: '2030-01-02' } })
  }
  if (url === '/detections/export/count') {
    const count = counts[config.params.range]
    return count instanceof Error ? Promise.reject(count) : Promise.resolve({ data: { count: count ?? 0 } })
  }
  return Promise.resolve({ data: { job: currentJob } })
}

const mountModal = async () => {
  const wrapper = mount(ExportModal, {
    attachTo: document.body,
    global: { stubs: { AppDatePicker: true } }
  })
  await flushPromises()
  await vi.advanceTimersByTimeAsync(300) // count debounce
  await flushPromises()
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find(b => b.text() === text)

beforeEach(() => {
  vi.useFakeTimers()
  currentJob = null
  counts = { all: 1234, '7d': 0 }
  mockApi.get.mockReset().mockImplementation(routeGet)
  mockApi.post.mockReset()
  mockApi.delete.mockReset().mockResolvedValue({ data: {} })
})
afterEach(() => {
  vi.useRealTimers()
  document.body.style.overflow = ''
  document.body.innerHTML = ''
})

describe('ExportModal', () => {
  it('previews the row count and starts an export for the chosen range', async () => {
    const wrapper = await mountModal()
    expect(wrapper.get('[data-testid="export-count"]').text()).toBe('1,234 detections')

    mockApi.post.mockResolvedValueOnce({ data: { job: makeJob() } })
    await button(wrapper, 'Prepare export').trigger('click')
    await flushPromises()

    expect(mockApi.post).toHaveBeenCalledWith('/detections/export/jobs', { range: 'all' }, { timeout: 45000 })
    expect(wrapper.text()).toContain('250 of 1,000 detections')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('25')
  })

  it('keeps the form up with a disabled Starting... button while the start request runs', async () => {
    const wrapper = await mountModal()
    let resolveStart
    mockApi.post.mockReturnValueOnce(new Promise(resolve => { resolveStart = resolve }))
    await button(wrapper, 'Prepare export').trigger('click')
    await flushPromises()
    const starting = button(wrapper, 'Starting...')
    expect(starting.attributes('disabled')).toBeDefined()

    resolveStart({ data: { job: makeJob() } })
    await flushPromises()
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)
  })

  it('disables Prepare when the range is empty', async () => {
    const wrapper = await mountModal()
    await button(wrapper, 'Last 7 days').trigger('click')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.get('[data-testid="export-count"]').text()).toBe('No detections in this range.')
    expect(button(wrapper, 'Prepare export').attributes('disabled')).toBeDefined()
  })

  it('needs both dates for a custom range', async () => {
    const wrapper = await mountModal()
    await button(wrapper, 'Custom').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="export-count"]').text()).toBe('Pick a start and end date.')
    expect(button(wrapper, 'Prepare export').attributes('disabled')).toBeDefined()
    expect(mockApi.get).not.toHaveBeenCalledWith('/detections/export/count', expect.objectContaining({
      params: expect.objectContaining({ range: 'custom' })
    }))
  })

  it("bounds the custom range by the station's date, not the browser's", async () => {
    const wrapper = await mountModal()
    await button(wrapper, 'Custom').trigger('click')
    await flushPromises()
    const pickers = wrapper.findAllComponents({ name: 'AppDatePicker' })
    expect(pickers.map(p => p.props('max'))).toEqual(['2030-01-02', '2030-01-02'])
  })

  it('reports a failed count and still allows the export', async () => {
    counts = { all: new Error('timeout') }
    const wrapper = await mountModal()
    expect(wrapper.get('[data-testid="export-count"]').text()).toBe("Couldn't count the detections in this range.")
    expect(button(wrapper, 'Prepare export').attributes('disabled')).toBeUndefined()
  })

  it('resumes a ready export with a download link through the API base', async () => {
    currentJob = makeJob({ state: 'ready', rows_done: 1000, bytes: 4096 })
    const wrapper = await mountModal()
    const link = wrapper.get('a[download]')
    expect(link.attributes('href')).toBe(`${API_BASE}/detections/export/jobs/job1/file`)
    expect(link.attributes('download')).toBe('birdnet_detections_all_2026-09-24.zip')
    expect(wrapper.text()).toContain('1,000 detections')
  })

  it('cancelling a preparing export returns to the options', async () => {
    currentJob = makeJob()
    const wrapper = await mountModal()
    currentJob = null
    await button(wrapper, 'Cancel export').trigger('click')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(mockApi.delete).toHaveBeenCalledWith('/detections/export/jobs/job1')
    expect(button(wrapper, 'Prepare export')).toBeTruthy()
  })

  it('closing leaves a preparing export running', async () => {
    currentJob = makeJob()
    const wrapper = await mountModal()
    await wrapper.get('button[title="Close"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(mockApi.delete).not.toHaveBeenCalled()
  })

  it('shows a failed export with a way to start over', async () => {
    currentJob = makeJob({ state: 'failed', error: 'The export failed. Check the logs for details.' })
    const wrapper = await mountModal()
    expect(wrapper.text()).toContain('The export failed.')
    currentJob = null
    await button(wrapper, 'Start over').trigger('click')
    await flushPromises()
    expect(mockApi.delete).toHaveBeenCalledWith('/detections/export/jobs/job1')
  })
})
