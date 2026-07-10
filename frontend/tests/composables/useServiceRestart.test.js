import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useServiceRestart } from '@/composables/useServiceRestart'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
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

  it('initializes with correct default state', () => {
    const { isRestarting, restartMessage, restartError } = useServiceRestart()

    expect(isRestarting.value).toBe(false)
    expect(restartMessage.value).toBe('')
    expect(restartError.value).toBe('')
  })

  it('sets isRestarting to true when waiting', async () => {
    mockApi.get.mockResolvedValue({ data: {} })

    const { isRestarting, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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

  it('polls until service responds', async () => {
    mockApi.get
      .mockRejectedValueOnce(new Error('Service down'))
      .mockRejectedValueOnce(new Error('Service down'))
      .mockResolvedValueOnce({ data: {} })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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
  })

  it('reloads page when autoReload is true', async () => {
    mockApi.get.mockResolvedValue({ data: {} })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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
    mockApi.get.mockResolvedValue({ data: {} })

    const { waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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
    mockApi.get.mockResolvedValue({ data: {} })

    const { restartMessage, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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

  it('updates elapsed progress in five-second increments while a probe is pending', async () => {
    let resolveProbe
    mockApi.get.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))

    const { restartMessage, waitForRestart } = useServiceRestart()
    const promise = waitForRestart({
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

    resolveProbe({ data: {} })
    await vi.advanceTimersByTimeAsync(0)
    await promise

    expect(restartMessage.value).toBe('Services ready!')
    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('Services ready!')
  })

  it('rejects with RESTART_TIMEOUT and shows the timeout message when the wait expires', async () => {
    mockApi.get.mockRejectedValue(new Error('Service down'))

    const { isRestarting, restartMessage, restartError, waitForRestart } = useServiceRestart()

    const promise = waitForRestart({
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

  it('reset() cancels an in-flight wait: resolves false and stops all timers', async () => {
    mockApi.get.mockRejectedValue(new Error('Service down'))

    const { isRestarting, restartMessage, waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
      initialDelay: 100,
      pollInterval: 100,
      autoReload: false,
      message: 'Restarting services'
    })

    await vi.advanceTimersByTimeAsync(5000)
    expect(restartMessage.value).toBe('Restarting services... (5s)')
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
      initialDelay: 100,
      postConnectDelay: 0,
      autoReload: true
    })

    await vi.advanceTimersByTimeAsync(100) // probe now in flight
    reset()
    await expect(promise).resolves.toBe(false)

    resolveProbe({ data: {} })
    await vi.advanceTimersByTimeAsync(5000)

    expect(restartMessage.value).toBe('')
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('reset() during the post-connect wait cancels completion and auto-reload', async () => {
    mockApi.get.mockResolvedValue({ data: {} })

    const { restartMessage, waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
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
    mockApi.get.mockResolvedValue({ data: {} })

    const { waitForRestart, reset } = useServiceRestart()
    const promise = waitForRestart({
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
