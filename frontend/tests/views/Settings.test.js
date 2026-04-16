import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Settings from '@/views/Settings.vue'
import { RECORDER_STATES } from '@/utils/recorderStates'

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
  default: mockApi
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
vi.mock('@/composables/useServiceRestart', () => ({
  requestRestart: mockRequestRestart,
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

// Mock the useAuth composable to avoid extra fetch calls
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    authStatus: { value: { authEnabled: false, setupComplete: true, authenticated: false } },
    loading: { value: false },
    error: { value: '' },
    needsLogin: { value: false },
    isAuthenticated: { value: true },
    checkAuthStatus: vi.fn().mockResolvedValue(undefined),
    login: vi.fn().mockResolvedValue(true),
    logout: vi.fn().mockResolvedValue(undefined),
    setup: vi.fn().mockResolvedValue(true),
    toggleAuth: vi.fn().mockResolvedValue(true),
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
    bird_name_language: 'en',
    use_metric_units: true
  },
  updates: {
    channel: 'release'
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

const mountSettings = () => mount(Settings, {
  global: {
    stubs: {
      'font-awesome-icon': true
    }
  }
})

describe('Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
        return Promise.resolve({ data: {} })
      }
      return Promise.resolve({ data: {} })
    })
  })

  describe('Loading Settings', () => {
    it('loads settings from API on mount', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(mockApi.get).toHaveBeenCalledWith('/settings')
      expect(wrapper.vm.settings.audio.recording_length).toBe(9)
      expect(wrapper.vm.settings.audio.overlap).toBe(0.0)
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

    it('initializes socket.io with the base-path-aware socket.io path', async () => {
      mountSettings()
      await flushPromises()

      expect(ioMock).toHaveBeenCalledWith({ path: '/socket.io' })
    })

    it('falls back to recorder status REST call when the socket connection fails', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(socketHandlers.connect_error).toBeTypeOf('function')

      socketHandlers.connect_error(new Error('origin mismatch'))
      await flushPromises()

      const recorderStatusCalls = mockApi.get.mock.calls
        .filter(([url]) => url === '/recorder/status')
      expect(recorderStatusCalls).toHaveLength(2)

      wrapper.unmount()
    })

    it('displays recording settings within Detection section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Chunk Length')
    })

    it('shows recording length dropdown with correct options', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const select = wrapper.find('#recordingLength')
      expect(select.exists()).toBe(true)

      const options = select.findAll('option')
      expect(options).toHaveLength(3)
      expect(options[0].attributes('value')).toBe('9')
      expect(options[1].attributes('value')).toBe('12')
      expect(options[2].attributes('value')).toBe('15')
      expect(options[0].text()).toBe('9 seconds')
      expect(options[1].text()).toBe('12 seconds')
      expect(options[2].text()).toBe('15 seconds')
    })

    it('shows overlap dropdown with correct options', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const select = wrapper.find('#overlap')
      expect(select.exists()).toBe(true)

      const options = select.findAll('option')
      expect(options).toHaveLength(6)
      expect(options[0].attributes('value')).toBe('0')
      expect(options[1].attributes('value')).toBe('0.5')
      expect(options[2].attributes('value')).toBe('1')
      expect(options[3].attributes('value')).toBe('1.5')
      expect(options[4].attributes('value')).toBe('2')
      expect(options[5].attributes('value')).toBe('2.5')
    })

    it('displays current recording_length value', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const select = wrapper.find('#recordingLength')
      expect(select.element.value).toBe('9')
    })

    it('displays current overlap value', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const select = wrapper.find('#overlap')
      expect(select.element.value).toBe('0')
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

      const select = wrapper.find('#modelType')
      expect(select.exists()).toBe(true)

      const options = select.findAll('option')
      expect(options).toHaveLength(2)
      expect(options[0].attributes('value')).toBe('birdnet')
      expect(options[1].attributes('value')).toBe('birdnet_v3')
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
        message: 'Applying settings changes'
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
        message: 'Applying settings changes'
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
    })
  })

  describe('Recorder Status & Error Display', () => {
    const { RUNNING, DEGRADED, STOPPED } = RECORDER_STATES

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
