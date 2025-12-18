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
