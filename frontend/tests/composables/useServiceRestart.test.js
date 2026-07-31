import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  useServiceRestart,
  captureRestartBaseline,
  isUpdateFailedError,
  requestRestart
} from '@/composables/useServiceRestart'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    info: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn()
  })
}))

// Identity fixtures: the wait engine compares probe responses against a
// baseline captured from the OLD server before the restart was triggered.
// updateStatus 'pending' mirrors the real update flow, where the dispatch
// response carries the server's verified post-reset read-back.
const BASELINE = {
  bootId: 'boot-old',
  commit: 'commit-old',
  version: '1.0.0',
  updateStatus: 'pending'
}

// Old server still up: same boot_id and commit as the baseline.
const OLD_SERVER = {
  data: { boot_id: 'boot-old', current_commit: 'commit-old', version: '1.0.0' }
}
// Restarted server: new process, same code.
const RESTARTED_SERVER = {
  data: { boot_id: 'boot-new', current_commit: 'commit-old', version: '1.0.0' }
}
// Updated server: new process, new commit.
const UPDATED_SERVER = {
  data: { boot_id: 'boot-new', current_commit: 'commit-new', version: '1.0.0' }
}

describe('useServiceRestart', () => {
  let originalLocation

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()

    // Mock window.location.reload
    originalLocation = window.location
    delete window.location
    window.location = { reload: vi.fn() }
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    window.location = originalLocation
  })

  describe('captureRestartBaseline', () => {
    it('maps identity fields from /system/version', async () => {
      mockApi.get.mockResolvedValueOnce({
        data: {
          boot_id: 'boot-1',
          current_commit: 'abc123',
          version: '0.9.0',
          runtime_mode: 'native',
          update_status: 'failed'
        }
      })

      const baseline = await captureRestartBaseline()

      expect(mockApi.get).toHaveBeenCalledWith('/system/version')
      expect(baseline).toEqual({
        bootId: 'boot-1',
        commit: 'abc123',
        version: '0.9.0',
        runtimeMode: 'native',
        updateStatus: 'failed'
      })
    })

    it('returns null when the request fails', async () => {
      mockApi.get.mockRejectedValueOnce(new Error('down'))
      expect(await captureRestartBaseline()).toBeNull()
    })

    it('returns null when the response has no data', async () => {
      mockApi.get.mockResolvedValueOnce(undefined)
      expect(await captureRestartBaseline()).toBeNull()
    })

    it("filters 'unknown' sentinels so they never pose as identity", async () => {
      // HA without BUILD_VERSION reports 'unknown' for version/commit; a
      // sentinel-only capture must collapse to a bootId-only baseline so
      // completion rides on the container swap, not an impossible
      // 'unknown' !== 'unknown' comparison.
      mockApi.get.mockResolvedValueOnce({
        data: {
          boot_id: 'boot-1',
          current_commit: 'unknown',
          version: 'unknown',
          runtime_mode: 'ha',
          update_status: null
        }
      })

      const baseline = await captureRestartBaseline()

      expect(baseline.bootId).toBe('boot-1')
      expect(baseline.commit).toBeUndefined()
      expect(baseline.version).toBeUndefined()
    })
  })

  describe('requestRestart', () => {
    it('returns the old server boot_id as a late baseline', async () => {
      mockApi.post.mockResolvedValueOnce({
        data: { status: 'restart_requested', boot_id: 'boot-old' }
      })

      expect(await requestRestart()).toEqual({ bootId: 'boot-old' })
      expect(mockApi.post).toHaveBeenCalledWith('/system/restart')
    })

    it('returns null when the response has no boot_id (older backend)', async () => {
      mockApi.post.mockResolvedValueOnce({ data: { status: 'restart_requested' } })
      expect(await requestRestart()).toBeNull()
    })

    it('returns null when the connection drops mid-restart', async () => {
      const err = new Error('Network Error')
      err.code = 'ERR_NETWORK'
      mockApi.post.mockRejectedValueOnce(err)

      expect(await requestRestart()).toBeNull()
    })

    it('rethrows errors that do not look like a restart in progress', async () => {
      mockApi.post.mockRejectedValueOnce(new Error('403 forbidden'))
      await expect(requestRestart()).rejects.toThrow('403 forbidden')
    })
  })

  it('initializes with correct default state', () => {
    const { isRestarting, restartMessage, restartError } = useServiceRestart()

    expect(isRestarting.value).toBe(false)
    expect(restartMessage.value).toBe('')
    expect(restartError.value).toBe('')
  })

  it('sets isRestarting to true when waiting', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { isRestarting, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0 // Skip post-connect delay in tests
    })

    expect(isRestarting.value).toBe(true)

    // Advance past initial delay and poll
    await vi.advanceTimersByTimeAsync(200)
    await promise

    expect(isRestarting.value).toBe(false)
  })

  it('probes /system/version and polls until the new instance responds', async () => {
    mockApi.get
      .mockRejectedValueOnce(new Error('Service down'))
      .mockRejectedValueOnce(new Error('Service down'))
      .mockResolvedValueOnce(RESTARTED_SERVER)

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0, // Skip post-connect delay in tests
      autoReload: false
    })

    // Initial delay
    await vi.advanceTimersByTimeAsync(100)
    // First failed poll
    await vi.advanceTimersByTimeAsync(100)
    // Second failed poll
    await vi.advanceTimersByTimeAsync(100)
    // Third successful poll
    await vi.advanceTimersByTimeAsync(100)

    const result = await promise
    expect(result).toBe(true)
    expect(mockApi.get).toHaveBeenCalledTimes(3)
    expect(mockApi.get).toHaveBeenCalledWith('/system/version')
  })

  it('REGRESSION (Pi Zero 2W): the old server answering is not treated as reconnected', async () => {
    // Slow hardware: the stack takes >initialDelay to go down, so early
    // probes hit the OLD server and succeed. The old logic reloaded into a
    // dead server; identity comparison must keep polling instead.
    mockApi.get
      .mockResolvedValueOnce(OLD_SERVER)
      .mockResolvedValueOnce(OLD_SERVER)
      .mockResolvedValueOnce(OLD_SERVER)
      .mockRejectedValueOnce(new Error('finally went down'))
      .mockResolvedValueOnce(RESTARTED_SERVER)

    const { waitForRestart } = useServiceRestart()
    let settled = false

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0,
      autoReload: true
    })
    promise.then(() => { settled = true })

    // Three successful probes against the old server: still waiting.
    await vi.advanceTimersByTimeAsync(400)
    expect(settled).toBe(false)
    expect(window.location.reload).not.toHaveBeenCalled()

    // Down, then the new instance appears: now it completes.
    await vi.advanceTimersByTimeAsync(300)
    await expect(promise).resolves.toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(window.location.reload).toHaveBeenCalled()
  })

  it('times out with RESTART_TIMEOUT if the old server never goes down', async () => {
    mockApi.get.mockResolvedValue(OLD_SERVER)

    const { restartError, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      maxWaitSeconds: 1,
      initialDelay: 100,
      pollInterval: 100,
      timeoutMessage: 'Took too long'
    })
    const outcome = promise.catch(error => error)

    await vi.advanceTimersByTimeAsync(2000)

    expect((await outcome).message).toBe('RESTART_TIMEOUT')
    expect(restartError.value).toBe('Took too long')
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  describe('update progress stages (progressUrl)', () => {
    let fetchMock

    beforeEach(() => {
      fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    const stageResponse = message => ({
      ok: true,
      json: () => Promise.resolve({ stage: 'pull', message })
    })

    it('replaces the generic banner subject with the fetched stage message', async () => {
      mockApi.get.mockRejectedValue(new Error('down for update'))
      fetchMock.mockResolvedValue(stageResponse('Downloading updated images (1 of 3)'))

      const { restartMessage, waitForRestart, reset } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 1000,
        message: 'System updating',
        progressUrl: '/update-progress'
      })

      // The stage poll is primed at wait start (before any timer fires), so
      // the very first banner tick can already render a real stage.
      expect(fetchMock).toHaveBeenCalledWith('/update-progress', { cache: 'no-store' })
      expect(restartMessage.value).toBe('System updating...')

      await vi.advanceTimersByTimeAsync(5000)
      expect(restartMessage.value).toBe('Downloading updated images (1 of 3)... (5s)')

      reset()
      await expect(promise).resolves.toBe(false)
    })

    it('keeps the generic subject when the endpoint is missing or the fetch fails', async () => {
      // Older stacks and the first update shipping this feature have no
      // /update-progress; the SPA 404-fallback serves index.html with 404.
      mockApi.get.mockRejectedValue(new Error('down for update'))
      fetchMock
        .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) })
        .mockRejectedValue(new TypeError('Failed to fetch'))

      const { restartMessage, waitForRestart, reset } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 1000,
        message: 'System updating',
        progressUrl: '/update-progress'
      })

      await vi.advanceTimersByTimeAsync(15000)
      expect(restartMessage.value).toBe('System updating... (15s)')

      reset()
      await expect(promise).resolves.toBe(false)
    })

    it('never fetches stages when no progressUrl is given', async () => {
      mockApi.get.mockRejectedValue(new Error('down for update'))

      const { waitForRestart, reset } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 1000,
        message: 'System updating'
      })

      await vi.advanceTimersByTimeAsync(15000)
      expect(fetchMock).not.toHaveBeenCalled()

      reset()
      await expect(promise).resolves.toBe(false)
    })
  })

  describe('expect: update', () => {
    it('completes only when the commit changes, not on mere reachability', async () => {
      mockApi.get
        .mockResolvedValueOnce(OLD_SERVER)
        .mockRejectedValueOnce(new Error('down for update'))
        .mockResolvedValueOnce(UPDATED_SERVER)

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      // Extra 10ms: the 0ms post-connect timer queued by the final probe
      // needs the clock to move past it before the promise can settle.
      await vi.advanceTimersByTimeAsync(310)
      const result = await promise
      expect(result).toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(3)
    })

    it('a restart of the same commit does not complete an update wait', async () => {
      // e.g. containers bounced but the build has not happened yet
      mockApi.get
        .mockResolvedValueOnce(RESTARTED_SERVER)
        .mockResolvedValueOnce(RESTARTED_SERVER)
        .mockResolvedValueOnce(UPDATED_SERVER)

      const { waitForRestart } = useServiceRestart()
      let settled = false

      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      promise.then(() => { settled = true })

      await vi.advanceTimersByTimeAsync(200)
      expect(settled).toBe(false)

      await vi.advanceTimersByTimeAsync(200)
      await expect(promise).resolves.toBe(true)
    })

    it('completes on a version change alone (HA add-on: no commit in payload)', async () => {
      mockApi.get.mockResolvedValueOnce({
        data: { boot_id: 'boot-new', version: '1.0.1' }
      })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(110)
      await expect(promise).resolves.toBe(true)
    })

    it('completes on update_status=success with a new boot_id (same-commit rebuild)', async () => {
      // install.sh found no code changes but rebuilt/restarted: commit and
      // version are unchanged, so the explicit success status is the signal.
      mockApi.get.mockResolvedValueOnce({
        data: {
          boot_id: 'boot-new',
          current_commit: 'commit-old',
          version: '1.0.0',
          update_status: 'success'
        }
      })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(110)
      await expect(promise).resolves.toBe(true)
    })

    it('rejects with UPDATE_FAILED when the old commit comes back with status=failed', async () => {
      mockApi.get
        .mockRejectedValueOnce(new Error('down for update'))
        .mockResolvedValueOnce({
          data: {
            boot_id: 'boot-new',
            current_commit: 'commit-old',
            version: '1.0.0',
            update_status: 'failed'
          }
        })

      const { isRestarting, restartError, waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: true,
        failureMessage: 'Update failed notice'
      })
      const outcome = promise.catch(error => error)

      await vi.advanceTimersByTimeAsync(200)

      const error = await outcome
      expect(error.message).toBe('UPDATE_FAILED')
      expect(isUpdateFailedError(error)).toBe(true)
      expect(restartError.value).toBe('Update failed notice')
      expect(isRestarting.value).toBe(false)
      await vi.advanceTimersByTimeAsync(2000)
      expect(window.location.reload).not.toHaveBeenCalled()
    })

    it('REGRESSION (P1): failed status is terminal even when the commit advanced', async () => {
      // version.json is refreshed before the post-build config steps, so
      // metadata can be ahead of what actually runs when a late step fails.
      mockApi.get.mockResolvedValueOnce({
        data: { ...UPDATED_SERVER.data, update_status: 'failed' }
      })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: true
      })
      const outcome = promise.catch(error => error)

      await vi.advanceTimersByTimeAsync(110)

      expect(isUpdateFailedError(await outcome)).toBe(true)
      await vi.advanceTimersByTimeAsync(2000)
      expect(window.location.reload).not.toHaveBeenCalled()
    })

    it('a failed status already present at baseline is not treated as this attempt failing', async () => {
      // Stale file survived the pending reset: ignore it until the status
      // demonstrably belongs to this run.
      mockApi.get
        .mockResolvedValueOnce({ data: { ...OLD_SERVER.data, update_status: 'failed' } })
        .mockRejectedValueOnce(new Error('down for update'))
        .mockResolvedValueOnce({ data: { ...UPDATED_SERVER.data, update_status: 'success' } })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { ...BASELINE, updateStatus: 'failed' },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(310)
      await expect(promise).resolves.toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(3)
    })

    it('a stale failed baseline still fails once a fresh failure is witnessed', async () => {
      // pending/in_progress observed mid-wait proves a later 'failed' came
      // from this attempt, stale baseline or not.
      mockApi.get
        .mockResolvedValueOnce({ data: { ...OLD_SERVER.data, update_status: 'in_progress' } })
        .mockResolvedValueOnce({
          data: {
            boot_id: 'boot-new',
            current_commit: 'commit-old',
            version: '1.0.0',
            update_status: 'failed'
          }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { ...BASELINE, updateStatus: 'failed' },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      const outcome = promise.catch(error => error)

      await vi.advanceTimersByTimeAsync(200)

      expect(isUpdateFailedError(await outcome)).toBe(true)
    })

    it('REGRESSION (retry): a fresh failure is terminal when the reset was verified, even if the failed-phase transition was missed', async () => {
      // Retry after an earlier failure: polling starts after shutdown so
      // the brief pending/in_progress window is never observed. The
      // verified 'pending' read-back in the baseline is the evidence that
      // any later 'failed' belongs to this attempt — terminal even though
      // version.json metadata advanced before the failure.
      mockApi.get
        .mockRejectedValueOnce(new Error('down for update'))
        .mockResolvedValueOnce({
          data: {
            boot_id: 'boot-new',
            current_commit: 'commit-new',
            version: '1.0.0',
            update_status: 'failed'
          }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE, // updateStatus: 'pending' — the verified read-back
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: true
      })
      const outcome = promise.catch(error => error)

      await vi.advanceTimersByTimeAsync(200)

      expect(isUpdateFailedError(await outcome)).toBe(true)
      await vi.advanceTimersByTimeAsync(2000)
      expect(window.location.reload).not.toHaveBeenCalled()
    })

    it('an unverified reset (null read-back) never attributes a stale failed to this attempt', async () => {
      // The best-effort reset could not be verified, so the stuck 'failed'
      // may predate this attempt: a successful retry (new commit, new
      // boot) must complete instead of false-failing.
      mockApi.get
        .mockRejectedValueOnce(new Error('down for update'))
        .mockResolvedValueOnce({
          data: { ...UPDATED_SERVER.data, update_status: 'failed' }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { ...BASELINE, updateStatus: null },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(210)
      await expect(promise).resolves.toBe(true)
    })

    it('a null-status probe is not witness evidence for failure attribution', async () => {
      // A reachable probe with no status field (file absent mid-rewrite, or
      // a transient read error) must not upgrade a later stale 'failed'
      // into a current-attempt failure — same rule as the baseline init.
      mockApi.get
        .mockResolvedValueOnce(OLD_SERVER) // reachable, no update_status
        .mockResolvedValueOnce({
          data: { ...UPDATED_SERVER.data, update_status: 'failed' }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { ...BASELINE, updateStatus: null },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(210)
      await expect(promise).resolves.toBe(true)
    })

    it('an unverified reset with a real failure degrades to a timeout, not a false failure', async () => {
      // Old commit back + failed status, but no evidence the status is
      // this attempt's: honest timeout instead of either false verdict.
      mockApi.get.mockResolvedValue({
        data: {
          boot_id: 'boot-new',
          current_commit: 'commit-old',
          version: '1.0.0',
          update_status: 'failed'
        }
      })

      const { restartError, waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { ...BASELINE, updateStatus: null },
        maxWaitSeconds: 1,
        initialDelay: 100,
        pollInterval: 100,
        timeoutMessage: 'Took too long'
      })
      const outcome = promise.catch(error => error)

      await vi.advanceTimersByTimeAsync(2000)

      const error = await outcome
      expect(error.message).toBe('RESTART_TIMEOUT')
      expect(isUpdateFailedError(error)).toBe(false)
      expect(restartError.value).toBe('Took too long')
    })

    it('completes a channel downgrade to a release that predates boot_id', async () => {
      // latest -> release can install code without the identity feature.
      // The baselined process demonstrably served a boot_id, so a response
      // without one is a different, older-code server: accept the commit
      // change.
      mockApi.get
        .mockResolvedValueOnce(OLD_SERVER)
        .mockRejectedValueOnce(new Error('down for downgrade'))
        .mockResolvedValueOnce({
          data: { current_commit: 'commit-release', version: '0.8.0' }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(310)
      await expect(promise).resolves.toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(3)
    })

    it('REGRESSION (P2a): a commit change served by the old process does not complete an update', async () => {
      // compose down is best-effort: the old API can survive it and serve a
      // version.json refreshed mid-update. Same boot_id => not done yet.
      mockApi.get
        .mockResolvedValueOnce({
          data: { boot_id: 'boot-old', current_commit: 'commit-new', version: '1.0.0' }
        })
        .mockResolvedValueOnce(UPDATED_SERVER)

      const { waitForRestart } = useServiceRestart()
      let settled = false

      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      promise.then(() => { settled = true })

      await vi.advanceTimersByTimeAsync(150)
      expect(settled).toBe(false)

      await vi.advanceTimersByTimeAsync(160)
      await expect(promise).resolves.toBe(true)
    })

    it('a bootId-only baseline (from a trigger response) completes via the success status', async () => {
      mockApi.get
        .mockResolvedValueOnce(OLD_SERVER)
        .mockResolvedValueOnce({
          data: { ...UPDATED_SERVER.data, update_status: 'success' }
        })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { bootId: 'boot-old' },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(210)
      await expect(promise).resolves.toBe(true)
    })

    it('a bootId-only baseline completes on a new process when no status system exists (HA)', async () => {
      // The HA add-on never writes update-status; a new container is the
      // only completion signal available for a trigger-response baseline.
      mockApi.get
        .mockResolvedValueOnce({ data: { boot_id: 'boot-old' } })
        .mockResolvedValueOnce({ data: { boot_id: 'boot-new' } })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        expect: 'update',
        baseline: { bootId: 'boot-old' },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(210)
      await expect(promise).resolves.toBe(true)
    })

    it("a probe reporting 'unknown' metadata cannot prove a code change", async () => {
      mockApi.get
        .mockResolvedValueOnce({
          data: { boot_id: 'boot-new', current_commit: 'unknown', version: 'unknown' }
        })
        .mockResolvedValueOnce(UPDATED_SERVER)

      const { waitForRestart } = useServiceRestart()
      let settled = false

      const promise = waitForRestart({
        expect: 'update',
        baseline: BASELINE,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      promise.then(() => { settled = true })

      await vi.advanceTimersByTimeAsync(150)
      expect(settled).toBe(false)

      await vi.advanceTimersByTimeAsync(160)
      await expect(promise).resolves.toBe(true)
    })

    it('a bootId-only baseline does not complete while the status shows in_progress', async () => {
      mockApi.get
        .mockResolvedValueOnce({
          data: { boot_id: 'boot-new', update_status: 'in_progress' }
        })
        .mockResolvedValueOnce({
          data: { boot_id: 'boot-new', update_status: 'success' }
        })

      const { waitForRestart } = useServiceRestart()
      let settled = false

      const promise = waitForRestart({
        expect: 'update',
        baseline: { bootId: 'boot-old' },
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      promise.then(() => { settled = true })

      await vi.advanceTimersByTimeAsync(150)
      expect(settled).toBe(false)

      await vi.advanceTimersByTimeAsync(160)
      await expect(promise).resolves.toBe(true)
    })
  })

  describe('fallback mode (no baseline)', () => {
    it('requires an observed outage before accepting a success', async () => {
      mockApi.get
        .mockResolvedValueOnce(OLD_SERVER)
        .mockResolvedValueOnce(OLD_SERVER)
        .mockRejectedValueOnce(new Error('down'))
        .mockResolvedValueOnce(OLD_SERVER)

      const { waitForRestart } = useServiceRestart()
      let settled = false

      const promise = waitForRestart({
        baseline: null,
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })
      promise.then(() => { settled = true })

      // Two successes with no outage seen yet: keep waiting.
      await vi.advanceTimersByTimeAsync(250)
      expect(settled).toBe(false)

      // Outage observed, then reachable again: down-then-up completes.
      await vi.advanceTimersByTimeAsync(250)
      await expect(promise).resolves.toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(4)
    })

    it('a baseline without the needed identity field falls back to down-then-up', async () => {
      // Old backend at capture time: no boot_id in the version payload.
      mockApi.get
        .mockResolvedValueOnce({ data: {} })
        .mockRejectedValueOnce(new Error('down'))
        .mockResolvedValueOnce({ data: {} })

      const { waitForRestart } = useServiceRestart()
      const promise = waitForRestart({
        baseline: { commit: 'commit-old' }, // no bootId
        initialDelay: 100,
        pollInterval: 100,
        postConnectDelay: 0,
        autoReload: false
      })

      await vi.advanceTimersByTimeAsync(310)
      await expect(promise).resolves.toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(3)
    })
  })

  it('reloads page when autoReload is true', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 100, // Small delay for testing
      autoReload: true
    })

    // Initial delay + poll
    await vi.advanceTimersByTimeAsync(200)
    // Post-connect delay
    await vi.advanceTimersByTimeAsync(100)
    // Reload delay (1 second)
    await vi.advanceTimersByTimeAsync(1000)

    await promise

    expect(window.location.reload).toHaveBeenCalled()
  })

  it('does not reload when autoReload is false', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0, // Skip post-connect delay in tests
      autoReload: false
    })

    await vi.advanceTimersByTimeAsync(200)
    await promise
    await vi.advanceTimersByTimeAsync(1000)

    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('waits postConnectDelay before completing', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { restartMessage, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 500,
      autoReload: false
    })

    // Initial delay + poll
    await vi.advanceTimersByTimeAsync(200)

    // Should show "waiting for services" message
    expect(restartMessage.value).toContain('Waiting')

    // After post-connect delay
    await vi.advanceTimersByTimeAsync(500)

    await promise

    // Should show ready message
    expect(restartMessage.value).toContain('ready')
  })

  it('updates elapsed progress in five-second increments during an update', async () => {
    let resolveProbe
    mockApi.get.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))

    const { restartMessage, waitForRestart } = useServiceRestart()
    const promise = waitForRestart({
      expect: 'update',
      baseline: BASELINE,
      initialDelay: 100,
      postConnectDelay: 0,
      autoReload: false,
      message: 'System updating'
    })

    await vi.advanceTimersByTimeAsync(100)
    await vi.advanceTimersByTimeAsync(4900)
    expect(restartMessage.value).toBe('System updating... (5s)')

    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('System updating... (10s)')

    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('System updating... (15s)')

    resolveProbe(UPDATED_SERVER)
    await vi.advanceTimersByTimeAsync(0)
    await promise

    expect(restartMessage.value).toBe('Services ready!')
    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('Services ready!')
  })

  it('omits the elapsed counter during a restart, keeping the phase messages', async () => {
    // A restart is short and its phases already advance; a ticking counter
    // only makes a normal wait read as slow.
    let resolveProbe
    mockApi.get.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))

    const { restartMessage, waitForRestart } = useServiceRestart()
    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      postConnectDelay: 0,
      autoReload: false,
      message: 'Restarting services'
    })

    await vi.advanceTimersByTimeAsync(100)
    await vi.advanceTimersByTimeAsync(15000)
    expect(restartMessage.value).toBe('Restarting services...')

    resolveProbe(RESTARTED_SERVER)
    await vi.advanceTimersByTimeAsync(0)
    await promise

    expect(restartMessage.value).toBe('Services ready!')
  })

  it('rejects with RESTART_TIMEOUT and shows the timeout message when the wait expires', async () => {
    mockApi.get.mockRejectedValue(new Error('Service down'))

    const { isRestarting, restartMessage, restartError, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      baseline: BASELINE,
      maxWaitSeconds: 1,
      initialDelay: 100,
      pollInterval: 100,
      timeoutMessage: 'Custom timeout notice'
    })
    const outcome = promise.catch(error => error)

    await vi.advanceTimersByTimeAsync(2000)

    expect((await outcome).message).toBe('RESTART_TIMEOUT')
    expect(restartError.value).toBe('Custom timeout notice')
    expect(restartMessage.value).toBe('')
    expect(isRestarting.value).toBe(false)

    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('')
  })

  it('resets state correctly', () => {
    const { isRestarting, restartMessage, restartError, reset } = useServiceRestart()

    isRestarting.value = true
    restartMessage.value = 'Test message'
    restartError.value = 'Test error'

    reset()

    expect(isRestarting.value).toBe(false)
    expect(restartMessage.value).toBe('')
    expect(restartError.value).toBe('')
  })

  it('starting a new wait cancels the previous one on the same instance', async () => {
    // Double-trigger safety: a superseded wait must resolve false and never
    // fire its reload; only the newest wait stays live.
    mockApi.get.mockRejectedValue(new Error('down'))

    const { waitForRestart } = useServiceRestart()
    const first = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(150)

    mockApi.get.mockResolvedValue(RESTARTED_SERVER)
    const second = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0,
      autoReload: false
    })

    await expect(first).resolves.toBe(false)
    await vi.advanceTimersByTimeAsync(110)
    await expect(second).resolves.toBe(true)
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('reset() cancels an in-flight wait: resolves false and stops all timers', async () => {
    mockApi.get.mockRejectedValue(new Error('Service down'))

    const { isRestarting, restartMessage, waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      autoReload: false,
      message: 'Restarting services'
    })

    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('Restarting services...')
    const callsBeforeReset = mockApi.get.mock.calls.length

    reset()

    await expect(promise).resolves.toBe(false)
    expect(isRestarting.value).toBe(false)
    expect(restartMessage.value).toBe('')

    // No more probes and no resurrected banner text after the reset.
    await vi.advanceTimersByTimeAsync(20000)
    expect(mockApi.get.mock.calls.length).toBe(callsBeforeReset)
    expect(restartMessage.value).toBe('')
  })

  it('a probe resolving after reset() cannot resurrect messages or reload', async () => {
    let resolveProbe
    mockApi.get.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))

    const { restartMessage, waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      postConnectDelay: 0,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(100) // probe now in flight
    reset()
    await expect(promise).resolves.toBe(false)

    resolveProbe(RESTARTED_SERVER)
    await vi.advanceTimersByTimeAsync(5000)

    expect(restartMessage.value).toBe('')
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('reset() during the post-connect wait cancels completion and auto-reload', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { restartMessage, waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      postConnectDelay: 10000,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(100) // probe succeeds; post-connect wait begins
    expect(restartMessage.value).toBe('Waiting for services to initialize...')

    reset()
    await expect(promise).resolves.toBe(false)

    await vi.advanceTimersByTimeAsync(20000)
    expect(restartMessage.value).toBe('')
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('reset() after a completed wait does not cancel the pending auto-reload', async () => {
    mockApi.get.mockResolvedValue(RESTARTED_SERVER)

    const { waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
      baseline: BASELINE,
      initialDelay: 100,
      pollInterval: 100,
      postConnectDelay: 0,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(100)
    // A zero-ms advance won't fire the already-queued 0ms post-connect
    // completion timer; nudge the clock forward to run it.
    await vi.advanceTimersByTimeAsync(1)
    await expect(promise).resolves.toBe(true)

    reset()
    await vi.advanceTimersByTimeAsync(1000)
    expect(window.location.reload).toHaveBeenCalled()
  })
})
