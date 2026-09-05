import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import App from '@/App.vue'
import { DISPLAY_NAME } from '@/version'
import { useSettings } from '@/composables/useSettings'
import { useAppStatus } from '@/composables/useAppStatus'
import { useRecorderHealth } from '@/composables/useRecorderHealth'
import MoonIcon from '@/components/icons/MoonIcon.vue'

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

// Mock socket.io — App opens the app-wide recorder-status socket on mount
const socketHandlers = vi.hoisted(() => ({}))
const socketMock = vi.hoisted(() => ({
  on: vi.fn((event, handler) => { socketHandlers[event] = handler }),
  once: vi.fn((event, handler) => { socketHandlers[event] = handler }),
  connect: vi.fn(),
  disconnect: vi.fn()
}))

vi.mock('socket.io-client', () => ({ io: vi.fn(() => socketMock) }))

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
      isAuthenticated: ref(true),
      loading: ref(false),
      error: ref(''),
      checkAuthStatus: vi.fn().mockResolvedValue(undefined),
      ensureAuthLoaded: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn().mockResolvedValue(true),
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

  describe('quiet-hours status FAB', () => {
    const RECORDER_URL = '/recorder/status'
    const settingsPayload = {
      location: { configured: true, timezone: 'America/New_York' },
      display: { use_metric_units: true, time_format: null }
    }

    const withRecorderStatus = (status) => {
      mockApi.get.mockImplementation((url) =>
        Promise.resolve({ data: url === RECORDER_URL ? status : settingsPayload })
      )
    }

    const pausedFab = (wrapper) =>
      wrapper.findAll('a').find(a => a.text().includes('Paused'))

    // The composable is a module-level singleton — hand it back a clean state
    // so a paused test can't leak into the next one.
    afterEach(async () => {
      withRecorderStatus({ state: 'running' })
      await useRecorderHealth().checkStatus()
    })

    it('shows a paused pill with the resume time while quiet hours are active', async () => {
      withRecorderStatus({
        state: 'paused',
        pause: { reason: 'quiet_hours', resumes_at: '2026-08-25T06:00' }
      })

      const wrapper = mountApp()
      await flushPromises()

      const fab = pausedFab(wrapper)
      expect(fab).toBeDefined()
      expect(fab.text()).toContain('6:00')
      expect(fab.classes()).toContain('bg-blue-600')
      expect(fab.attributes('title')).toBe('Recording is paused by quiet hours')
      expect(fab.findComponent(MoonIcon).exists()).toBe(true)
      // Informational: it links to Settings but is not a dismissible warning
      expect(wrapper.text()).not.toContain('Audio Recording Issues')
    })

    it('shows the same pill, without a moon, when no source is active', async () => {
      withRecorderStatus({
        state: 'paused',
        pause: { reason: 'no_sources', resumes_at: null }
      })

      const wrapper = mountApp()
      await flushPromises()

      const fab = pausedFab(wrapper)
      expect(fab).toBeDefined()
      expect(fab.text()).toBe('Audio Paused')
      expect(fab.classes()).toContain('bg-blue-600')
      expect(fab.attributes('title')).toBe('Recording is paused — no audio source is active')
      // A moon reads as night, which this pause is not.
      expect(fab.findComponent(MoonIcon).exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Audio Recording Issues')
    })

    it('follows a pause pushed after the page loaded, with no refetch', async () => {
      withRecorderStatus({ state: 'running' })

      const wrapper = mountApp()
      await flushPromises()
      expect(pausedFab(wrapper)).toBeUndefined()

      // What the recorder broadcasts when the last source is switched off.
      socketHandlers.recorder_status({
        state: 'paused',
        pause: { reason: 'no_sources', resumes_at: null }
      })
      await wrapper.vm.$nextTick()

      expect(pausedFab(wrapper).text()).toBe('Audio Paused')
    })

    it('shows no pill while recording', async () => {
      withRecorderStatus({ state: 'running' })

      const wrapper = mountApp()
      await flushPromises()

      expect(pausedFab(wrapper)).toBeUndefined()
    })

    it('yields the corner to the recorder-fault warning', async () => {
      withRecorderStatus({ state: 'stopped' })

      const wrapper = mountApp()
      await flushPromises()

      expect(wrapper.text()).toContain('Audio Recording Issues')
      expect(pausedFab(wrapper)).toBeUndefined()
    })

    it('takes the corner ahead of an available update', async () => {
      withRecorderStatus({
        state: 'paused',
        pause: { reason: 'quiet_hours', resumes_at: '2026-08-25T06:00' }
      })

      const wrapper = mountApp()
      await flushPromises()
      // showUpdateIndicator is a computed — driving it means setting the
      // updateAvailable ref it derives from, or the assignment is a silent
      // no-op and this test passes without an update indicator to outrank.
      wrapper.vm.systemUpdate.updateAvailable.value = true
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.systemUpdate.showUpdateIndicator.value).toBe(true)

      expect(pausedFab(wrapper)).toBeDefined()
      expect(wrapper.text()).not.toContain('Update Available')

      wrapper.vm.systemUpdate.updateAvailable.value = false
    })
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
