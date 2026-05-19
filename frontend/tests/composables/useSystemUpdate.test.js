import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useSystemUpdate } from '@/composables/useSystemUpdate'

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

vi.mock('@/composables/useServiceRestart', () => ({
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
    localStorage.removeItem('birdnet_update_dismissed_until')

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
    localStorage.removeItem('birdnet_update_dismissed_until')

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
    localStorage.removeItem('birdnet_update_dismissed_until')
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
    localStorage.removeItem('birdnet_update_dismissed_until')
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

  it('triggerUpdate (HA mode) sets banner and dispatches POST', async () => {
    const { triggerUpdate, versionInfo, isRestarting, restartMessage } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockResolvedValueOnce({ data: { status: 'update_triggered' } })

    await triggerUpdate(true)

    expect(mockLongApi.post).toHaveBeenCalledWith('/system/update')
    expect(isRestarting.value).toBe(true)
    expect(restartMessage.value).toContain('Home Assistant')
  })

  it('triggerUpdate (HA mode) suppresses dispatch errors and keeps polling', async () => {
    const { triggerUpdate, versionInfo, isRestarting, statusType } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockRejectedValueOnce(new Error('connection lost'))
    mockApi.get.mockResolvedValue({ data: { version: '0.6.4-dev21' } })

    await triggerUpdate(true)
    // Flush the rejected POST's .catch microtask
    await vi.advanceTimersByTimeAsync(0)

    expect(isRestarting.value).toBe(true)
    expect(statusType.value).toBeNull()
  })

  it('triggerUpdate (HA mode) surfaces backend error response and stops polling', async () => {
    const { triggerUpdate, versionInfo, isRestarting, statusType, statusMessage, updating } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    const backendErr = new Error('Request failed with status code 502')
    backendErr.response = { status: 502, data: { error: 'Could not find update entity for addon' } }
    mockLongApi.post.mockRejectedValueOnce(backendErr)

    await triggerUpdate(true)
    await vi.advanceTimersByTimeAsync(0)

    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Could not find update entity')
    expect(isRestarting.value).toBe(false)
    expect(updating.value).toBe(false)

    // Confirm polling was stopped — no GET on /system/version even after interval elapses
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockApi.get).not.toHaveBeenCalled()
  })

  it('triggerUpdate (HA mode) reloads when version changes', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockResolvedValueOnce({ data: {} })
    mockApi.get
      .mockResolvedValueOnce({ data: { version: '0.6.4-dev21' } })
      .mockResolvedValueOnce({ data: { version: '0.6.4-dev22' } })

    await triggerUpdate(true)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockApi.get).toHaveBeenCalledWith('/system/version')
    expect(window.location.reload).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(window.location.reload).toHaveBeenCalled()
  })

  it('triggerUpdate (HA mode) keeps polling through GET errors', async () => {
    const { triggerUpdate, versionInfo } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockResolvedValueOnce({ data: {} })
    mockApi.get
      .mockRejectedValueOnce(new Error('proxy down'))
      .mockResolvedValueOnce({ data: { version: '0.6.4-dev22' } })

    await triggerUpdate(true)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockApi.get).toHaveBeenCalledTimes(1)
    expect(window.location.reload).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(window.location.reload).toHaveBeenCalled()
  })

  it('triggerUpdate (HA mode) shows fallback after timeout, no reload', async () => {
    const { triggerUpdate, versionInfo, isRestarting, statusType, statusMessage, updating } = useSystemUpdate()
    versionInfo.value = { runtime_mode: 'ha', version: '0.6.4-dev21' }
    mockLongApi.post.mockResolvedValueOnce({ data: {} })
    mockApi.get.mockResolvedValue({ data: { version: '0.6.4-dev21' } })

    await triggerUpdate(true)

    await vi.advanceTimersByTimeAsync(10 * 60 * 1000 + 1000)

    expect(window.location.reload).not.toHaveBeenCalled()
    expect(isRestarting.value).toBe(false)
    expect(updating.value).toBe(false)
    expect(statusType.value).toBe('info')
    expect(statusMessage.value).toContain('longer than expected')
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
