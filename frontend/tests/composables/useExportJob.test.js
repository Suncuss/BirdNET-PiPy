import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { useExportJob } from '@/composables/useExportJob'
import { API_BASE } from '@/services/baseUrl'

const mockApi = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('@/services/api', () => ({ default: mockApi, SLOW_QUERY_TIMEOUT: 45000 }))

const httpError = (status, data = {}) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } })

const makeJob = (overrides = {}) => ({
  id: 'job1', state: 'preparing', rows_done: 0, rows_total: 100, bytes: 0,
  filename: 'birdnet_detections_all_2026-09-24.zip', start_date: null, end_date: null,
  error: null, expires_at: null, ...overrides
})

const mountComposable = () => {
  let exportJob
  const wrapper = mount({ setup() { exportJob = useExportJob(); return () => null } })
  return { wrapper, exportJob }
}

beforeEach(() => {
  vi.useFakeTimers()
  mockApi.get.mockReset()
  mockApi.post.mockReset()
  mockApi.delete.mockReset().mockResolvedValue({ data: {} })
})
afterEach(() => { vi.useRealTimers() })

describe('useExportJob', () => {
  it('resumes a preparing job and polls until it is ready', async () => {
    mockApi.get
      .mockResolvedValueOnce({ data: { job: makeJob({ rows_done: 10 }) } }) // current
      .mockResolvedValueOnce({ data: { job: makeJob({ rows_done: 60 }) } })
      .mockResolvedValueOnce({ data: { job: makeJob({ state: 'ready', rows_done: 100, bytes: 2048 }) } })
    const { exportJob } = mountComposable()

    await exportJob.load()
    expect(mockApi.get).toHaveBeenCalledWith('/detections/export/jobs/current')
    expect(exportJob.percent.value).toBe(10)
    expect(exportJob.downloadUrl.value).toBeNull()

    await vi.advanceTimersByTimeAsync(1000)
    expect(mockApi.get).toHaveBeenLastCalledWith('/detections/export/jobs/job1')
    expect(exportJob.percent.value).toBe(60)

    await vi.advanceTimersByTimeAsync(1000)
    expect(exportJob.job.value.state).toBe('ready')
    expect(exportJob.downloadUrl.value).toBe(`${API_BASE}/detections/export/jobs/job1/file`)

    await vi.advanceTimersByTimeAsync(5000)
    expect(mockApi.get).toHaveBeenCalledTimes(3) // polling stopped once ready
  })

  it('does not poll when there is no job', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { job: null } })
    const { exportJob } = mountComposable()
    await exportJob.load()
    await vi.advanceTimersByTimeAsync(5000)
    expect(mockApi.get).toHaveBeenCalledTimes(1)
    expect(exportJob.job.value).toBeNull()
  })

  it('starts a job with the chosen options', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { job: makeJob() } })
    const { exportJob } = mountComposable()
    await exportJob.start({ range: '7d' })
    expect(mockApi.post).toHaveBeenCalledWith('/detections/export/jobs', { range: '7d' }, { timeout: 45000 })
    expect(exportJob.job.value.id).toBe('job1')
  })

  it('adopts the already-running job on 409', async () => {
    mockApi.post.mockRejectedValueOnce(httpError(409, { error: 'busy', job: makeJob({ id: 'other' }) }))
    const { exportJob } = mountComposable()
    await exportJob.start({ range: 'all' })
    expect(exportJob.job.value.id).toBe('other')
    expect(exportJob.error.value).toBe('')
  })

  it('shows the server reason when a start is refused', async () => {
    mockApi.post.mockRejectedValueOnce(httpError(507, { error: 'Not enough free space' }))
    const { exportJob } = mountComposable()
    await exportJob.start({ range: 'all' })
    expect(exportJob.job.value).toBeNull()
    expect(exportJob.error.value).toBe('Not enough free space')
  })

  it('drops an expired job when a poll 404s', async () => {
    mockApi.get
      .mockResolvedValueOnce({ data: { job: makeJob() } })
      .mockRejectedValueOnce(httpError(404))
    const { exportJob } = mountComposable()
    await exportJob.load()
    await vi.advanceTimersByTimeAsync(1000)
    expect(exportJob.job.value).toBeNull()
    expect(exportJob.error.value).toMatch(/expired/)
  })

  it('keeps polling through a transient error', async () => {
    mockApi.get
      .mockResolvedValueOnce({ data: { job: makeJob() } })
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce({ data: { job: makeJob({ rows_done: 50 }) } })
    const { exportJob } = mountComposable()
    await exportJob.load()
    await vi.advanceTimersByTimeAsync(2000)
    expect(exportJob.percent.value).toBe(50)
  })

  it('discard deletes the job and stops polling', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { job: makeJob() } })
    const { exportJob } = mountComposable()
    await exportJob.load()
    await exportJob.discard()
    expect(mockApi.delete).toHaveBeenCalledWith('/detections/export/jobs/job1')
    expect(exportJob.job.value).toBeNull()
    await vi.advanceTimersByTimeAsync(5000)
    expect(mockApi.get).toHaveBeenCalledTimes(1)
  })

  it('does not resume polling when a poll in flight at unmount returns', async () => {
    let resolvePoll
    mockApi.get
      .mockResolvedValueOnce({ data: { job: makeJob(), today: '2026-09-25' } })
      .mockReturnValueOnce(new Promise(resolve => { resolvePoll = resolve }))
    const { wrapper, exportJob } = mountComposable()
    await exportJob.load()
    expect(exportJob.today.value).toBe('2026-09-25')
    await vi.advanceTimersByTimeAsync(1000) // poll now in flight
    wrapper.unmount()
    resolvePoll({ data: { job: makeJob({ rows_done: 50 }) } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    expect(mockApi.get).toHaveBeenCalledTimes(2)
  })

  it('stops polling on unmount without cancelling the job', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { job: makeJob() } })
    const { wrapper, exportJob } = mountComposable()
    await exportJob.load()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(mockApi.get).toHaveBeenCalledTimes(1)
    expect(mockApi.delete).not.toHaveBeenCalled()
  })
})
