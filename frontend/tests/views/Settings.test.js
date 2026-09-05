import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import Settings from '@/views/Settings.vue'
import { RECORDER_STATES } from '@/utils/recorderStates'
import { useRecorderHealth } from '@/composables/useRecorderHealth'
import { useSettings } from '@/composables/useSettings'

const socketHandlers = vi.hoisted(() => ({}))
const socketOnMock = vi.hoisted(() => vi.fn((event, handler) => {
  socketHandlers[event] = handler
}))
const socketDisconnectMock = vi.hoisted(() => vi.fn())

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi,
  createLongRequest: () => mockApi
}))

const ioMock = vi.hoisted(() => vi.fn(() => ({
  on: socketOnMock,
  once: socketOnMock,
  disconnect: socketDisconnectMock
})))

vi.mock('socket.io-client', () => ({
  io: ioMock
}))

// Mock the useServiceRestart composable (expose waitForRestart for assertions)
const mockWaitForRestart = vi.hoisted(() => vi.fn().mockResolvedValue(true))
const mockRequestRestart = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
const mockCaptureBaseline = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ bootId: 'boot-1', commit: 'c1', version: '1.0.0' })
)
vi.mock('@/composables/useServiceRestart', () => ({
  requestRestart: mockRequestRestart,
  captureRestartBaseline: mockCaptureBaseline,
  useServiceRestart: () => ({
    isRestarting: { value: false },
    restartMessage: { value: '' },
    restartError: { value: '' },
    waitForRestart: mockWaitForRestart,
    reset: vi.fn()
  })
}))

// Mock the useSystemUpdate composable to avoid extra fetch calls
const mockSystemUpdate = vi.hoisted(() => ({
  versionInfo: { value: null },
  updateInfo: { value: null },
  updateAvailable: { value: false },
  checking: { value: false },
  updating: { value: false },
  statusMessage: { value: null },
  statusType: { value: null },
  showUpdateIndicator: { value: false },
  dismissUpdate: vi.fn(),
  restartMessage: { value: '' },
  restartError: { value: '' },
  isRestarting: { value: false },
  loadVersionInfo: vi.fn().mockResolvedValue({}),
  checkForUpdates: vi.fn().mockResolvedValue({}),
  triggerUpdate: vi.fn().mockResolvedValue({})
}))

vi.mock('@/composables/useSystemUpdate', () => ({
  useSystemUpdate: () => mockSystemUpdate
}))

enableAutoUnmount(afterEach)
afterEach(() => { document.body.style.overflow = '' })

// Mock the useAuth composable to avoid extra fetch calls
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    authStatus: { value: { authEnabled: false, setupComplete: true, authenticated: false } },
    loading: { value: false },
    error: { value: '' },
    needsLogin: { value: false },
    isAuthenticated: { value: true },
    checkAuthStatus: vi.fn().mockResolvedValue(undefined),
    ensureAuthLoaded: vi.fn().mockResolvedValue(undefined),
    login: vi.fn().mockResolvedValue(true),
    logout: vi.fn().mockResolvedValue(true),
    setup: vi.fn().mockResolvedValue(true),
    toggleAuth: vi.fn().mockResolvedValue(true),
    saveAccessSettings: vi.fn().mockResolvedValue(true),
    changePassword: vi.fn().mockResolvedValue(true),
    clearError: vi.fn()
  })
}))

const mockSettings = {
  location: {
    latitude: 42.47,
    longitude: -76.45
  },
  detection: {
    sensitivity: 0.75,
    cutoff: 0.60
  },
  audio: {
    sources: [
      { id: 'source_0', type: 'pulseaudio', device: 'default', label: 'Microphone', enabled: true }
    ],
    next_source_id: 1,
    recording_length: 9,
    overlap: 0.0,
    sample_rate: 48000,
    recording_chunk_length: 3
  },
  spectrogram: {
    max_freq_khz: 12,
    min_freq_khz: 0,
    max_dbfs: 0,
    min_dbfs: -120
  },
  model: {
    type: 'birdnet'
  },
  general: {
    timezone: 'UTC',
    language: 'en'
  },
  notifications: {
    enabled: false,
    apprise_url: null,
    every_detection: true,
    rate_limit_seconds: 300,
    first_of_day: true,
    rare_species: false,
    rare_threshold: 3,
    rare_window_days: 7
  },
  display: {
    station_name: '',
    site_url: '',
    bird_name_language: 'en',
    use_metric_units: true,
    time_format: null
  },
  updates: {
    channel: 'release'
  },
  schedule: {
    quiet_hours: { enabled: false, start: '22:00', end: '06:00' }
  },
  storage: {
    auto_cleanup_enabled: true,
    trigger_percent: 85,
    target_percent: 80,
    keep_per_species: 60,
    check_interval_minutes: 30
  },
  access: {
    charts_public: false,
    table_public: false,
    live_feed_public: false
  }
}

const createMockSettings = () => structuredClone(mockSettings)

const defaultGetResponse = (url) => {
  if (url === '/settings' || url === '/settings/defaults') {
    return Promise.resolve({ data: createMockSettings() })
  }
  if (url === '/species/available') {
    return Promise.resolve({ data: { species: [], total: 0, filtered: 0 } })
  }
  if (url === '/system/storage') {
    return Promise.resolve({ data: {} })
  }
  if (url === '/recorder/status') {
    return Promise.resolve({ data: {} })
  }
  if (url === '/model/status') {
    return Promise.resolve({
      data: {
        status: 'ok',
        location_filter: {
          state: 'active',
          source: 'meta_model_v2.4',
          version: '2.4',
          code: null,
          message: null
        }
      }
    })
  }
  return Promise.resolve({ data: {} })
}

const mountSettings = () => mount(Settings, {
  global: {
    stubs: {
      'font-awesome-icon': true
    }
  }
})

// Make GET /settings hang until the returned release() is called, so a test
// can observe the form's pre-load (skeleton) state. Other URLs fall through
// to the defaults.
const deferSettingsFetch = (payload = createMockSettings()) => {
  let release
  mockApi.get.mockImplementation((url) =>
    url === '/settings'
      ? new Promise((resolve) => { release = () => resolve({ data: structuredClone(payload) }) })
      : defaultGetResponse(url)
  )
  return () => release()
}

