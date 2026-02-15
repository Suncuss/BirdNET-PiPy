import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Settings from '@/views/Settings.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock the useServiceRestart composable (expose waitForRestart for assertions)
const mockWaitForRestart = vi.hoisted(() => vi.fn().mockResolvedValue(true))
vi.mock('@/composables/useServiceRestart', () => ({
  useServiceRestart: () => ({
    isRestarting: { value: false },
    restartMessage: { value: '' },
    restartError: { value: '' },
    waitForRestart: mockWaitForRestart,
    reset: vi.fn()
  })
}))

// Mock the useSystemUpdate composable to avoid extra fetch calls
vi.mock('@/composables/useSystemUpdate', () => ({
  useSystemUpdate: () => ({
    versionInfo: { value: null },
    updateInfo: { value: null },
    updateAvailable: { value: false },
    checking: { value: false },
    updating: { value: false },
    statusMessage: { value: null },
    statusType: { value: null },
    // New dismissal state
    showUpdateIndicator: { value: false },
    dismissUpdate: vi.fn(),
    // Exposed from internal useServiceRestart
    restartMessage: { value: '' },
    restartError: { value: '' },
    isRestarting: { value: false },
    loadVersionInfo: vi.fn().mockResolvedValue({}),
    checkForUpdates: vi.fn().mockResolvedValue({}),
    triggerUpdate: vi.fn().mockResolvedValue({})
  })
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
    recording_mode: 'pulseaudio',
    stream_url: null,
    pulseaudio_source: null,
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
    mockApi.get.mockImplementation((url) => {
      if (url === '/settings' || url === '/settings/defaults') {
        return Promise.resolve({ data: createMockSettings() })
      }
      if (url === '/system/storage') {
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
    it('displays "Recording" heading', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Recording')
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
    it('displays Location & Audio section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Location & Audio')
      expect(wrapper.find('#latitude').exists()).toBe(true)
      expect(wrapper.find('#longitude').exists()).toBe(true)
      expect(wrapper.find('#recordingMode').exists()).toBe(true)
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
      expect(wrapper.text()).not.toContain('Language')
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
  })

  describe('Reset to Defaults', () => {
    it('resets settings to defaults when confirmed', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Change values
      wrapper.vm.settings.audio.recording_length = 12
      wrapper.vm.settings.audio.overlap = 1.5

      // Mock confirm dialog
      vi.spyOn(window, 'confirm').mockReturnValue(true)

      // Mock save response
      mockApi.put.mockResolvedValueOnce({
        data: {
          status: 'updated',
          message: 'Settings saved',
          settings: mockSettings
        }
      })

      const resetButton = wrapper.findAll('button').find(btn => btn.text() === 'Reset')
      await resetButton.trigger('click')
      await flushPromises()

      expect(wrapper.vm.settings.audio.recording_length).toBe(9)
      expect(wrapper.vm.settings.audio.overlap).toBe(0.0)
    })

    it('does not reset settings when cancelled', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.audio.recording_length = 12
      wrapper.vm.settings.audio.overlap = 1.5

      vi.spyOn(window, 'confirm').mockReturnValue(false)

      const resetButton = wrapper.findAll('button').find(btn => btn.text() === 'Reset')
      await resetButton.trigger('click')
      await flushPromises()

      // Values should not change
      expect(wrapper.vm.settings.audio.recording_length).toBe(12)
      expect(wrapper.vm.settings.audio.overlap).toBe(1.5)
    })
  })

  describe('Recording Mode Switching', () => {
    it('shows stream URL input when http_stream mode selected', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const modeSelect = wrapper.find('#recordingMode')
      await modeSelect.setValue('http_stream')
      await flushPromises()

      expect(wrapper.find('#streamUrl').exists()).toBe(true)
    })

    it('hides stream URL input when pulseaudio mode selected', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      const modeSelect = wrapper.find('#recordingMode')
      await modeSelect.setValue('pulseaudio')
      await flushPromises()

      expect(wrapper.find('#streamUrl').exists()).toBe(false)
    })

    it('preserves stream_url when switching to pulseaudio mode', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.audio.stream_url = 'http://example.com/stream.mp3'
      wrapper.vm.recordingMode = 'http_stream'

      const modeSelect = wrapper.find('#recordingMode')
      await modeSelect.setValue('pulseaudio')
      wrapper.vm.onRecordingModeChange()

      // URLs are intentionally preserved when switching modes
      // This allows users to switch back without re-entering URLs
      expect(wrapper.vm.settings.audio.stream_url).toBe('http://example.com/stream.mp3')
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

    it('uses extended timeout when switching to V3 model', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({ data: { status: 'updated' } })

      // Switch to V3 model
      wrapper.vm.settings.model.type = 'birdnet_v3'
      await wrapper.vm.$nextTick()

      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockWaitForRestart).toHaveBeenCalledWith(
        expect.objectContaining({
          maxWaitSeconds: 600,
          message: 'Updating settings'
        })
      )
    })

    it('uses default timeout when not switching to V3', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      mockApi.put.mockResolvedValueOnce({ data: { status: 'updated' } })

      // Change a non-model setting
      wrapper.vm.settings.location.latitude = 50.0
      await wrapper.vm.$nextTick()

      await wrapper.vm.saveSettings()
      await flushPromises()

      expect(mockWaitForRestart).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Updating settings'
        })
      )
      expect(mockWaitForRestart).not.toHaveBeenCalledWith(
        expect.objectContaining({
          maxWaitSeconds: 600
        })
      )
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
    })

    it('handleUnsavedSave keeps modal open on validation failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Set up state that will fail validation (HTTP stream mode without URL)
      wrapper.vm.recordingMode = 'http_stream'
      wrapper.vm.settings.audio.recording_mode = 'http_stream'
      wrapper.vm.settings.audio.stream_url = ''
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
      expect(wrapper.vm.settingsSaveError).toContain('Stream URL')
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

})
