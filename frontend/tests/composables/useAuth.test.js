/**
 * Tests for useAuth composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock the api service (must come before useAuth import so the module sees the mock)
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi,
  api: mockApi
}))

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  })
}))

import { useAuth } from '@/composables/useAuth'

const axiosError = (status, data) => ({ response: { status, data } })

describe('useAuth', () => {
  beforeEach(() => {
    mockApi.get.mockReset()
    mockApi.post.mockReset()
    mockApi.put.mockReset()
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

    it('has saveAccessSettings method', () => {
      const auth = useAuth()
      expect(auth).toHaveProperty('saveAccessSettings')
    })

    it('initializes with default auth status', () => {
      const auth = useAuth()

      expect(auth.authStatus.value).toEqual({
        authEnabled: false,
        setupComplete: false,
        authenticated: false,
        publicFeatures: [],
        stationName: ''
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
      mockApi.get.mockResolvedValueOnce({
        status: 200,
        data: {
          auth_enabled: true,
          setup_complete: true,
          authenticated: false,
          public_features: ['charts']
        }
      })

      const auth = useAuth()
      await auth.checkAuthStatus()

      expect(mockApi.get).toHaveBeenCalledWith('/auth/status')
      expect(auth.authStatus.value).toEqual({
        authEnabled: true,
        setupComplete: true,
        authenticated: false,
        publicFeatures: ['charts'],
        stationName: ''
      })
    })

    it('defaults publicFeatures to empty array when not in response', async () => {
      mockApi.get.mockResolvedValueOnce({
        status: 200,
        data: {
          auth_enabled: false,
          setup_complete: false,
          authenticated: true
        }
      })

      const auth = useAuth()
      await auth.checkAuthStatus()

      expect(auth.authStatus.value.publicFeatures).toEqual([])
    })

    it('handles network error gracefully', async () => {
      mockApi.get.mockRejectedValueOnce(new Error('Network error'))

      const auth = useAuth()
      await auth.checkAuthStatus()

      // Should not throw, and status should remain default
      expect(auth.authStatus.value.authEnabled).toBe(false)
    })
  })

  describe('login', () => {
    it('sets authenticated to true on successful login', async () => {
      mockApi.post.mockResolvedValueOnce({
        status: 200,
        data: { message: 'Login successful' }
      })

      const auth = useAuth()
      const result = await auth.login('testpassword')

      expect(result).toBe(true)
      expect(auth.authStatus.value.authenticated).toBe(true)
      expect(auth.error.value).toBe('')
    })

    it('sends password in request body', async () => {
      mockApi.post.mockResolvedValueOnce({ status: 200, data: {} })

      const auth = useAuth()
      await auth.login('mypassword123')

      expect(mockApi.post).toHaveBeenCalledWith('/auth/login', { password: 'mypassword123' })
    })

    it('sets error from server response on failed login', async () => {
      mockApi.post.mockRejectedValueOnce(axiosError(401, { error: 'Invalid password' }))

      const auth = useAuth()
      const result = await auth.login('wrongpassword')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Invalid password')
      expect(auth.authStatus.value.authenticated).toBe(false)
    })

    it('uses generic error message when server provides none', async () => {
      mockApi.post.mockRejectedValueOnce(axiosError(500, {}))

      const auth = useAuth()
      await auth.login('password')

      expect(auth.error.value).toBe('Login failed')
    })

    it('distinguishes network errors from server errors', async () => {
      mockApi.post.mockRejectedValueOnce(new Error('Network error'))

      const auth = useAuth()
      const result = await auth.login('password')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Connection error')
    })

    it('sets loading state during login', async () => {
      let resolvePromise
      mockApi.post.mockReturnValueOnce(new Promise((resolve) => {
        resolvePromise = resolve
      }))

      const auth = useAuth()
      const loginPromise = auth.login('password')

      expect(auth.loading.value).toBe(true)

      resolvePromise({ status: 200, data: {} })
      await loginPromise

      expect(auth.loading.value).toBe(false)
    })
  })

  describe('logout', () => {
    it('clears authenticated status', async () => {
      mockApi.post.mockResolvedValueOnce({ status: 200, data: {} })

      const auth = useAuth()
      auth.authStatus.value.authenticated = true

      await auth.logout()

      expect(auth.authStatus.value.authenticated).toBe(false)
    })

    it('sends POST request to logout endpoint', async () => {
      mockApi.post.mockResolvedValueOnce({ status: 200, data: {} })

      const auth = useAuth()
      await auth.logout()

      expect(mockApi.post).toHaveBeenCalledWith('/auth/logout')
    })
  })

  describe('setup', () => {
    it('sets setupComplete and authenticated on success', async () => {
      mockApi.post.mockResolvedValueOnce({
        status: 200,
        data: { message: 'Password set' }
      })

      const auth = useAuth()
      const result = await auth.setup('newpassword')

      expect(result).toBe(true)
      expect(auth.authStatus.value.setupComplete).toBe(true)
      expect(auth.authStatus.value.authenticated).toBe(true)
    })

    it('sends password to setup endpoint', async () => {
      mockApi.post.mockResolvedValueOnce({ status: 200, data: {} })

      const auth = useAuth()
      await auth.setup('mynewpassword')

      expect(mockApi.post).toHaveBeenCalledWith('/auth/setup', { password: 'mynewpassword' })
    })

    it('sets error from server response on setup failure', async () => {
      mockApi.post.mockRejectedValueOnce(axiosError(400, { error: 'Password too short' }))

      const auth = useAuth()
      const result = await auth.setup('abc')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Password too short')
    })
  })

  describe('toggleAuth', () => {
    it('updates authEnabled on success', async () => {
      mockApi.post.mockResolvedValueOnce({
        status: 200,
        data: { auth_enabled: true }
      })

      const auth = useAuth()
      const result = await auth.toggleAuth(true)

      expect(result).toBe(true)
      expect(auth.authStatus.value.authEnabled).toBe(true)
    })

    it('sends enabled state in request', async () => {
      mockApi.post.mockResolvedValueOnce({
        status: 200,
        data: { auth_enabled: false }
      })

      const auth = useAuth()
      await auth.toggleAuth(false)

      expect(mockApi.post).toHaveBeenCalledWith('/auth/toggle', { enabled: false })
    })

    it('sets error from server response on toggle failure', async () => {
      mockApi.post.mockRejectedValueOnce(axiosError(401, { error: 'Not authorized' }))

      const auth = useAuth()
      const result = await auth.toggleAuth(true)

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Not authorized')
    })
  })

  describe('changePassword', () => {
    it('returns true on successful password change', async () => {
      mockApi.post.mockResolvedValueOnce({
        status: 200,
        data: { message: 'Password changed' }
      })

      const auth = useAuth()
      const result = await auth.changePassword('oldpass', 'newpass')

      expect(result).toBe(true)
      expect(auth.error.value).toBe('')
    })

    it('sends current and new password in request', async () => {
      mockApi.post.mockResolvedValueOnce({ status: 200, data: {} })

      const auth = useAuth()
      await auth.changePassword('currentpwd', 'newpwd')

      expect(mockApi.post).toHaveBeenCalledWith('/auth/change-password', {
        current_password: 'currentpwd',
        new_password: 'newpwd'
      })
    })

    it('sets error from server response on change failure', async () => {
      mockApi.post.mockRejectedValueOnce(axiosError(403, { error: 'Current password is incorrect' }))

      const auth = useAuth()
      const result = await auth.changePassword('wrongpass', 'newpass')

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Current password is incorrect')
    })
  })

  describe('saveAccessSettings', () => {
    it('sends correct PUT body', async () => {
      mockApi.put.mockResolvedValueOnce({
        status: 200,
        data: { success: true, access: { charts_public: true } }
      })
      mockApi.get.mockResolvedValueOnce({
        status: 200,
        data: {
          auth_enabled: true,
          setup_complete: true,
          authenticated: true,
          public_features: ['charts']
        }
      })

      const auth = useAuth()
      const result = await auth.saveAccessSettings({ charts_public: true })

      expect(result).toBe(true)
      expect(mockApi.put).toHaveBeenCalledWith('/settings/access', { charts_public: true })
    })

    it('refreshes auth status on success', async () => {
      mockApi.put.mockResolvedValueOnce({ status: 200, data: { success: true } })
      mockApi.get.mockResolvedValueOnce({
        status: 200,
        data: {
          auth_enabled: true,
          setup_complete: true,
          authenticated: true,
          public_features: ['charts', 'table']
        }
      })

      const auth = useAuth()
      await auth.saveAccessSettings({ charts_public: true })

      expect(auth.authStatus.value.publicFeatures).toEqual(['charts', 'table'])
    })

    it('sets error from server response on failure', async () => {
      mockApi.put.mockRejectedValueOnce(axiosError(401, { error: 'Not authorized' }))

      const auth = useAuth()
      const result = await auth.saveAccessSettings({ charts_public: true })

      expect(result).toBe(false)
      expect(auth.error.value).toBe('Not authorized')
    })
  })

  describe('resetState', () => {
    it('clears publicFeatures', () => {
      const auth = useAuth()
      auth.authStatus.value.publicFeatures = ['charts', 'table']

      auth.resetState()

      expect(auth.authStatus.value.publicFeatures).toEqual([])
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
