import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { UPDATE_DISMISSED_UNTIL_KEY } from '@/utils/storageKeys'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn()
}))

const mockLongApi = vi.hoisted(() => ({
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi,
  createLongRequest: () => mockLongApi
}))

// Mock useAuth - default: auth disabled (isAuthenticated = true)
const mockIsAuthenticated = vi.hoisted(() => ({ value: true }))

vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated
  })
}))

// Mock useServiceRestart since useSystemUpdate now delegates to it
const mockServiceRestart = vi.hoisted(() => {
  const isRestarting = { value: false }
  const restartMessage = { value: '' }
  const restartError = { value: '' }
  return {
    isRestarting,
    restartMessage,
    restartError,
    waitForRestart: vi.fn().mockResolvedValue(true),
    reset: vi.fn(() => {
      isRestarting.value = false
      restartMessage.value = ''
      restartError.value = ''
    })
  }
})

const mockCaptureBaseline = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useServiceRestart', () => ({
  isRestartTimeoutError: (error) => error?.message === 'RESTART_TIMEOUT',
  isUpdateFailedError: (error) => error?.message === 'UPDATE_FAILED',
  // Real (trivial, pure) implementation: the composable under test calls it
  identityValue: (value) => (value && value !== 'unknown' ? value : undefined),
  captureRestartBaseline: mockCaptureBaseline,
  useServiceRestart: () => mockServiceRestart
}))

