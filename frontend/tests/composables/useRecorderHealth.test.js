import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useRecorderHealth } from '@/composables/useRecorderHealth'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock useAuth
const mockIsAuthenticated = vi.hoisted(() => ({ value: true }))

vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated
  })
}))

// Mock localStorage
const mockStorage = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key) => mockStorage[key] ?? null),
  setItem: vi.fn((key, val) => { mockStorage[key] = val }),
  removeItem: vi.fn((key) => { delete mockStorage[key] })
})

// Reset module-level singleton between tests by re-importing
// We use a helper that sets status to a known "running" state (no warning shown)
async function resetRecorderState() {
  mockApi.get.mockResolvedValueOnce({ data: { state: 'running' } })
  const { checkStatus } = useRecorderHealth()
  await checkStatus()
}

describe('useRecorderHealth', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    mockIsAuthenticated.value = true

    await resetRecorderState()

    // Clear storage mock
    for (const key of Object.keys(mockStorage)) {
      delete mockStorage[key]
    }
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('checkStatus', () => {
    it('calls /recorder/status endpoint', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      const { checkStatus } = useRecorderHealth()

      await checkStatus()

      expect(mockApi.get).toHaveBeenCalledWith('/recorder/status')
    })

    it('does not call /stream/config', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'running' } })
      const { checkStatus } = useRecorderHealth()

      await checkStatus()

      expect(mockApi.get).not.toHaveBeenCalledWith('/stream/config')
    })

    it('updates status when response has state field', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'degraded', message: 'Source failed' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(true)
    })

    it('does not update status when response has no state field', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(false)
    })

    it('handles repeated calls with same state without error', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'degraded' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()
      await checkStatus()
      expect(showRecorderWarning.value).toBe(true)
    })

    it('silently handles errors without throwing', async () => {
      mockApi.get.mockRejectedValue(new Error('Network error'))
      const { checkStatus } = useRecorderHealth()

      // Should not throw
      await expect(checkStatus()).resolves.toBeUndefined()
    })
  })

  describe('showRecorderWarning', () => {
    it('shows warning when state is degraded and user is authenticated', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'degraded' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(true)
    })

    it('shows warning when state is stopped and user is authenticated', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'stopped' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(true)
    })

    it('does not show warning when state is running', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'running' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(false)
    })

    it('does not show warning when user is not authenticated', async () => {
      mockIsAuthenticated.value = false
      mockApi.get.mockResolvedValue({ data: { state: 'degraded' } })
      const { checkStatus, showRecorderWarning } = useRecorderHealth()

      await checkStatus()

      expect(showRecorderWarning.value).toBe(false)
    })
  })

  describe('dismissWarning', () => {
    it('hides warning after dismiss', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'degraded' } })
      const { checkStatus, showRecorderWarning, dismissWarning } = useRecorderHealth()

      await checkStatus()
      expect(showRecorderWarning.value).toBe(true)

      dismissWarning()
      expect(showRecorderWarning.value).toBe(false)
    })

    it('persists dismissal to localStorage', async () => {
      mockApi.get.mockResolvedValue({ data: { state: 'degraded' } })
      const { checkStatus, dismissWarning } = useRecorderHealth()

      await checkStatus()
      dismissWarning()

      expect(localStorage.setItem).toHaveBeenCalledWith(
        'birdnet_recorder_dismissed_until',
        expect.any(String)
      )
    })
  })
})
