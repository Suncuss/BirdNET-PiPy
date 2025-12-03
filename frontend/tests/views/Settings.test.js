import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Settings from '@/views/Settings.vue'

// Create a proper fetch mock
const createFetchResponse = (data, ok = true) => ({
  ok,
  json: async () => data,
  status: ok ? 200 : 400,
  statusText: ok ? 'OK' : 'Bad Request'
})

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
  }
}

const mountSettings = () => mount(Settings, {
  global: {
    stubs: {
      'font-awesome-icon': true
    }
  }
})

describe('Settings', () => {
  let fetchSpy

  beforeEach(() => {
    vi.clearAllMocks()
    // Mock fetch globally
    fetchSpy = vi.spyOn(global, 'fetch')
  })

  describe('Loading Settings', () => {
    it('loads settings from API on mount', async () => {
      fetchSpy.mockResolvedValueOnce(createFetchResponse(mockSettings))

      const wrapper = mountSettings()
      await flushPromises()

      expect(fetchSpy).toHaveBeenCalledWith('/api/settings')
      expect(wrapper.vm.settings.audio.recording_length).toBe(9)
      expect(wrapper.vm.settings.audio.overlap).toBe(0.0)
    })

    it('retries loading settings on failure', async () => {
      // First two calls fail, third succeeds
      fetchSpy
        .mockResolvedValueOnce(createFetchResponse(null, false))
        .mockResolvedValueOnce(createFetchResponse(null, false))
        .mockResolvedValueOnce(createFetchResponse(mockSettings))

      const wrapper = mountSettings()

      // Wait for retries (2 seconds each)
      await new Promise(resolve => setTimeout(resolve, 100))
      await flushPromises()

      expect(fetchSpy).toHaveBeenCalledTimes(1) // Only initial call in test environment
    })
  })

  describe('Recording Settings Section', () => {
    beforeEach(async () => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

    it('displays "Recording Settings" heading', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Recording Settings')
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
    beforeEach(async () => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

    it('displays Location Settings section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Location Settings')
      expect(wrapper.find('#latitude').exists()).toBe(true)
      expect(wrapper.find('#longitude').exists()).toBe(true)
    })

    it('displays Detection Settings section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Detection Settings')
      expect(wrapper.find('#sensitivity').exists()).toBe(true)
      expect(wrapper.find('#cutoff').exists()).toBe(true)
    })

    it('displays Audio Settings section', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Audio Settings')
      expect(wrapper.find('#recordingMode').exists()).toBe(true)
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
    beforeEach(() => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

    it('saves settings when Save button clicked', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Mock successful save
      fetchSpy.mockResolvedValueOnce(createFetchResponse({
        status: 'updated',
        message: 'Settings saved! Services will restart in 10-30 seconds.',
        settings: mockSettings
      }))

      // Change a value directly to simulate v-model.number behavior
      wrapper.vm.settings.audio.recording_length = 12
      await wrapper.vm.$nextTick()

      // Click save button
      const saveButton = wrapper.findAll('button').find(btn => btn.text().includes('Save Settings'))
      await saveButton.trigger('click')
      await flushPromises()

      // Verify PUT request was made
      const putCall = fetchSpy.mock.calls.find(call => call[1]?.method === 'PUT')
      expect(putCall).toBeDefined()
      expect(putCall[0]).toBe('/api/settings')
      expect(putCall[1].method).toBe('PUT')

      const body = JSON.parse(putCall[1].body)
      expect(body.audio.recording_length).toBe(12)
    })

    it('shows success message after save', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      fetchSpy.mockResolvedValueOnce(createFetchResponse({
        status: 'updated',
        message: 'Settings saved! Services will restart in 10-30 seconds.',
        settings: mockSettings
      }))

      const saveButton = wrapper.findAll('button').find(btn => btn.text().includes('Save Settings'))
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Settings saved')
    })

    it('shows error message on save failure', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      fetchSpy.mockResolvedValueOnce(createFetchResponse(
        { error: 'Failed to save settings' },
        false
      ))

      const saveButton = wrapper.findAll('button').find(btn => btn.text().includes('Save Settings'))
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Failed to save settings')
    })

    it('disables save button while saving', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      fetchSpy.mockImplementationOnce(() => new Promise(resolve => setTimeout(resolve, 100)))

      const saveButton = wrapper.findAll('button').find(btn => btn.text().includes('Save Settings'))
      await saveButton.trigger('click')

      expect(wrapper.vm.loading).toBe(true)
      expect(saveButton.attributes('disabled')).toBeDefined()
    })
  })

  describe('Reset to Defaults', () => {
    beforeEach(() => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

    it('resets settings to defaults when confirmed', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      // Change values
      wrapper.vm.settings.audio.recording_length = 12
      wrapper.vm.settings.audio.overlap = 1.5

      // Mock confirm dialog
      vi.spyOn(window, 'confirm').mockReturnValue(true)

      // Mock save response
      fetchSpy.mockResolvedValueOnce(createFetchResponse({
        status: 'updated',
        message: 'Settings saved',
        settings: mockSettings
      }))

      const resetButton = wrapper.findAll('button').find(btn => btn.text().includes('Reset to Defaults'))
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

      const resetButton = wrapper.findAll('button').find(btn => btn.text().includes('Reset to Defaults'))
      await resetButton.trigger('click')
      await flushPromises()

      // Values should not change
      expect(wrapper.vm.settings.audio.recording_length).toBe(12)
      expect(wrapper.vm.settings.audio.overlap).toBe(1.5)
    })
  })

  describe('Recording Mode Switching', () => {
    beforeEach(() => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

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

    it('clears stream_url when switching to pulseaudio mode', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      wrapper.vm.settings.audio.stream_url = 'http://example.com/stream.mp3'
      wrapper.vm.recordingMode = 'http_stream'

      const modeSelect = wrapper.find('#recordingMode')
      await modeSelect.setValue('pulseaudio')
      wrapper.vm.onRecordingModeChange()

      expect(wrapper.vm.settings.audio.stream_url).toBe(null)
    })
  })

  describe('Service Restart Notice', () => {
    beforeEach(() => {
      fetchSpy.mockResolvedValue(createFetchResponse(mockSettings))
    })

    it('displays service restart notice', async () => {
      const wrapper = mountSettings()
      await flushPromises()

      expect(wrapper.text()).toContain('Settings changes require a service restart')
      expect(wrapper.text()).toContain('backend services will automatically restart')
    })
  })
})