describe('useSystemUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.window.confirm = vi.fn()
    global.window.location = { reload: vi.fn() }
    vi.useFakeTimers()

    // Reset auth mock to default (auth disabled = isAuthenticated true)
    mockIsAuthenticated.value = true

    // Baseline capture is best-effort; default to "unavailable"
    mockCaptureBaseline.mockReset()
    mockCaptureBaseline.mockResolvedValue(null)

    // Reset singleton state between tests
    const { versionInfo, updateInfo, updateAvailable, checking, updating, statusMessage, statusType } = useSystemUpdate()
    versionInfo.value = null
    updateInfo.value = null
    updateAvailable.value = false
    checking.value = false
    updating.value = false
    statusMessage.value = null
    statusType.value = null
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads version info successfully', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        current_commit: '1a081f5',
        current_commit_date: '2025-11-28T08:49:00Z',
        current_branch: 'develop',
        remote_url: 'git@github.com:Suncuss/Birdnet-PiPy-archive.git'
      }
    })

    const { loadVersionInfo, versionInfo } = useSystemUpdate()
    await loadVersionInfo()

    expect(versionInfo.value.current_commit).toBe('1a081f5')
    expect(versionInfo.value.current_branch).toBe('develop')
  })

  it('handles version info load failure', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('Server error'))

    const { loadVersionInfo, statusMessage, statusType } = useSystemUpdate()

    await expect(loadVersionInfo()).rejects.toThrow()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Failed to load version information')
  })

  it('checks for updates and sets updateAvailable when updates exist', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        current_commit: '1a081f5',
        remote_commit: '2b192g6',
        commits_behind: 5,
        current_branch: 'develop',
        target_branch: 'main',
        preview_commits: [
          { hash: '2b192g6', message: 'feat: new feature', date: '2025-11-29T10:00:00Z' }
        ]
      }
    })

    const { checkForUpdates, updateAvailable, updateInfo, statusMessage } = useSystemUpdate()
    await checkForUpdates()

    expect(updateAvailable.value).toBe(true)
    expect(updateInfo.value.commits_behind).toBe(5)
    // No status message when update is available - the UI box is sufficient
    expect(statusMessage.value).toBeNull()
  })

  it('checks for updates and shows up to date when no updates', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: false,
        commits_behind: 0,
        preview_commits: []
      }
    })

    const { checkForUpdates, updateAvailable, statusMessage } = useSystemUpdate()
    await checkForUpdates()

    expect(updateAvailable.value).toBe(false)
    expect(statusMessage.value).toContain('up to date')
  })

  it('handles check for updates failure', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('Network error'))

    const { checkForUpdates, statusType, statusMessage } = useSystemUpdate()

    await expect(checkForUpdates()).rejects.toThrow()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Failed to check for updates')
  })

  it('triggers update with user confirmation', async () => {
    window.confirm.mockReturnValue(true)
    mockLongApi.post.mockResolvedValueOnce({
      data: {
        status: 'update_triggered',
        message: 'Update started',
        estimated_downtime: '2-5 minutes',
        commits_to_apply: 3
      }
    })

    const { triggerUpdate, updating, statusMessage } = useSystemUpdate()
    await triggerUpdate()

    expect(window.confirm).toHaveBeenCalled()
    expect(statusMessage.value).toContain('Services restarting')
  })

  it('cancels update when user declines confirmation', async () => {
    window.confirm.mockReturnValue(false)

    const { triggerUpdate, updating } = useSystemUpdate()
    await triggerUpdate()

    expect(window.confirm).toHaveBeenCalled()
    expect(updating.value).toBe(false)
    expect(mockLongApi.post).not.toHaveBeenCalled()
  })

  it('handles update trigger when already up to date', async () => {
    window.confirm.mockReturnValue(true)
    mockLongApi.post.mockResolvedValueOnce({
      data: {
        status: 'no_update_needed',
        message: 'System is already up to date'
      }
    })

    const { triggerUpdate, updating, statusMessage } = useSystemUpdate()
    await triggerUpdate()

    expect(updating.value).toBe(false)
    expect(statusMessage.value).toContain('already up to date')
  })

  it('handles update trigger failure', async () => {
    window.confirm.mockReturnValue(true)
    mockLongApi.post.mockRejectedValueOnce(new Error('Update failed'))

    const { triggerUpdate, updating, statusType, statusMessage } = useSystemUpdate()

    await expect(triggerUpdate()).rejects.toThrow()

    expect(updating.value).toBe(false)
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Update failed')
  })

  it('delegates to useServiceRestart for monitoring reconnection', async () => {
    window.confirm.mockReturnValue(true)

    mockLongApi.post.mockResolvedValueOnce({
      data: {
        status: 'update_triggered',
        message: 'Update started'
      }
    })

    const { triggerUpdate, restartMessage, isRestarting } = useSystemUpdate()

    // Verify that restartMessage and isRestarting are exposed from useServiceRestart
    expect(restartMessage).toBeDefined()
    expect(isRestarting).toBeDefined()

    await triggerUpdate()

    // The update should trigger and delegate to serviceRestart.waitForRestart
    expect(mockLongApi.post).toHaveBeenCalledWith('/system/update')
  })

  it('auto-clears success/info messages after 10 seconds', async () => {
    // Simulate a success message
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: false,
        commits_behind: 0,
        preview_commits: []
      }
    })

    const composable = useSystemUpdate()
    await composable.checkForUpdates()

    expect(composable.statusMessage.value).toBeTruthy()
    expect(composable.statusType.value).toBe('success')

    // Fast-forward 10 seconds
    await vi.advanceTimersByTimeAsync(10000)
    await vi.runAllTimersAsync()

    expect(composable.statusMessage.value).toBeNull()
    expect(composable.statusType.value).toBeNull()
  })

  it('does not auto-clear error messages', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('Network error'))

    const { checkForUpdates, statusMessage, statusType } = useSystemUpdate()

    await expect(checkForUpdates()).rejects.toThrow()

    expect(statusMessage.value).toBeTruthy()
    expect(statusType.value).toBe('error')

    // Fast-forward 10 seconds
    await vi.advanceTimersByTimeAsync(10000)
    await vi.runAllTimersAsync()

    // Error message should still be there
    expect(statusMessage.value).toBeTruthy()
    expect(statusType.value).toBe('error')
  })

  it('showUpdateIndicator is false when no update available', () => {
    const { showUpdateIndicator, updateAvailable } = useSystemUpdate()
    updateAvailable.value = false
    expect(showUpdateIndicator.value).toBe(false)
  })

  it('showUpdateIndicator is true when update available and not dismissed', async () => {
    // Clear any stored dismissal
    localStorage.removeItem(UPDATE_DISMISSED_UNTIL_KEY)

    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        remote_commit: 'abc123',
        channel: 'release',
        commits_behind: 3
      }
    })

    const { checkForUpdates, showUpdateIndicator } = useSystemUpdate()
    await checkForUpdates()

    expect(showUpdateIndicator.value).toBe(true)
  })

  it('dismissUpdate hides the update indicator', async () => {
    // Clear any stored dismissal
    localStorage.removeItem(UPDATE_DISMISSED_UNTIL_KEY)

    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        remote_commit: 'abc123',
        channel: 'release',
        commits_behind: 3
      }
    })

    const { checkForUpdates, showUpdateIndicator, dismissUpdate } = useSystemUpdate()
    await checkForUpdates()

    expect(showUpdateIndicator.value).toBe(true)

    dismissUpdate()

    expect(showUpdateIndicator.value).toBe(false)
  })

  it('checkForUpdates with silent option does not set status message', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: false,
        commits_behind: 0
      }
    })

    const { checkForUpdates, statusMessage } = useSystemUpdate()
    await checkForUpdates({ silent: true })

    expect(statusMessage.value).toBeNull()
  })

  it('checkForUpdates with force option adds query param', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: false,
        commits_behind: 0
      }
    })

    const { checkForUpdates } = useSystemUpdate()
    await checkForUpdates({ force: true })

    expect(mockApi.get).toHaveBeenCalledWith('/system/update-check?force=true')
  })

  it('showUpdateIndicator is false when auth enabled and user not logged in', async () => {
    localStorage.removeItem(UPDATE_DISMISSED_UNTIL_KEY)
    mockIsAuthenticated.value = false

    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        remote_commit: 'abc123',
        channel: 'release',
        commits_behind: 3
      }
    })

    const { checkForUpdates, showUpdateIndicator } = useSystemUpdate()
    await checkForUpdates()

    expect(showUpdateIndicator.value).toBe(false)
  })

  it('showUpdateIndicator is true when auth enabled and user is logged in', async () => {
    localStorage.removeItem(UPDATE_DISMISSED_UNTIL_KEY)
    mockIsAuthenticated.value = true
    // Advance past any dismiss duration from previous tests (7 days + buffer)
    vi.advanceTimersByTime(8 * 24 * 60 * 60 * 1000)

    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        remote_commit: 'abc123',
        channel: 'release',
        commits_behind: 3
      }
    })

    const { checkForUpdates, showUpdateIndicator } = useSystemUpdate()
    await checkForUpdates()

    expect(showUpdateIndicator.value).toBe(true)
  })

  it('checkForUpdates handles HA response shape', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: {
        update_available: true,
        runtime_mode: 'ha',
        current_version: '0.6.3',
        latest_version: '0.6.4',
        update_note: null
      }
    })

    const { checkForUpdates, updateAvailable, updateInfo } = useSystemUpdate()
    await checkForUpdates()

    expect(updateAvailable.value).toBe(true)
    expect(updateInfo.value.runtime_mode).toBe('ha')
    expect(updateInfo.value.current_version).toBe('0.6.3')
    expect(updateInfo.value.latest_version).toBe('0.6.4')
  })

  it('native update passes update expectation and baseline to waitForRestart', async () => {
    window.confirm.mockReturnValue(true)
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', commit: 'c1', version: '0.9.0', runtimeMode: 'native'
    })
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })

    const { triggerUpdate } = useSystemUpdate()
    await triggerUpdate()

    expect(mockCaptureBaseline).toHaveBeenCalled()
    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        expect: 'update',
        baseline: expect.objectContaining({ bootId: 'b1', commit: 'c1' }),
        autoReload: true
      })
    )
  })

  it('native update points the wait at the host update-progress stage file', async () => {
    window.confirm.mockReturnValue(true)
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', commit: 'c1', version: '0.9.0', runtimeMode: 'native'
    })
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })

    const { triggerUpdate } = useSystemUpdate()
    await triggerUpdate()

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({ progressUrl: '/update-progress' })
    )
  })

  it('HA update never passes a progressUrl (Supervisor owns that update)', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha' }
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'boot-from-dispatch' }
    })

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledTimes(1)
    const options = mockServiceRestart.waitForRestart.mock.calls[0][0]
    expect(options.progressUrl).toBeUndefined()
  })

  it('falls back to the trigger response boot_id when baseline capture failed', async () => {
    window.confirm.mockReturnValue(true)
    // mockCaptureBaseline default resolves null (capture failed)
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'boot-from-post' }
    })

    const { triggerUpdate } = useSystemUpdate()
    await triggerUpdate()

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        expect: 'update',
        baseline: { bootId: 'boot-from-post' }
      })
    )
  })

  it('merges cached version identity with the trigger response identity', async () => {
    window.confirm.mockReturnValue(true)
    // mockCaptureBaseline default resolves null (capture failed); the
    // versionInfo cache still knows the running commit/version.
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { current_commit: 'cached-commit', version: '0.9.0' }
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'boot-from-post', update_status: 'pending' }
    })

    await triggerUpdate()

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        baseline: {
          commit: 'cached-commit',
          version: '0.9.0',
          bootId: 'boot-from-post',
          updateStatus: 'pending'
        }
      })
    )
  })

  it('refreshes the baseline update status from the trigger response read-back', async () => {
    window.confirm.mockReturnValue(true)
    // Stale 'failed' at capture time; the server read back 'pending' after
    // resetting it, so a later 'failed' is attributable to this attempt.
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', commit: 'c1', version: 'v1',
      runtimeMode: 'native', updateStatus: 'failed'
    })
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'b1', update_status: 'pending' }
    })

    const { triggerUpdate } = useSystemUpdate()
    await triggerUpdate()

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        baseline: expect.objectContaining({
          bootId: 'b1',
          commit: 'c1',
          updateStatus: 'pending'
        })
      })
    )
  })

  it('treats a wait timeout as still-in-progress info, not failure', async () => {
    window.confirm.mockReturnValue(true)
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })
    mockServiceRestart.waitForRestart.mockRejectedValueOnce(new Error('RESTART_TIMEOUT'))

    const { triggerUpdate, statusType, statusMessage, updating } = useSystemUpdate()
    await triggerUpdate()

    expect(updating.value).toBe(false)
    expect(statusType.value).toBe('info')
    expect(statusMessage.value).toContain('longer than expected')
  })

  it('reports a failed update distinctly when the wait rejects with UPDATE_FAILED', async () => {
    window.confirm.mockReturnValue(true)
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })
    mockServiceRestart.waitForRestart.mockRejectedValueOnce(new Error('UPDATE_FAILED'))

    const { triggerUpdate, statusType, statusMessage, updating } = useSystemUpdate()
    await triggerUpdate()

    expect(updating.value).toBe(false)
    expect(statusType.value).toBe('error')
    expect(statusMessage.value.toLowerCase()).toContain('update failed')
  })

  it('triggerUpdate (HA mode) dispatches POST and delegates to the shared wait engine', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', version: '0.6.4-dev21', runtimeMode: 'ha'
    })
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })

    await triggerUpdate(true)

    expect(mockLongApi.post).toHaveBeenCalledWith('/system/update')
    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        expect: 'update',
        baseline: expect.objectContaining({ bootId: 'b1' }),
        autoReload: true,
        message: expect.stringContaining('Home Assistant')
      })
    )
  })

  it('triggerUpdate (HA mode) tolerates dispatch connection loss and keeps waiting', async () => {
    const { triggerUpdate, versionInfo, statusType } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockRejectedValueOnce(new Error('connection lost'))

    await triggerUpdate(true)
    // Flush the rejected POST's .catch microtask
    await vi.advanceTimersByTimeAsync(0)

    expect(mockServiceRestart.reset).not.toHaveBeenCalled()
    expect(statusType.value).toBeNull()
  })

  it('triggerUpdate (HA mode) surfaces backend dispatch error and cancels the wait', async () => {
    const { triggerUpdate, versionInfo, statusType, statusMessage, updating } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    // Captured baseline: the wait starts immediately, so the dispatch error
    // must cancel it mid-flight.
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', version: '0.6.4-dev21', runtimeMode: 'ha'
    })
    const backendErr = new Error('Request failed with status code 502')
    backendErr.response = { status: 502, data: { error: 'Could not find update entity for addon' } }
    mockLongApi.post.mockRejectedValueOnce(backendErr)

    // The wait stays pending until reset() cancels it, mirroring the real
    // engine where reset() resolves the in-flight waitForRestart with false.
    let resolveWait
    mockServiceRestart.waitForRestart.mockImplementationOnce(
      () => new Promise((resolve) => { resolveWait = resolve })
    )
    mockServiceRestart.reset.mockImplementationOnce(() => { resolveWait?.(false) })

    await triggerUpdate(true)

    expect(mockServiceRestart.reset).toHaveBeenCalled()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Could not find update entity')
    expect(updating.value).toBe(false)
  })

  it('triggerUpdate (HA mode) dispatch error without any identity never starts a wait', async () => {
    const { triggerUpdate, versionInfo, statusType, statusMessage, updating } = useSystemUpdate()
    // No version/commit in the cache either: the dispatch-response race is
    // the only identity source, so a dispatch failure must return early.
    versionInfo.value = { runtime_mode: 'ha' }
    // mockCaptureBaseline default resolves null (capture failed)
    const backendErr = new Error('Request failed with status code 502')
    backendErr.response = { status: 502, data: { error: 'Could not find update entity for addon' } }
    mockLongApi.post.mockRejectedValueOnce(backendErr)

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).not.toHaveBeenCalled()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Could not find update entity')
    expect(updating.value).toBe(false)
  })

  it('triggerUpdate (HA mode) sentinel-only cached identity falls back to the dispatch race', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    // 'unknown' placeholders can't prove advancement; they must not
    // suppress the dispatch boot_id fallback.
    versionInfo.value = {
      runtime_mode: 'ha', version: 'unknown', current_commit: 'unknown'
    }
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'boot-from-dispatch' }
    })

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        baseline: { bootId: 'boot-from-dispatch' }
      })
    )
  })

  it('triggerUpdate (HA mode) uses the dispatch response boot_id when no other identity exists', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    // Neither a captured baseline nor cached version identity: only the
    // dispatch response can supply a baseline.
    versionInfo.value = { runtime_mode: 'ha' }
    mockLongApi.post.mockResolvedValueOnce({
      data: { status: 'update_triggered', boot_id: 'boot-from-dispatch' }
    })

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        expect: 'update',
        baseline: { bootId: 'boot-from-dispatch' }
      })
    )
  })

  it('triggerUpdate (HA mode) uses cached version identity immediately when capture failed', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = {
      runtime_mode: 'ha', version: '0.6.4-dev21', current_commit: 'ha-commit'
    }
    // mockCaptureBaseline default resolves null (capture failed).
    // Dispatch never settles: the monitor must start anyway — a fast
    // container swap can finish before any dispatch response arrives, and
    // version identity also refuses to call a failed update (old image
    // back, new boot, no status file) done.
    mockLongApi.post.mockImplementationOnce(() => new Promise(() => {}))

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        expect: 'update',
        baseline: expect.objectContaining({
          version: '0.6.4-dev21',
          commit: 'ha-commit'
        })
      })
    )
  })

  it('triggerUpdate (HA mode) grafts the dispatch boot_id onto a cache-derived baseline', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = {
      runtime_mode: 'ha', version: '0.6.4-dev21', current_commit: 'ha-commit'
    }
    // Capture fails (default null): the cache supplies commit/version but no
    // process identity, which waives the wait engine's process proof — a
    // stale cache could then look "advanced" on the first probe. The
    // dispatch responder is the old process; its boot_id must be grafted
    // onto the in-flight baseline when the response arrives.
    let resolveDispatch
    mockLongApi.post.mockImplementationOnce(
      () => new Promise(resolve => { resolveDispatch = resolve })
    )

    await triggerUpdate(true)

    const { baseline } = mockServiceRestart.waitForRestart.mock.calls[0][0]
    expect(baseline).toMatchObject({ version: '0.6.4-dev21', commit: 'ha-commit' })
    expect(baseline.bootId).toBeUndefined()

    resolveDispatch({ data: { status: 'update_triggered', boot_id: 'old-boot' } })
    await vi.advanceTimersByTimeAsync(0)

    expect(baseline.bootId).toBe('old-boot')
  })

  it('triggerUpdate (HA mode) with a captured baseline starts the wait without awaiting dispatch', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockCaptureBaseline.mockResolvedValueOnce({
      bootId: 'b1', version: '0.6.4-dev21', runtimeMode: 'ha'
    })
    // Dispatch never settles (Supervisor kills the connection): must not block
    mockLongApi.post.mockImplementationOnce(() => new Promise(() => {}))

    await triggerUpdate(true)

    expect(mockServiceRestart.waitForRestart).toHaveBeenCalledWith(
      expect.objectContaining({
        baseline: expect.objectContaining({ bootId: 'b1' })
      })
    )
  })

  it('triggerUpdate throws on connection loss in native mode', async () => {
    const { triggerUpdate, versionInfo, statusType } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'native' }

    const networkError = new Error('Network Error')
    networkError.code = 'ERR_NETWORK'
    mockLongApi.post.mockRejectedValueOnce(networkError)

    await expect(triggerUpdate(true)).rejects.toThrow()
    expect(statusType.value).toBe('error')
  })
})
