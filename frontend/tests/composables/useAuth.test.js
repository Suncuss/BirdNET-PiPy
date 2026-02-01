/**
 * Tests for useAuth composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAuth } from '@/composables/useAuth'

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  })
}))

describe('useAuth', () => {
  let fetchMock

  beforeEach(() => {
    fetchMock = vi.fn()
    global.fetch = fetchMock
    // Reset singleton state before each test
    const auth = useAuth()
    auth.resetState()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('initialization', () => {
    it('returns auth object with all expected properties', () => {
      const auth = useAuth()

      expect(auth).toHaveProperty('authStatus')
      expect(auth).toHaveProperty('loading')
      expect(auth).toHaveProperty('error')
      expect(auth).toHaveProperty('needsLogin')
      expect(auth).toHaveProperty('isAuthenticated')
      expect(auth).toHaveProperty('checkAuthStatus')
      expect(auth).toHaveProperty('login')
      expect(auth).toHaveProperty('logout')
      expect(auth).toHaveProperty('setup')
      expect(auth).toHaveProperty('toggleAuth')
      expect(auth).toHaveProperty('changePassword')
      expect(auth).toHaveProperty('clearError')
    })

    it('initializes with default auth status', () => {
      const auth = useAuth()

      expect(auth.authStatus.value).toEqual({
        authEnabled: false,
        setupComplete: false,
        authenticated: false
      })
    })

    it('initializes loading as false', () => {
      const auth = useAuth()
      expect(auth.loading.value).toBe(false)
    })

    it('initializes error as empty string', () => {
      const auth = useAuth()
      expect(auth.error.value).toBe('')
    })
  })

  describe('computed properties', () => {
    it('needsLogin is true when auth enabled and not authenticated', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: true,
        setupComplete: true,
        authenticated: false
      }
      expect(auth.needsLogin.value).toBe(true)
    })

    it('needsLogin is false when authenticated', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: true,
        setupComplete: true,
        authenticated: true
      }
      expect(auth.needsLogin.value).toBe(false)
    })

    it('needsLogin is false when auth disabled', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: false,
        setupComplete: false,
        authenticated: false
      }
      expect(auth.needsLogin.value).toBe(false)
    })

    it('isAuthenticated is true when auth disabled', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: false,
        setupComplete: false,
        authenticated: false
      }
      expect(auth.isAuthenticated.value).toBe(true)
    })

    it('isAuthenticated is true when authenticated', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: true,
        setupComplete: true,
        authenticated: true
      }
      expect(auth.isAuthenticated.value).toBe(true)
    })

    it('isAuthenticated is false when auth enabled but not authenticated', () => {
      const auth = useAuth()
      auth.authStatus.value = {
        authEnabled: true,
        setupComplete: true,
        authenticated: false
      }
      expect(auth.isAuthenticated.value).toBe(false)
    })
  })

  describe('checkAuthStatus', () => {
    it('fetches and updates auth status', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          auth_enabled: true,
          setup_complete: true,
          authenticated: false
        })
      })

      const auth = useAuth()
      await auth.checkAuthStatus()

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/status')
      expect(auth.authStatus.value).toEqual({
        authEnabled: true,
        setupComplete: true,
        authenticated: false
      })
    })

    it('handles fetch error gracefully', async () => {
      fetchMock.mockRejectedValueOnce(new Error('Network error'))

      const auth = useAuth()
      await auth.checkAuthStatus()

      // Should not throw, and status should remain default
      expect(auth.authStatus.value.authEnabled).toBe(false)
    })
  })

  describe('login', () => {
    it('sets authenticated to true on successful login', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Login successful' })
      })

      const auth = useAuth()
      const result = await auth.login('testpassword')

      expect(result).toBe(true)
      expect(auth.authStatus.value.authenticated).toBe(true)
      expect(auth.error.value).toBe('')
    })

    it('sends password in request body', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Login successful' })
      })

      const auth = useAuth()
      await auth.login('mypassword123')

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: 'mypassword123' })
      })
    })

    it('sets error on failed login', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Invalid password' })
      })

      const auth = useAuth()
      const result = await auth.login('wrongpassword')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Invalid password')
      expect(auth.authStatus.value.authenticated).toBe(false)
    })

    it('sets loading state during login', async () => {
      let resolvePromise
      fetchMock.mockReturnValueOnce(new Promise(resolve => {
        resolvePromise = resolve
      }))

      const auth = useAuth()
      const loginPromise = auth.login('password')

      expect(auth.loading.value).toBe(true)

      resolvePromise({
        ok: true,
        json: () => Promise.resolve({ message: 'ok' })
      })
      await loginPromise

      expect(auth.loading.value).toBe(false)
    })

    it('handles network error', async () => {
      fetchMock.mockRejectedValueOnce(new Error('Network error'))

      const auth = useAuth()
      const result = await auth.login('password')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Connection error')
    })
  })

  describe('logout', () => {
    it('clears authenticated status', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({})
      })

      const auth = useAuth()
      auth.authStatus.value.authenticated = true

      await auth.logout()

      expect(auth.authStatus.value.authenticated).toBe(false)
    })

    it('sends POST request to logout endpoint', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({})
      })

      const auth = useAuth()
      await auth.logout()

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/logout', { method: 'POST' })
    })
  })

  describe('setup', () => {
    it('sets setupComplete and authenticated on success', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Password set' })
      })

      const auth = useAuth()
      const result = await auth.setup('newpassword')

      expect(result).toBe(true)
      expect(auth.authStatus.value.setupComplete).toBe(true)
      expect(auth.authStatus.value.authenticated).toBe(true)
    })

    it('sends password to setup endpoint', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Password set' })
      })

      const auth = useAuth()
      await auth.setup('mynewpassword')

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: 'mynewpassword' })
      })
    })

    it('sets error on setup failure', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Password too short' })
      })

      const auth = useAuth()
      const result = await auth.setup('abc')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Password too short')
    })
  })

  describe('toggleAuth', () => {
    it('updates authEnabled on success', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ auth_enabled: true })
      })

      const auth = useAuth()
      const result = await auth.toggleAuth(true)

      expect(result).toBe(true)
      expect(auth.authStatus.value.authEnabled).toBe(true)
    })

    it('sends enabled state in request', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ auth_enabled: false })
      })

      const auth = useAuth()
      await auth.toggleAuth(false)

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: false })
      })
    })

    it('sets error on toggle failure', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Not authorized' })
      })

      const auth = useAuth()
      const result = await auth.toggleAuth(true)

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Not authorized')
    })
  })

  describe('changePassword', () => {
    it('returns true on successful password change', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Password changed' })
      })

      const auth = useAuth()
      const result = await auth.changePassword('oldpass', 'newpass')

      expect(result).toBe(true)
      expect(auth.error.value).toBe('')
    })

    it('sends current and new password in request', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'Password changed' })
      })

      const auth = useAuth()
      await auth.changePassword('currentpwd', 'newpwd')

      expect(fetchMock).toHaveBeenCalledWith('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: 'currentpwd',
          new_password: 'newpwd'
        })
      })
    })

    it('sets error on change failure', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Current password is incorrect' })
      })

      const auth = useAuth()
      const result = await auth.changePassword('wrongpass', 'newpass')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Current password is incorrect')
    })
  })

  describe('clearError', () => {
    it('clears the error value', () => {
      const auth = useAuth()
      auth.error.value = 'Some error'

      auth.clearError()

      expect(auth.error.value).toBe('')
    })
  })
})
