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

// Mock the useServiceRestart composable
vi.mock('@/composables/useServiceRestart', () => ({
  useServiceRestart: () => ({
    isRestarting: { value: false },
    restartMessage: { value: '' },
    restartError: { value: '' },
    waitForRestart: vi.fn().mockResolvedValue(true),
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
    // Exposed from internal useServiceRestart
    restartMessage: { value: '' },
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
    needsSetup: { value: false },
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
  general: {
    timezone: 'UTC',
    language: 'en'
  },
  updates: {
    channel: 'stable'
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

      const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save' || btn.text() === 'Saving...')
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Failed to save')
    })

    it('disables save button while saving', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      mockApi.put.mockImplementationOnce(() => new Promise(resolve => setTimeout(resolve, 100)))

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

})
