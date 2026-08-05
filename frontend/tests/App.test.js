import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import App from '@/App.vue'
import { DISPLAY_NAME } from '@/version'
import { useSettings } from '@/composables/useSettings'
import { useAppStatus } from '@/composables/useAppStatus'

let infoSpy
let debugSpy
let errorSpy
// Hoisted because useUpdateOverlay.js calls useLogger() at module scope,
// which runs during import — before this file's consts initialize. The
// default implementation hands out a discard-logger for those module-scope
// callers; beforeEach overrides it with per-test spies.
const useLoggerMock = vi.hoisted(() => vi.fn(() => ({
  info: () => {},
  debug: () => {},
  error: () => {}
})))

vi.mock('@/composables/useLogger', () => ({
  useLogger: (...args) => useLoggerMock(...args)
}))

// Mock useAuth composable — rebuilt per test in beforeEach so individual
// tests can flip auth state (e.g. needsLogin after a 401)
const authMock = vi.hoisted(() => ({ current: null }))

vi.mock('@/composables/useAuth', () => ({
  useAuth: () => authMock.current
}))

// Mock api service (App.vue uses axios, not fetch)
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi,
  createLongRequest: () => mockApi
}))

// Mock vue-router
vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {},
    meta: {}
  }),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn()
  })
}))

const mountApp = () => mount(App, {
  global: {
    stubs: {
      'router-link': RouterLinkStub,
      'router-view': {
        template: '<div class="router-view-stub" />'
      },
      'SetupWizard': {
        name: 'SetupWizard',
        props: ['isVisible'],
        template: '<div class="setup-wizard-stub" />'
      },
      'LoginModal': {
        template: '<div class="login-modal-stub" />'
      }
    }
  }
})

describe('App', () => {
  beforeEach(() => {
    infoSpy = vi.fn()
    debugSpy = vi.fn()
    errorSpy = vi.fn()
    useLoggerMock.mockReturnValue({ info: infoSpy, debug: debugSpy, error: errorSpy })

    authMock.current = {
      authStatus: ref({ authEnabled: false, setupComplete: true, authenticated: false, publicFeatures: [] }),
      needsLogin: ref(false),
      loading: ref(false),
      error: ref(''),
      checkAuthStatus: vi.fn().mockResolvedValue(undefined),
      ensureAuthLoaded: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn().mockResolvedValue(undefined),
      clearError: vi.fn()
    }

    // Reset the shared singletons — settings and app status persist across
    // mounts within this file.
    useSettings().resetState()
    useAppStatus().setLocationConfigured(null)
    useAppStatus().setStationName('')

    mockApi.get.mockReset()
    mockApi.get.mockResolvedValue({
      data: {
        location: { configured: true, timezone: 'America/New_York' },
        display: { use_metric_units: true, time_format: null }
      }
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders navigation links', () => {
    const wrapper = mountApp()

    const text = wrapper.text()
    expect(text).toContain(DISPLAY_NAME)
    expect(text).toContain('Dashboard')
    expect(text).toContain('Gallery')
    expect(text).toContain('Live Feed')
    expect(text).toContain('Charts')
    expect(text).toContain('Table')
    expect(text).toContain('Settings')
  })

  it('logs on mount', async () => {
    mountApp()
    await flushPromises()

    expect(useLoggerMock).toHaveBeenCalledWith('App')
    expect(infoSpy).toHaveBeenCalledWith('Application mounted')
    expect(debugSpy).toHaveBeenCalledTimes(1)
  })

  describe('settings bootstrap failure', () => {
    const settingsCalls = () =>
      mockApi.get.mock.calls.filter(([url]) => url === '/settings').length

    let wrapper

    // Every test starts from the same stranded state: the bootstrap
    // /settings load has failed once and a backoff retry is pending.
    beforeEach(async () => {
      vi.useFakeTimers()
      mockApi.get.mockRejectedValue(new Error('timeout'))
      wrapper = mountApp()
      await vi.advanceTimersByTimeAsync(0)
    })

    afterEach(() => {
      if (wrapper) wrapper.unmount()
      wrapper = null
    })

    it('unblocks the dashboard instead of stranding it on null', () => {
      // Optimistically assume configured so the dashboard starts fetching
      // (its own error handling takes over); no wizard on a network error.
      expect(useAppStatus().locationConfigured.value).toBe(true)
      expect(wrapper.getComponent({ name: 'SetupWizard' }).props('isVisible')).toBe(false)
    })

    it('retries with backoff until the load succeeds', async () => {
      expect(settingsCalls()).toBe(1)

      // First retry after 10s
      await vi.advanceTimersByTimeAsync(10000)
      expect(settingsCalls()).toBe(2)

      // Second retry backs off to 20s: nothing at +10s, fires at +20s
      await vi.advanceTimersByTimeAsync(10000)
      expect(settingsCalls()).toBe(2)
      mockApi.get.mockResolvedValue({
        data: {
          location: { configured: true, timezone: 'America/New_York' },
          display: { station_name: 'Backyard Station' }
        }
      })
      await vi.advanceTimersByTimeAsync(10000)
      expect(settingsCalls()).toBe(3)

      // The successful retry syncs state and stops retrying
      expect(wrapper.text()).toContain('Backyard Station')
      await vi.advanceTimersByTimeAsync(120000)
      expect(settingsCalls()).toBe(3)
    })

    it('shows the setup wizard when a retried load reports unconfigured', async () => {
      mockApi.get.mockResolvedValue({
        data: { location: { configured: false }, display: {} }
      })
      await vi.advanceTimersByTimeAsync(10000)

      expect(useAppStatus().locationConfigured.value).toBe(false)
      expect(wrapper.getComponent({ name: 'SetupWizard' }).props('isVisible')).toBe(true)
    })

    it('parks the retry loop when a 401 reveals login is required', async () => {
      expect(settingsCalls()).toBe(1)

      // The api interceptor turns a 401 into an auth:required event; login
      // becomes the recovery path (onLoginSuccess re-runs the bootstrap),
      // so retries would only spam the server and re-pop the login modal.
      authMock.current.checkAuthStatus.mockImplementation(async () => {
        authMock.current.needsLogin.value = true
      })
      window.dispatchEvent(new Event('auth:required'))
      await vi.advanceTimersByTimeAsync(0)

      await vi.advanceTimersByTimeAsync(120000)
      expect(settingsCalls()).toBe(1)
    })

    it('stops retrying on unmount', async () => {
      expect(settingsCalls()).toBe(1)

      wrapper.unmount()
      wrapper = null
      await vi.advanceTimersByTimeAsync(120000)
      expect(settingsCalls()).toBe(1)
    })
  })
})
