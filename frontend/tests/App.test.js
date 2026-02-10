import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import App from '@/App.vue'
import { DISPLAY_NAME } from '@/version'

let infoSpy
let debugSpy
let errorSpy
const useLoggerMock = vi.fn()

vi.mock('@/composables/useLogger', () => ({
  useLogger: (...args) => useLoggerMock(...args)
}))

// Mock useAuth composable
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    authStatus: ref({ authEnabled: false, setupComplete: true, authenticated: false }),
    needsLogin: ref(false),
    loading: ref(false),
    error: ref(''),
    checkAuthStatus: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    clearError: vi.fn()
  })
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
      'LocationSetupModal': {
        template: '<div class="location-setup-modal-stub" />'
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

    // Mock fetch for settings check
    global.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ location: { configured: true } })
    }))
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
})
