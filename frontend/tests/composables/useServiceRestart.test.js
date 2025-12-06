import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useServiceRestart } from '@/composables/useServiceRestart'

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    info: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn()
  })
}))

describe('useServiceRestart', () => {
  let fetchMock
  let originalLocation

  beforeEach(() => {
    fetchMock = vi.fn()
    global.fetch = fetchMock
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

  it('initializes with correct default state', () => {
    const { isRestarting, restartMessage, restartError } = useServiceRestart()

    expect(isRestarting.value).toBe(false)
    expect(restartMessage.value).toBe('')
    expect(restartError.value).toBe('')
  })

  it('sets isRestarting to true when waiting', async () => {
    fetchMock.mockResolvedValue({ ok: true })

    const { isRestarting, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({ initialDelay: 100, pollInterval: 100 })

    expect(isRestarting.value).toBe(true)

    // Advance past initial delay and poll
    await vi.advanceTimersByTimeAsync(200)
    await promise

    expect(isRestarting.value).toBe(false)
  })

  it('polls until service responds', async () => {
    fetchMock
      .mockRejectedValueOnce(new Error('Service down'))
      .mockRejectedValueOnce(new Error('Service down'))
      .mockResolvedValueOnce({ ok: true })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      initialDelay: 100,
      pollInterval: 100,
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
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('reloads page when autoReload is true', async () => {
    fetchMock.mockResolvedValue({ ok: true })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      initialDelay: 100,
      pollInterval: 100,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(200)
    await promise

    // Advance for reload delay
    await vi.advanceTimersByTimeAsync(1000)

    expect(window.location.reload).toHaveBeenCalled()
  })

  it('does not reload when autoReload is false', async () => {
    fetchMock.mockResolvedValue({ ok: true })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
      initialDelay: 100,
      pollInterval: 100,
      autoReload: false
    })

    await vi.advanceTimersByTimeAsync(200)
    await promise
    await vi.advanceTimersByTimeAsync(1000)

    expect(window.location.reload).not.toHaveBeenCalled()
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
})