describe('Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Recorder status lives in the useRecorderHealth singleton — clear it so
    // one test's status can't leak into the next.
    useRecorderHealth().recorderStatus.value = null
    useSettings().resetState()
    Object.keys(socketHandlers).forEach((key) => delete socketHandlers[key])
    socketOnMock.mockClear()
    socketDisconnectMock.mockClear()
    ioMock.mockClear()
    mockApi.get.mockReset()
    mockApi.put.mockReset()
    mockApi.post.mockReset()
    mockWaitForRestart.mockReset()
    mockWaitForRestart.mockResolvedValue(true)
    // Reset systemUpdate mock state
    mockSystemUpdate.versionInfo.value = null
    mockSystemUpdate.updateInfo.value = null
    mockSystemUpdate.updateAvailable.value = false
    mockSystemUpdate.checking.value = false
    mockSystemUpdate.updating.value = false
    mockSystemUpdate.statusMessage.value = null
    mockSystemUpdate.statusType.value = null
    mockSystemUpdate.showUpdateIndicator.value = false
    mockApi.post.mockResolvedValue({ data: { status: 'restart_requested' } })
    mockApi.get.mockImplementation(defaultGetResponse)
  })

  describe('Loading Settings', () => {
    it('loads settings from API on mount', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(mockApi.get).toHaveBeenCalledWith('/settings')
      expect(wrapper.vm.settings.audio.recording_length).toBe(9)
      expect(wrapper.vm.settings.audio.overlap).toBe(0.0)
    })

    it('shows a skeleton until the first payload lands, not empty-state text', async () => {
      // Cold store: clear the shared singleton so nothing seeds the form, and
      // hold the /settings response so the form stays in its pre-load state.
      useSettings().resetState()
      const releaseSettings = deferSettingsFetch()

      const wrapper = mountSettings()
      await wrapper.vm.$nextTick()

      // Before data: skeleton visible, form body gated, no misleading pause hint.
      expect(wrapper.vm.loaded).toBe(false)
      expect(wrapper.find('[data-testid="settings-skeleton"]').exists()).toBe(true)
      expect(wrapper.vm.noActiveSourceHint).toBe('')
      expect(wrapper.find('[data-testid="no-active-source-hint"]').exists()).toBe(false)

      releaseSettings()
      await flushPromises()

      // After data: skeleton gone, real form rendered.
      expect(wrapper.vm.loaded).toBe(true)
      expect(wrapper.find('[data-testid="settings-skeleton"]').exists()).toBe(false)
      expect(wrapper.text()).toContain('Microphone')
    })

    it('seeds the form synchronously from an already-loaded store (no flash)', async () => {
      // Warm store (the common navigation case): App.vue loaded it earlier.
      const store = useSettings()
      store.resetState()
      store.setSettings(createMockSettings())

      // Hold the background revalidation so the seed is the ONLY thing that
      // can populate the form.
      const releaseSettings = deferSettingsFetch()

      const wrapper = mountSettings()
      // loaded flips true during onMounted, before any network resolves.
      expect(wrapper.vm.loaded).toBe(true)

      // DOM reflects the seed on the next tick — no await on the fetch.
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-testid="settings-skeleton"]').exists()).toBe(false)
      expect(wrapper.text()).toContain('Microphone')

      releaseSettings()
      await flushPromises()
    })

    it('does not overwrite warm-form edits when background revalidation finishes', async () => {
      const store = useSettings()
      const cached = createMockSettings()
      cached.display.station_name = 'Cached station'
      store.setSettings(cached)

      const refreshed = createMockSettings()
      refreshed.display.station_name = 'Server station'
      const releaseSettings = deferSettingsFetch(refreshed)
      const wrapper = mountSettings()

      wrapper.vm.settings.display.station_name = 'Unsaved edit'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.hasUnsavedChanges).toBe(true)

      releaseSettings()
      await flushPromises()

      expect(wrapper.vm.settings.display.station_name).toBe('Unsaved edit')
      expect(wrapper.vm.hasUnsavedChanges).toBe(true)
      expect(store.settings.value.display.station_name).toBe('Server station')
    })

    it('keeps warm cached settings when background revalidation exhausts its retries', async () => {
      vi.useFakeTimers()
      try {
        const cached = createMockSettings()
        cached.display.station_name = 'Known-good station'
        useSettings().setSettings(cached)
        mockApi.get.mockImplementation((url) =>
          url === '/settings'
            ? Promise.reject(new Error('settings unavailable'))
            : defaultGetResponse(url)
        )

        const wrapper = mountSettings()
        await flushPromises()
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()

        expect(wrapper.vm.settings.display.station_name).toBe('Known-good station')
        expect(wrapper.vm.saveStatus).toEqual({
          type: 'error',
          message: 'Could not refresh settings. Showing last loaded settings.'
        })
        expect(mockApi.get).not.toHaveBeenCalledWith('/settings/defaults')
      } finally {
        vi.useRealTimers()
      }
    })

    it('still falls back to defaults when a genuine cold load exhausts its retries', async () => {
      vi.useFakeTimers()
      try {
        const defaults = createMockSettings()
        defaults.display.station_name = 'Default station'
        mockApi.get.mockImplementation((url) => {
          if (url === '/settings') return Promise.reject(new Error('settings unavailable'))
          if (url === '/settings/defaults') return Promise.resolve({ data: defaults })
          return defaultGetResponse(url)
        })

        const wrapper = mountSettings()
        await flushPromises()
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()

        expect(mockApi.get).toHaveBeenCalledWith('/settings/defaults')
        expect(wrapper.vm.loaded).toBe(true)
        expect(wrapper.vm.settings.display.station_name).toBe('Default station')
      } finally {
        vi.useRealTimers()
      }
    })

    it('loads model and location-filter status on mount', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(mockApi.get).toHaveBeenCalledWith('/model/status')
      expect(wrapper.vm.modelStatus.location_filter.state).toBe('active')
      expect(wrapper.find('[data-testid="location-filter-warning"]').exists()).toBe(false)
    })

    it('shows a persistent warning when location filtering is degraded', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url !== '/model/status') return defaultGetResponse(url)
        return Promise.resolve({
          data: {
            status: 'degraded',
            location_filter: {
              state: 'degraded',
              source: 'disabled',
              version: null,
              code: 'geomodel_validation_failed',
              message: 'Location filtering failed to start. Acoustic detections are continuing without location filtering; check System Logs for details.'
            }
          }
        })
      })

      const wrapper = mountSettings()
      await flushPromises()

      const warning = wrapper.find('[data-testid="location-filter-warning"]')
      expect(warning.exists()).toBe(true)
      expect(warning.text()).toContain('Acoustic detections are continuing without location filtering')
      expect(warning.text()).not.toContain('Dismiss')
    })

    it('does not render intentionally disabled filtering as an error', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url !== '/model/status') return defaultGetResponse(url)
        return Promise.resolve({
          data: {
            status: 'ok',
            location_filter: {
              state: 'disabled',
              source: 'disabled',
              message: 'Location filtering is disabled.'
            }
          }
        })
      })

      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.find('[data-testid="location-filter-warning"]').exists()).toBe(false)
    })

    it('rechecks a temporarily unavailable model service and clears the warning', async () => {
      vi.useFakeTimers()
      let statusCalls = 0
      mockApi.get.mockImplementation((url) => {
        if (url !== '/model/status') return defaultGetResponse(url)
        statusCalls += 1
        if (statusCalls === 1) {
          return Promise.resolve({
            data: {
              status: 'unavailable',
              location_filter: {
                state: 'unavailable',
                source: 'disabled',
                message: 'Model service status is unavailable.'
              }
            }
          })
        }
        return defaultGetResponse(url)
      })

      const wrapper = mountSettings()
      await flushPromises()
      expect(wrapper.text()).toContain('Model service status is unavailable.')

      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()

      expect(statusCalls).toBe(2)
      expect(wrapper.find('[data-testid="location-filter-warning"]').exists()).toBe(false)
      vi.useRealTimers()
    })

    it('retries after a transient model-status fetch failure', async () => {
      vi.useFakeTimers()
      let statusCalls = 0
      mockApi.get.mockImplementation((url) => {
        if (url !== '/model/status') return defaultGetResponse(url)
        statusCalls += 1
        if (statusCalls === 1) return Promise.reject(new Error('nginx restarting'))
        return defaultGetResponse(url)
      })

      const wrapper = mountSettings()
      await flushPromises()
      expect(statusCalls).toBe(1)

      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()

      expect(statusCalls).toBe(2)
      expect(wrapper.vm.modelStatus.location_filter.state).toBe('active')
      vi.useRealTimers()
    })

    it('does not schedule polling when an in-flight fetch resolves after unmount', async () => {
      vi.useFakeTimers()
      let resolveStatus
      let statusCalls = 0
      mockApi.get.mockImplementation((url) => {
        if (url !== '/model/status') return defaultGetResponse(url)
        statusCalls += 1
        return new Promise((resolve) => { resolveStatus = resolve })
      })

      const wrapper = mountSettings()
      await Promise.resolve()
      wrapper.unmount()
      resolveStatus({
        data: {
          status: 'unavailable',
          location_filter: { state: 'unavailable', source: 'disabled' }
        }
      })
      await flushPromises()
      await vi.advanceTimersByTimeAsync(5000)

      expect(statusCalls).toBe(1)
      vi.useRealTimers()
    })

    it('retries loading settings on failure', async () => {
      vi.useFakeTimers()
      let settingsCallCount = 0
      mockApi.get.mockImplementation((url) => {
        if (url === '/system/storage') {
          return Promise.resolve({ data: {} })
        }
        if (url === '/settings') {
          settingsCallCount += 1
          if (settingsCallCount < 3) {
            return Promise.reject(new Error('Network error'))
          }
          return Promise.resolve({ data: createMockSettings() })
        }
        return Promise.resolve({ data: {} })
      })

      mountSettings()
      await flushPromises()

      // First attempt only
      expect(mockApi.get.mock.calls.filter(call => call[0] === '/settings')).toHaveLength(1)

      // Wait for retries (2 seconds each)
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(mockApi.get.mock.calls.filter(call => call[0] === '/settings')).toHaveLength(3)
      vi.useRealTimers()
    })
  })

  describe('Recording Settings Section', () => {
    it('loads recorder status on mount', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/settings' || url === '/settings/defaults') {
          return Promise.resolve({ data: createMockSettings() })
        }
        if (url === '/species/available') {
          return Promise.resolve({ data: { species: [], total: 0, filtered: 0 } })
        }
        if (url === '/system/storage') {
          return Promise.resolve({ data: {} })
        }
        if (url === '/recorder/status') {
          return Promise.resolve({
            data: {
              state: RECORDER_STATES.RUNNING,
              sources: {
                source_0: {
                  label: 'Microphone',
                  type: 'pulseaudio',
                  state: RECORDER_STATES.RUNNING
                }
              }
            }
          })
        }
        return Promise.resolve({ data: {} })
      })

      const wrapper = mountSettings()
      await flushPromises()

      expect(mockApi.get).toHaveBeenCalledWith('/recorder/status')
      expect(wrapper.vm.recorderStatus.state).toBe(RECORDER_STATES.RUNNING)
    })

    it('displays recording settings within Detection section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Chunk Length')
    })

    it('shows recording length dropdown with correct options', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const trigger = wrapper.find('button#recordingLength')
      expect(trigger.exists()).toBe(true)

      const options = [...trigger.element.parentElement.querySelectorAll('li[role="option"]')]
      expect(options.map(o => o.textContent.trim())).toEqual([
        '9 seconds', '12 seconds', '15 seconds'
      ])
    })

    it('shows overlap dropdown with correct options', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const trigger = wrapper.find('button#overlap')
      expect(trigger.exists()).toBe(true)

      const options = [...trigger.element.parentElement.querySelectorAll('li[role="option"]')]
      expect(options.map(o => o.textContent.trim())).toEqual([
        'None', '0.5s', '1.0s', '1.5s', '2.0s', '2.5s'
      ])
    })

    it('displays current recording_length value', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const trigger = wrapper.find('button#recordingLength')
      expect(trigger.text()).toContain('9 seconds')
    })

    it('displays current overlap value', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const trigger = wrapper.find('button#overlap')
      expect(trigger.text()).toContain('None')
    })

    it('updates recording_length when dropdown changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Directly update the value to simulate v-model.number behavior
      wrapper.vm.settings.audio.recording_length = 12
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.settings.audio.recording_length).toBe(12)
    })

    it('updates overlap when dropdown changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Directly update the value to simulate v-model.number behavior
      wrapper.vm.settings.audio.overlap = 1.5
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.settings.audio.overlap).toBe(1.5)
    })
  })

  describe('Other Settings Sections', () => {
    it('displays Location and Audio sections', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Location')
      expect(wrapper.text()).toContain('Audio')
      expect(wrapper.find('#latitude').exists()).toBe(true)
      expect(wrapper.find('#longitude').exists()).toBe(true)
      expect(wrapper.text()).toContain('Microphone')
    })

    it('displays Detection section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Detection')
      expect(wrapper.find('#sensitivity').exists()).toBe(true)
      expect(wrapper.find('#cutoff').exists()).toBe(true)
    })

    it('does NOT display General Settings section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).not.toContain('General Settings')
      expect(wrapper.text()).not.toContain('Timezone')
      expect(wrapper.text()).toContain('Personalization')
      expect(wrapper.text()).toContain('Bird Name Language')
    })
  })

  describe('Site URL Setting', () => {
    it('renders the site URL input in Personalization', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.find('#siteUrl').exists()).toBe(true)
    })

    it('hides the example-link preview when site URL is empty', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).not.toContain('Links will look like')
    })

    it('previews the normalized link for a bare host', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.display.site_url = 'birdnet.example.com'
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain(
        'https://birdnet.example.com/bird/Northern%20Cardinal/recording/123'
      )
    })

    it('strips trailing slashes and keeps an explicit http scheme in the preview', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.display.site_url = 'http://192.168.1.50/'
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain(
        'http://192.168.1.50/bird/Northern%20Cardinal/recording/123'
      )
    })
  })

  describe('Saving Settings', () => {
    it('saves settings when Save button clicked', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved! Services will restart in 10-30 seconds.',
          settings: mockSettings
        }
      })

      // Change a value directly to simulate v-model.number behavior
      wrapper.vm.settings.audio.recording_length = 12
      await wrapper.vm.$nextTick()

      // Click save button
      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')
      await flushPromises()

      // Verify PUT request was made
      expect(mockApi.put).toHaveBeenCalledWith('/settings', expect.objectContaining({
        audio: expect.objectContaining({
          recording_length: 12
        })
      }))
    })

    it('saves settings and triggers service restart', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved',
          settings: mockSettings
        }
      })

      // Make a change so hasUnsavedChanges becomes true
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')
      await flushPromises()

      // Verify PUT request was made
      expect(mockApi.put).toHaveBeenCalledWith('/settings', expect.any(Object))
      // Note: Page auto-reloads after service restart via useServiceRestart composable
    })

    it('shows error message on save failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockRejectedValueOnce(new Error('Failed to save settings'))

      // Make a change so hasUnsavedChanges becomes true
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Failed to save')
    })

    it('surfaces the server validation message on a 400 save failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const rejection = new Error('Request failed with status code 400')
      rejection.response = {
        status: 400,
        data: { error: 'Site URL must start with http:// or https://' }
      }
      mockApi.put.mockRejectedValueOnce(rejection)

      wrapper.vm.settings.display.site_url = 'ftp://example.com'
      await wrapper.vm.$nextTick()

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Site URL must start with http:// or https://')
    })

    it('disables save button while saving', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockImplementationOnce(() => new Promise(resolve => setTimeout(resolve, 100)))

      // Make a change so hasUnsavedChanges becomes true
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')

      expect(wrapper.vm.loading).toBe(true)
      expect(saveButton.attributes('disabled')).toBeDefined()
    })

    it('disables Save while a system update is in flight', async () => {
      mockSystemUpdate.updating.value = true
      const wrapper = mountSettings()
      await flushPromises()

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      expect(saveButton.attributes('disabled')).toBeDefined()
    })

    it('a restart-required save dispatches the restart when no update is in flight', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved',
          settings: createMockSettings(),
          changes: { full_restart_required: true }
        }
      })

      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()
      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockRequestRestart).toHaveBeenCalled()
      expect(mockWaitForRestart).toHaveBeenCalledWith(
        expect.objectContaining({ expect: 'restart' })
      )
    })

    it('a restart-required save during an update defers to the update instead of dispatching a competing restart', async () => {
      mockSystemUpdate.updating.value = true
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved',
          settings: createMockSettings(),
          changes: { full_restart_required: true }
        }
      })

      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()
      // The Save button is disabled during an update, but the guard must
      // live in the method too: an update can be mid-dispatch before its
      // wait flips isRestarting, leaving the button briefly clickable.
      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalled()
      expect(mockRequestRestart).not.toHaveBeenCalled()
      expect(mockWaitForRestart).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('take effect after the update completes')
    })

    it('does not render Reset button', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const resetButton = wrapper.findAll('button').find(btn => btn.text() === 'Reset')
      expect(resetButton).toBeUndefined()
    })
  })

  describe('Audio Source List', () => {
    // Helper: add an RTSP source via the modal handler
    const addSource = (wrapper, source) => {
      wrapper.vm.handleStreamAdd(source)
    }

    it('shows Microphone as default active source', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const sources = wrapper.vm.settings.audio.sources
      expect(sources).toHaveLength(1)
      expect(sources[0].type).toBe('pulseaudio')
      expect(sources[0].enabled).toBe(true)
      expect(wrapper.text()).toContain('Microphone')
    })

    it('hints that recording is paused when every source is disabled', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.audio.sources[0].enabled = false
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.noActiveSourceHint).toContain('recording is paused')
      expect(wrapper.find('[data-testid="no-active-source-hint"]').exists()).toBe(true)
      // The "highlighted sources are active" legend needs something highlighted.
      expect(wrapper.vm.hasInactiveSource).toBe(false)
    })

    it('shows the active-source legend only for a mixed list', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream', label: '' })
      wrapper.vm.settings.audio.sources[0].enabled = false
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.hasInactiveSource).toBe(true)
      expect(wrapper.vm.noActiveSourceHint).toBe('')
      expect(wrapper.find('[data-testid="no-active-source-hint"]').exists()).toBe(false)
    })

    it('adds RTSP source with enabled flag', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream', label: '' })

      const sources = wrapper.vm.settings.audio.sources
      const rtsp = sources.find(s => s.type === 'rtsp')
      expect(rtsp).toBeTruthy()
      expect(rtsp.url).toBe('rtsp://192.168.1.100:554/stream')
      expect(rtsp.enabled).toBe(true)
      expect(wrapper.vm.showStreamModal).toBe(false)
    })

    it('adds RTSP source with label', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream', label: 'Backyard mic' })

      const sources = wrapper.vm.settings.audio.sources
      const rtsp = sources.find(s => s.url === 'rtsp://192.168.1.100:554/stream')
      expect(rtsp.label).toBe('Backyard mic')
    })

    it('supports multiple RTSP sources', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream1', label: '' })
      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.200:554/stream2', label: '' })

      const rtspSources = wrapper.vm.settings.audio.sources.filter(s => s.type === 'rtsp')
      expect(rtspSources).toHaveLength(2)
    })

    it('edits source label and URL', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream', label: 'Old label' })
      const sourceId = wrapper.vm.settings.audio.sources.find(s => s.type === 'rtsp').id

      wrapper.vm.handleStreamSave({
        id: sourceId,
        updates: { url: 'rtsp://192.168.1.200:554/new', label: 'New label' },
      })

      const updated = wrapper.vm.settings.audio.sources.find(s => s.id === sourceId)
      expect(updated.url).toBe('rtsp://192.168.1.200:554/new')
      expect(updated.label).toBe('New label')
    })

    it('deletes source by id', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream', label: '' })
      const sourceId = wrapper.vm.settings.audio.sources.find(s => s.type === 'rtsp').id

      wrapper.vm.handleStreamDelete(sourceId)

      expect(wrapper.vm.settings.audio.sources.find(s => s.id === sourceId)).toBeUndefined()
    })

    it('deletes one RTSP source without affecting others', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream1', label: '' })
      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.200:554/stream2', label: '' })

      const sources = wrapper.vm.settings.audio.sources
      const firstRtsp = sources.find(s => s.url === 'rtsp://192.168.1.100:554/stream1')

      wrapper.vm.handleStreamDelete(firstRtsp.id)

      const remaining = wrapper.vm.settings.audio.sources.filter(s => s.type === 'rtsp')
      expect(remaining).toHaveLength(1)
      expect(remaining[0].url).toBe('rtsp://192.168.1.200:554/stream2')
    })

    it('increments next_source_id when adding sources', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.settings.audio.next_source_id).toBe(1)

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.100:554/stream1', label: '' })
      expect(wrapper.vm.settings.audio.next_source_id).toBe(2)

      addSource(wrapper, { type: 'rtsp', url: 'rtsp://192.168.1.200:554/stream2', label: '' })
      expect(wrapper.vm.settings.audio.next_source_id).toBe(3)
    })
  })

  describe('Model Type Selection', () => {
    it('shows model type selector with correct options', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const trigger = wrapper.find('button#modelType')
      expect(trigger.exists()).toBe(true)

      const options = [...trigger.element.parentElement.querySelectorAll('li[role="option"]')]
      expect(options).toHaveLength(2)
      expect(options[0].textContent).toContain('v2.4')
      expect(options[1].textContent).toContain('v3.1')
    })

    it('changing model type marks hasUnsavedChanges', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.hasUnsavedChanges).toBe(false)

      wrapper.vm.settings.model.type = 'birdnet_v3'
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.hasUnsavedChanges).toBe(true)
    })

    it('saves V3 model change and waits for restart', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved. Restart services to apply all changes.',
          changes: { full_restart_required: true }
        }
      })

      // Switch to V3 model
      wrapper.vm.settings.model.type = 'birdnet_v3'
      await wrapper.vm.$nextTick()

      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith(
        '/settings',
        expect.objectContaining({
          model: expect.objectContaining({ type: 'birdnet_v3' })
        })
      )
      expect(mockRequestRestart).toHaveBeenCalled()
      expect(mockWaitForRestart).toHaveBeenCalledWith(expect.objectContaining({
        autoReload: true,
        message: 'Settings saved — restarting services to apply'
      }))
    })

    it('saves non-model changes without waiting for restart', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({ data: { status: 'updated' } })

      // Change a non-model setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith(
        '/settings',
        expect.objectContaining({
          location: expect.objectContaining({ latitude: 50.0 })
        })
      )
      expect(mockApi.post).not.toHaveBeenCalled()
      expect(mockWaitForRestart).not.toHaveBeenCalled()
    })

    it('reloads species names after saving bird name language changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(mockApi.get.mock.calls.filter(call => call[0] === '/species/available')).toHaveLength(1)

      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved. Changes applied immediately.',
          changes: {
            changed_paths: ['display.bird_name_language'],
            full_restart_required: false
          }
        }
      })

      wrapper.vm.settings.display = { bird_name_language: 'de' }
      await wrapper.vm.$nextTick()

      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockApi.get.mock.calls.filter(call => call[0] === '/species/available')).toHaveLength(2)
      expect(mockWaitForRestart).not.toHaveBeenCalled()
    })
  })

  describe('Unsaved Changes Detection', () => {
    it('hasUnsavedChanges is false after initial load', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
    })

    it('hasUnsavedChanges becomes true when settings are modified', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.hasUnsavedChanges).toBe(false)

      // Modify a setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.hasUnsavedChanges).toBe(true)
    })

    it('hasUnsavedChanges returns to false when reverted to original', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const originalLat = wrapper.vm.settings.location.latitude

      // Modify a setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.hasUnsavedChanges).toBe(true)

      // Revert to original
      wrapper.vm.settings.location.latitude = originalLat
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
    })

    it('hasUnsavedChanges becomes false after successful save', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Modify a setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.hasUnsavedChanges).toBe(true)

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({ data: { status: 'updated' } })

      // Save settings
      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
    })

    it('toggling recording normalization saves immediately without marking unsaved changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.settings.playback?.normalize ?? false).toBe(false)
      expect(wrapper.vm.hasUnsavedChanges).toBe(false)

      mockApi.put.mockResolvedValueOnce({ data: { success: true, normalize: true } })
      await wrapper.vm.togglePlaybackNormalize(true)
      await flushPromises()

      // Saved instantly via the dedicated endpoint — no full-settings PUT, no draft change
      expect(mockApi.put).toHaveBeenCalledWith('/settings/playback', { normalize: true })
      expect(wrapper.vm.settings.playback.normalize).toBe(true)
      expect(useSettings().settings.value.playback.normalize).toBe(true)
      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
    })

    it('togglePlaybackNormalize ignores re-entry while request is in flight', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      let resolveRequest
      mockApi.put = vi.fn().mockImplementationOnce(() => new Promise((resolve) => {
        resolveRequest = resolve
      }))

      const firstCall = wrapper.vm.togglePlaybackNormalize(true)
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.playbackNormalizeSaving).toBe(true)

      await wrapper.vm.togglePlaybackNormalize(true)
      expect(mockApi.put).toHaveBeenCalledTimes(1)

      resolveRequest({ data: { success: true } })
      await firstCall
      expect(wrapper.vm.playbackNormalizeSaving).toBe(false)
    })

    it('shows orange indicator on Save button when there are unsaved changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Find the Save button (contains "Save" text and is not the Reset button)
      const saveButton = wrapper.findAll('button').find(btn =>
        btn.text().includes('Save') && !btn.text().includes('Reset')
      )

      // Initially no indicator within Save button
      expect(saveButton.find('.bg-orange-500').exists()).toBe(false)

      // Modify a setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      // Now indicator should appear within Save button
      expect(saveButton.find('.bg-orange-500').exists()).toBe(true)
    })

    it('shows unsaved changes modal when showUnsavedModal is true', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Modal should not be visible initially
      expect(wrapper.findComponent({ name: 'UnsavedChangesModal' }).exists()).toBe(false)

      // Trigger modal
      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()

      // Modal should now be visible
      expect(wrapper.findComponent({ name: 'UnsavedChangesModal' }).exists()).toBe(true)
    })

    it('handleUnsavedDiscard closes modal', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Open modal
      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.showUnsavedModal).toBe(true)

      // Trigger discard
      wrapper.vm.handleUnsavedDiscard()
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.showUnsavedModal).toBe(false)
    })

    it('handleUnsavedCancel closes modal', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Open modal
      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.showUnsavedModal).toBe(true)

      // Trigger cancel
      wrapper.vm.handleUnsavedCancel()
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.showUnsavedModal).toBe(false)
    })

    it('handleUnsavedSave saves and closes modal on success', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({ data: { status: 'updated' } })

      // Set up modal state with a pending change
      wrapper.vm.settings.location.latitude = 50.0
      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()

      // Trigger save
      await wrapper.vm.handleUnsavedSave()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith('/settings', expect.any(Object))
      expect(wrapper.vm.showUnsavedModal).toBe(false)
      expect(mockApi.post).not.toHaveBeenCalled()
      expect(mockWaitForRestart).not.toHaveBeenCalled()
    })

    it('handleUnsavedSave triggers restart flow and blocks navigation when full restart is required', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved. Restart services to apply all changes.',
          changes: { full_restart_required: true }
        }
      })

      wrapper.vm.settings.model.type = 'birdnet_v3'
      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()

      await wrapper.vm.handleUnsavedSave()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith('/settings', expect.any(Object))
      expect(mockRequestRestart).toHaveBeenCalled()
      expect(mockWaitForRestart).toHaveBeenCalledWith(expect.objectContaining({
        autoReload: true,
        message: 'Settings saved — restarting services to apply'
      }))
      expect(wrapper.vm.showUnsavedModal).toBe(false)
    })

    it('handleUnsavedSave keeps modal open on validation failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Set up state that will fail validation (RTSP source without URL)
      wrapper.vm.settings.audio.sources.push({
        id: 'source_99', type: 'rtsp', url: '', label: 'Bad source', enabled: true
      })
      wrapper.vm.showUnsavedModal = true
      let navigationResolved = null
      wrapper.vm.navigationResolver = (value) => { navigationResolved = value }
      await wrapper.vm.$nextTick()

      // Trigger save (should fail validation)
      await wrapper.vm.handleUnsavedSave()
      await flushPromises()

      // Modal should stay open, navigation should NOT be resolved
      expect(wrapper.vm.showUnsavedModal).toBe(true)
      expect(navigationResolved).toBe(null)
      expect(wrapper.vm.settingsSaveError).toContain('requires a URL')
    })

    it('handleUnsavedSave keeps modal open on API failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Reset and mock API failure
      mockApi.put.mockReset()
      mockApi.put.mockRejectedValue(new Error('API error'))

      // Set up modal state with a pending change
      wrapper.vm.settings.location.latitude = 50.0
      wrapper.vm.showUnsavedModal = true
      let navigationResolved = null
      wrapper.vm.navigationResolver = (value) => { navigationResolved = value }
      await wrapper.vm.$nextTick()

      // Trigger save
      await wrapper.vm.handleUnsavedSave()
      await flushPromises()

      // Verify put was called and rejected
      expect(mockApi.put).toHaveBeenCalled()

      // Modal should stay open, navigation should NOT be resolved
      expect(wrapper.vm.showUnsavedModal).toBe(true)
      expect(navigationResolved).toBe(null)
      expect(wrapper.vm.settingsSaveError).toContain('Failed to save')
    })
  })

  describe('Quiet Hours', () => {
    const summary = (wrapper) => wrapper.find('[data-testid="quiet-hours-summary"]').text()
    const timeField = (wrapper, index) =>
      wrapper.findAllComponents({ name: 'AppTimeSelect' })[index].props('modelValue')

    it('renders inside the Detection section with the stored window', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(timeField(wrapper, 0)).toBe('22:00')
      expect(timeField(wrapper, 1)).toBe('06:00')
      expect(wrapper.vm.quietHours.enabled).toBe(false)
      expect(summary(wrapper)).toBe('Recording runs around the clock.')
    })

    it('toggling saves immediately via the schedule endpoint without marking unsaved changes', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: { success: true, quiet_hours: { enabled: true, start: '22:00', end: '06:00' } }
      })
      await wrapper.vm.toggleQuietHours(true)
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith('/settings/schedule', { quiet_hours: { enabled: true } })
      expect(wrapper.vm.settings.schedule.quiet_hours.enabled).toBe(true)
      expect(useSettings().settings.value.schedule.quiet_hours.enabled).toBe(true)
      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
      expect(summary(wrapper)).toContain('every day (8 h)')
      expect(summary(wrapper)).toContain('wrap past midnight')
    })

    it('saves a committed time change as the full start/end pair', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockResolvedValueOnce({
        data: { success: true, quiet_hours: { enabled: false, start: '21:30', end: '06:00' } }
      })
      wrapper.vm.quietHoursDraft.start = '21:30'
      await wrapper.vm.saveQuietHoursTime()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith('/settings/schedule', { quiet_hours: { start: '21:30', end: '06:00' } })
      expect(wrapper.vm.settings.schedule.quiet_hours.start).toBe('21:30')
      expect(timeField(wrapper, 0)).toBe('21:30')
    })

    it('does not save an unchanged pair', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      await wrapper.vm.saveQuietHoursTime()
      expect(mockApi.put).not.toHaveBeenCalled()
    })

    it('flags an equal pair inline, keeps the draft and saves nothing', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.quietHoursDraft.end = '22:00'
      await wrapper.vm.saveQuietHoursTime()
      await flushPromises()

      expect(mockApi.put).not.toHaveBeenCalled()
      expect(wrapper.vm.quietHoursDraft.end).toBe('22:00')
      expect(wrapper.find('[data-testid="quiet-hours-error"]').text()).toBe('Start and end must differ — not saved yet.')
      expect(wrapper.find('[data-testid="quiet-hours-summary"]').exists()).toBe(false)
      expect(wrapper.vm.settings.schedule.quiet_hours.end).toBe('06:00')
    })

    it('lets a swap through: the pair saves once both fields are valid again', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // 22:00–06:00 → 06:00–22:00 necessarily passes through 06:00–06:00
      wrapper.vm.quietHoursDraft.start = '06:00'
      await wrapper.vm.saveQuietHoursTime()
      expect(mockApi.put).not.toHaveBeenCalled()

      mockApi.put.mockResolvedValueOnce({
        data: { success: true, quiet_hours: { enabled: false, start: '06:00', end: '22:00' } }
      })
      wrapper.vm.quietHoursDraft.end = '22:00'
      await wrapper.vm.saveQuietHoursTime()
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledTimes(1)
      expect(mockApi.put).toHaveBeenCalledWith('/settings/schedule', { quiet_hours: { start: '06:00', end: '22:00' } })
      expect(wrapper.vm.settings.schedule.quiet_hours).toEqual({ enabled: false, start: '06:00', end: '22:00' })
      expect(wrapper.find('[data-testid="quiet-hours-error"]').exists()).toBe(false)
    })

    it('flags a cleared field inline without saving', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.quietHoursDraft.start = ''
      await wrapper.vm.saveQuietHoursTime()

      expect(mockApi.put).not.toHaveBeenCalled()
      expect(wrapper.find('[data-testid="quiet-hours-error"]').text()).toContain('must both be set')
    })

    it('keeps a half-entered draft when the toggle saves', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.quietHoursDraft.start = '06:00'  // invalid pair, deliberately unsaved
      mockApi.put.mockResolvedValueOnce({
        data: { success: true, quiet_hours: { enabled: true, start: '22:00', end: '06:00' } }
      })
      await wrapper.vm.toggleQuietHours(true)
      await flushPromises()

      expect(wrapper.vm.quietHoursDraft.start).toBe('06:00')
    })

    it('reverts both inputs and surfaces the server error when the save is rejected', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockRejectedValueOnce({
        response: { data: { error: 'quiet_hours.start must be a time in HH:MM (24-hour) format' } }
      })
      wrapper.vm.quietHoursDraft.start = '23:15'
      await wrapper.vm.saveQuietHoursTime()
      await flushPromises()

      expect(wrapper.vm.quietHoursDraft.start).toBe('22:00')
      expect(wrapper.vm.quietHoursDraft.end).toBe('06:00')
      expect(wrapper.vm.settings.schedule.quiet_hours.start).toBe('22:00')
      expect(wrapper.vm.saveStatus.type).toBe('error')
      expect(wrapper.vm.saveStatus.message).toContain('HH:MM')
    })

    it('locks full-settings save paths while a quiet-hours request is pending, and vice versa', async () => {
      const wrapper = mountSettings()
      await flushPromises()
      const saveButton = () => wrapper.findAll('button').find(b => b.text().startsWith('Save'))

      let resolveRequest
      mockApi.put.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve }))
      const pending = wrapper.vm.toggleQuietHours(true)
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.quietHoursSaving).toBe(true)
      expect(saveButton().attributes('disabled')).toBeDefined()

      wrapper.vm.showUnsavedModal = true
      await wrapper.vm.$nextTick()
      const unsavedModal = wrapper.findComponent({ name: 'UnsavedChangesModal' })
      expect(unsavedModal.props('saving')).toBe(true)

      // Defend against direct/programmatic callers as well as the disabled UI.
      await wrapper.vm.handleUnsavedSave()
      expect(mockApi.put).toHaveBeenCalledTimes(1)
      expect(wrapper.vm.showUnsavedModal).toBe(true)

      resolveRequest({ data: { success: true, quiet_hours: { enabled: true, start: '22:00', end: '06:00' } } })
      await pending
      await wrapper.vm.$nextTick()
      expect(saveButton().attributes('disabled')).toBeUndefined()
      expect(unsavedModal.props('saving')).toBe(false)

      // Main Save in flight → quiet-hours controls locked
      wrapper.vm.loading = true
      await wrapper.vm.$nextTick()
      expect(wrapper.find('#quietHoursStart').attributes('disabled')).toBeDefined()
      expect(wrapper.find('[aria-labelledby="quietHoursLabel"]').attributes('disabled')).toBeDefined()
    })

    it('gives the switch an accessible name from its label', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const toggle = wrapper.find('[role="switch"][aria-labelledby="quietHoursLabel"]')
      expect(toggle.exists()).toBe(true)
      expect(wrapper.find('#quietHoursLabel').text()).toBe('Quiet Hours')
    })

    it('falls back to defaults when the settings payload predates the schedule section', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/settings') {
          const legacy = createMockSettings()
          delete legacy.schedule
          return Promise.resolve({ data: legacy })
        }
        return defaultGetResponse(url)
      })
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.quietHours).toEqual({ enabled: false, start: '22:00', end: '06:00' })

      mockApi.put.mockResolvedValueOnce({
        data: { success: true, quiet_hours: { enabled: true, start: '22:00', end: '06:00' } }
      })
      await wrapper.vm.toggleQuietHours(true)
      await flushPromises()

      expect(wrapper.vm.settings.schedule.quiet_hours.enabled).toBe(true)
    })
  })

  describe('Notifications Section', () => {
    it('displays Notifications section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Notifications')
    })

    it('shows notification sub-settings when section is expanded', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.notifications = {
        apprise_urls: [],
        every_detection: true,
        rate_limit_seconds: 300,
        first_of_day: true,
        rare_species: false,
        rare_threshold: 3,
        rare_window_days: 7
      }
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('Add')
      expect(wrapper.text()).toContain('Every Detection')
      expect(wrapper.text()).toContain('First of Day')
      expect(wrapper.text()).toContain('Rare Species')
    })

    it('handleAddNotificationUrl adds URL, closes modal, and saves immediately', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.notifications = {
        apprise_urls: [],
        every_detection: true,
        rate_limit_seconds: 300,
        first_of_day: true,
        rare_species: false,
        rare_threshold: 3,
        rare_window_days: 7
      }
      wrapper.vm.showAddNotificationModal = true
      await wrapper.vm.$nextTick()

      mockApi.put = vi.fn().mockResolvedValue({ data: { success: true } })

      wrapper.vm.handleAddNotificationUrl('tgram://bot/chat')
      await flushPromises()

      expect(wrapper.vm.settings.notifications.apprise_urls).toContain('tgram://bot/chat')
      expect(wrapper.vm.showAddNotificationModal).toBe(false)
      expect(mockApi.put).toHaveBeenCalledWith('/settings/notifications', expect.objectContaining({
        apprise_urls: ['tgram://bot/chat']
      }))
    })

    it('openEditNotification then delete triggers confirm and removes URL on confirm', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.notifications = {
        apprise_urls: ['tgram://bot/chat', 'discord://webhook'],
        every_detection: true
      }
      await wrapper.vm.$nextTick()

      // Open the edit modal for the first service
      wrapper.vm.openEditNotification(0)
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.showAddNotificationModal).toBe(true)

      mockApi.put = vi.fn().mockResolvedValue({ data: { success: true } })

      // Delete from modal closes modal and opens confirm
      wrapper.vm.handleDeleteNotificationFromModal()
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.showAddNotificationModal).toBe(false)
      expect(wrapper.vm.confirmRemoveIndex).toBe(0)

      // Confirm the removal
      wrapper.vm.confirmRemoveAppriseUrl()
      await wrapper.vm.$nextTick()
      await flushPromises()

      expect(wrapper.vm.settings.notifications.apprise_urls).toEqual(['discord://webhook'])
      expect(mockApi.put).toHaveBeenCalledWith('/settings/notifications', expect.objectContaining({
        apprise_urls: ['discord://webhook']
      }))
    })

    it('notification settings changes do NOT mark hasUnsavedChanges', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.vm.hasUnsavedChanges).toBe(false)

      wrapper.vm.settings.notifications.apprise_urls = ['tgram://bot/chat']
      await wrapper.vm.$nextTick()

      // Notification settings are auto-saved, so they should NOT trigger unsaved changes
      expect(wrapper.vm.hasUnsavedChanges).toBe(false)
    })

    it('toggleNotificationSetting saves immediately', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put = vi.fn().mockResolvedValue({ data: { success: true } })

      wrapper.vm.toggleNotificationSetting('every_detection')
      await flushPromises()

      expect(mockApi.put).toHaveBeenCalledWith('/settings/notifications', expect.any(Object))
      expect(useSettings().settings.value.notifications.every_detection).toBe(false)
    })

    it('notification save sequence ignores stale success and rolls back to latest confirmed on failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      let resolveFirstSave
      const firstSavePromise = new Promise((resolve) => {
        resolveFirstSave = resolve
      })

      mockApi.put = vi.fn()
        .mockImplementationOnce(() => firstSavePromise) // seq 1 (pending)
        .mockResolvedValueOnce({ data: { success: true } }) // seq 2 (latest success)
        .mockRejectedValueOnce(new Error('save failed')) // seq 3 (latest failure)

      // seq 1: toggle true -> false
      wrapper.vm.toggleNotificationSetting('every_detection')
      await wrapper.vm.$nextTick()

      // seq 2: toggle false -> true
      wrapper.vm.toggleNotificationSetting('every_detection')
      await flushPromises()

      // Complete stale seq 1 after seq 2 already applied
      resolveFirstSave({ data: { success: true } })
      await flushPromises()

      // seq 3: toggle true -> false, then fail -> rollback to confirmed true
      wrapper.vm.toggleNotificationSetting('every_detection')
      await flushPromises()

      expect(wrapper.vm.settings.notifications.every_detection).toBe(true)
    })
  })

  describe('Immediate Toggle Guards', () => {
    it('keeps successful access autosaves in the warm settings cache', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(useSettings().settings.value.access.charts_public).toBe(false)

      await wrapper.vm.toggleFeatureAccess('charts_public')

      expect(wrapper.vm.settings.access.charts_public).toBe(true)
      expect(useSettings().settings.value.access.charts_public).toBe(true)
    })

    it('toggleUpdateChannel ignores re-entry while request is in flight', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.updates = { channel: 'release' }
      let resolveRequest
      mockApi.put = vi.fn().mockImplementationOnce(() => new Promise((resolve) => {
        resolveRequest = resolve
      }))

      const firstCall = wrapper.vm.toggleUpdateChannel()
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.updateChannelSaving).toBe(true)

      await wrapper.vm.toggleUpdateChannel()
      expect(mockApi.put).toHaveBeenCalledTimes(1)

      resolveRequest({ data: { success: true } })
      await firstCall
      expect(wrapper.vm.updateChannelSaving).toBe(false)
      expect(useSettings().settings.value.updates.channel).toBe('latest')
    })

    it('toggleMetricUnits ignores re-entry while request is in flight', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.display = { use_metric_units: true }
      let resolveRequest
      mockApi.put = vi.fn().mockImplementationOnce(() => new Promise((resolve) => {
        resolveRequest = resolve
      }))

      const firstCall = wrapper.vm.toggleMetricUnits()
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.metricUnitsSaving).toBe(true)

      await wrapper.vm.toggleMetricUnits()
      expect(mockApi.put).toHaveBeenCalledTimes(1)

      resolveRequest({ data: { success: true } })
      await firstCall
      expect(wrapper.vm.metricUnitsSaving).toBe(false)
      expect(useSettings().settings.value.display.use_metric_units).toBe(false)
    })

    it('toggleTimeFormat syncs settings.value so a later full save preserves it', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Force a known starting state so the toggle direction is deterministic
      // (detection-based default varies by test runner locale).
      wrapper.vm.timeFormatSettings.setTimeFormat('12h')
      wrapper.vm.settings.display.time_format = '12h'
      mockApi.put.mockResolvedValueOnce({ data: { success: true, time_format: '24h' } })

      await wrapper.vm.toggleTimeFormat()
      await flushPromises()

      // The PUT to the dedicated endpoint happened with the new value
      expect(mockApi.put).toHaveBeenCalledWith('/settings/time-format', { time_format: '24h' })
      // settings.value is now in sync — a subsequent full PUT /settings sends '24h', not the stale '12h'
      expect(wrapper.vm.settings.display.time_format).toBe('24h')
      expect(useSettings().settings.value.display.time_format).toBe('24h')
    })
  })

  describe('Recorder Status & Error Display', () => {
    const { RUNNING, DEGRADED, STOPPED, PAUSED } = RECORDER_STATES

    // Helper: build a multi-source status object matching the backend shape
    const makeStatus = (state, sources = {}) => ({ state, sources })

    const makeSource = (label, sourceState, lastError = null) => ({
      label,
      type: 'rtsp',
      state: sourceState,
      is_healthy: sourceState === RUNNING,
      consecutive_failures: sourceState === RUNNING ? 0 : 5,
      last_error_message: lastError,
      last_error_time: lastError ? Date.now() / 1000 : null,
      last_success_time: Date.now() / 1000
    })

    it('does not show error details when all sources are running', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = makeStatus(RUNNING, {
        source_0: makeSource('Microphone', RUNNING)
      })
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.showRecorderError).toBe(false)
      expect(wrapper.find('details').exists()).toBe(false)
    })

    it('shows error details when a source is degraded with an error message', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = makeStatus(DEGRADED, {
        source_0: makeSource('Microphone', RUNNING),
        source_1: makeSource('Backyard Cam', DEGRADED, 'Connection timed out')
      })
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.showRecorderError).toBe(true)
      expect(wrapper.vm.sourceErrors).toHaveLength(1)
      expect(wrapper.vm.sourceErrors[0]).toEqual({
        label: 'Backyard Cam',
        state: DEGRADED,
        message: 'Connection timed out'
      })
    })

    it('shows error details for multiple failing sources', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = makeStatus(STOPPED, {
        source_0: makeSource('Microphone', STOPPED, 'Device not found'),
        source_1: makeSource('Backyard Cam', DEGRADED, 'Connection refused')
      })
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.sourceErrors).toHaveLength(2)
      const labels = wrapper.vm.sourceErrors.map(e => e.label)
      expect(labels).toContain('Microphone')
      expect(labels).toContain('Backyard Cam')
    })

    it('hides error details when source has no error message', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = makeStatus(DEGRADED, {
        source_0: makeSource('Microphone', DEGRADED, null)
      })
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.showRecorderError).toBe(false)
    })

    it('shows correct status dot and label for each aggregate state', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Running
      wrapper.vm.recorderStatus = makeStatus(RUNNING, {
        source_0: makeSource('Mic', RUNNING)
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recorderStateLabel).toBe('Audio Healthy')
      expect(wrapper.vm.recorderDotClass).toContain('bg-green-500')

      // Degraded
      wrapper.vm.recorderStatus = makeStatus(DEGRADED, {
        source_0: makeSource('Mic', DEGRADED, 'err')
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recorderStateLabel).toBe('Audio Degraded')
      expect(wrapper.vm.recorderDotClass).toContain('bg-amber-500')

      // Stopped
      wrapper.vm.recorderStatus = makeStatus(STOPPED, {})
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recorderStateLabel).toBe('Audio Stopped')
      expect(wrapper.vm.recorderDotClass).toContain('bg-red-500')
    })

    it('shows a blue paused badge with the resume time and hides error details', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = {
        ...makeStatus(PAUSED, { source_0: makeSource('Mic', PAUSED) }),
        pause: { reason: 'quiet_hours', resumes_at: '2026-08-25T06:00' }
      }
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.recorderStateLabel).toMatch(/^Paused until /)
      expect(wrapper.vm.recorderStateLabel).toContain('6:00')
      expect(wrapper.vm.recorderDotClass).toBe('bg-blue-400')
      expect(wrapper.vm.recorderStateLabelClass).toBe('text-blue-600')
      expect(wrapper.vm.showRecorderError).toBe(false)
    })

    it('falls back to a plain paused label without a resume time', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = { ...makeStatus(PAUSED, {}), pause: null }
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.recorderStateLabel).toBe('Audio Paused')
    })

    it('reports a sourceless pause as paused, not stopped', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.recorderStatus = {
        ...makeStatus(PAUSED, {}),
        pause: { reason: 'no_sources', resumes_at: null }
      }
      await wrapper.vm.$nextTick()

      expect(wrapper.vm.recorderStateLabel).toBe('Audio Paused')
      expect(wrapper.vm.recorderDotClass).toBe('bg-blue-400')
      expect(wrapper.vm.showRecorderError).toBe(false)
    })

  })

  describe('HA Mode System Updates', () => {
    const haVersionInfo = {
      runtime_mode: 'ha',
      version: '0.6.3',
      current_commit: 'abc1234',
      current_branch: 'home_assistant'
    }

    it('shows Check for Updates button in HA mode', async () => {
      mockSystemUpdate.versionInfo.value = haVersionInfo
      const wrapper = mountSettings()
      await flushPromises()

      const buttons = wrapper.findAll('button')
      const checkButton = buttons.find(b => b.text().includes('Check for Updates'))
      expect(checkButton).toBeTruthy()
    })

    it('shows version transition subtitle in HA mode', async () => {
      mockSystemUpdate.versionInfo.value = haVersionInfo
      mockSystemUpdate.updateInfo.value = { current_version: '0.6.3', latest_version: '0.6.4' }
      mockSystemUpdate.updateAvailable.value = true
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('v0.6.3')
      expect(wrapper.text()).toContain('v0.6.4')
    })
  })

})
