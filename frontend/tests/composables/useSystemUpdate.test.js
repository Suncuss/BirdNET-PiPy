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

// Mock useServiceRestart since useSystemUpdate now delegates to it
vi.mock('@/composables/useServiceRestart', () => ({
  useServiceRestart: () => ({
    isRestarting: { value: false },
    restartMessage: { value: '' },
    restartError: { value: '' },
    waitForRestart: vi.fn().mockResolvedValue(true),
    reset: vi.fn()
  })
}))

describe('useSystemUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.window.confirm = vi.fn()
    global.window.location = { reload: vi.fn() }
    vi.useFakeTimers()
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
})
