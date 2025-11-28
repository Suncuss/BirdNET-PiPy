import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useSystemUpdate } from '@/composables/useSystemUpdate'

describe('useSystemUpdate', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
    global.window.confirm = vi.fn()
    global.window.location = { reload: vi.fn() }
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads version info successfully', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        current_commit: '1a081f5',
        current_commit_message: 'fix: improve spectrogram',
        current_commit_date: '2025-11-28T08:49:00Z',
        current_branch: 'develop',
        remote_url: 'git@github.com:Suncuss/Birdnet-PiPy-archive.git'
      })
    })

    const { loadVersionInfo, versionInfo } = useSystemUpdate()
    await loadVersionInfo()

    expect(versionInfo.value.current_commit).toBe('1a081f5')
    expect(versionInfo.value.current_branch).toBe('develop')
    expect(versionInfo.value.current_commit_message).toBe('fix: improve spectrogram')
  })

  it('handles version info load failure', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500
    })

    const { loadVersionInfo, statusMessage, statusType } = useSystemUpdate()

    await expect(loadVersionInfo()).rejects.toThrow()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Failed to load version information')
  })

  it('checks for updates and sets updateAvailable when updates exist', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        update_available: true,
        current_commit: '1a081f5',
        remote_commit: '2b192g6',
        commits_behind: 5,
        current_branch: 'develop',
        target_branch: 'main',
        preview_commits: [
          { hash: '2b192g6', message: 'feat: new feature', date: '2025-11-29T10:00:00Z' }
        ]
      })
    })

    const { checkForUpdates, updateAvailable, updateInfo, statusMessage } = useSystemUpdate()
    await checkForUpdates()

    expect(updateAvailable.value).toBe(true)
    expect(updateInfo.value.commits_behind).toBe(5)
    expect(statusMessage.value).toContain('Update available')
  })

  it('checks for updates and shows up to date when no updates', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        update_available: false,
        commits_behind: 0,
        preview_commits: []
      })
    })

    const { checkForUpdates, updateAvailable, statusMessage } = useSystemUpdate()
    await checkForUpdates()

    expect(updateAvailable.value).toBe(false)
    expect(statusMessage.value).toContain('up to date')
  })

  it('handles check for updates failure', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500
    })

    const { checkForUpdates, statusType, statusMessage } = useSystemUpdate()

    await expect(checkForUpdates()).rejects.toThrow()
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Failed to check for updates')
  })

  it('triggers update with user confirmation', async () => {
    window.confirm.mockReturnValue(true)
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'update_triggered',
        message: 'Update started',
        estimated_downtime: '2-5 minutes',
        commits_to_apply: 3
      })
    })

    const { triggerUpdate, updating, statusMessage } = useSystemUpdate()
    triggerUpdate()

    expect(window.confirm).toHaveBeenCalled()
    await vi.runAllTimersAsync()

    // Wait for the fetch to complete
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(updating.value).toBe(true)
  })

  it('cancels update when user declines confirmation', async () => {
    window.confirm.mockReturnValue(false)

    const { triggerUpdate, updating } = useSystemUpdate()
    await triggerUpdate()

    expect(window.confirm).toHaveBeenCalled()
    expect(updating.value).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('handles update trigger when already up to date', async () => {
    window.confirm.mockReturnValue(true)
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'no_update_needed',
        message: 'System is already up to date'
      })
    })

    const { triggerUpdate, updating, statusMessage } = useSystemUpdate()
    await triggerUpdate()

    expect(updating.value).toBe(false)
    expect(statusMessage.value).toContain('already up to date')
  })

  it('handles update trigger failure', async () => {
    window.confirm.mockReturnValue(true)
    fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({
        error: 'Update failed'
      })
    })

    const { triggerUpdate, updating, statusType, statusMessage } = useSystemUpdate()

    await expect(triggerUpdate()).rejects.toThrow()

    expect(updating.value).toBe(false)
    expect(statusType.value).toBe('error')
    expect(statusMessage.value).toContain('Update failed')
  })

  it('monitors reconnection and reloads page on success', async () => {
    window.confirm.mockReturnValue(true)

    // First fetch: trigger update
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'update_triggered',
        message: 'Update started'
      })
    })

    const { triggerUpdate } = useSystemUpdate()
    triggerUpdate()

    // Wait for initial update trigger
    await vi.runAllTimersAsync()
    await new Promise(resolve => setTimeout(resolve, 0))

    // Second fetch: reconnection check succeeds
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        current_commit: 'new123'
      })
    })

    // Fast-forward past the initial 10 second delay
    await vi.advanceTimersByTimeAsync(10000)
    await vi.runAllTimersAsync()
    await new Promise(resolve => setTimeout(resolve, 0))

    // Fast-forward past the reload delay (2 seconds)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.runAllTimersAsync()

    expect(window.location.reload).toHaveBeenCalled()
  })

  it('shows timeout error if service does not reconnect', async () => {
    window.confirm.mockReturnValue(true)

    // Trigger update
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'update_triggered'
      })
    })

    const { triggerUpdate, statusMessage, updating } = useSystemUpdate()
    triggerUpdate()

    await vi.runAllTimersAsync()
    await new Promise(resolve => setTimeout(resolve, 0))

    // All reconnection attempts fail
    for (let i = 0; i < 60; i++) {
      fetch.mockRejectedValueOnce(new Error('Service down'))
      await vi.advanceTimersByTimeAsync(5000)
      await vi.runAllTimersAsync()
      await new Promise(resolve => setTimeout(resolve, 0))
    }

    expect(updating.value).toBe(false)
    expect(statusMessage.value).toContain('Update may have failed')
  })

  it('auto-clears success/info messages after 10 seconds', async () => {
    const { setStatus, statusMessage, statusType } = useSystemUpdate()

    // Manually call setStatus (normally called internally)
    const composable = useSystemUpdate()

    // Simulate a success message
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        update_available: false,
        commits_behind: 0,
        preview_commits: []
      })
    })

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
    fetch.mockResolvedValueOnce({
      ok: false
    })

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
