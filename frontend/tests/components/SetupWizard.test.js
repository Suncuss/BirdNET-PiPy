import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import SetupWizard from '@/components/SetupWizard.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock the useServiceRestart composable
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

// Mock the useAppStatus composable
vi.mock('@/composables/useAppStatus', () => ({
  useAppStatus: () => ({
    locationConfigured: { value: null },
    isRestarting: { value: false },
    setLocationConfigured: vi.fn(),
    setRestarting: vi.fn(),
    isReady: vi.fn(() => false)
  })
}))

describe('SetupWizard', () => {
  let fetchMock

  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock = vi.fn()
    global.fetch = fetchMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountWizard = (props = {}) => mount(SetupWizard, {
    props: {
      isVisible: true,
      ...props
    }
  })

  const goToStep2 = async (wrapper) => {
    await wrapper.find('#latitude').setValue(42.47)
    await wrapper.find('#longitude').setValue(-76.45)
    const nextButton = wrapper.findAll('button').find(b => b.text() === 'Next')
    await nextButton.trigger('click')
  }

  describe('Step 1: Location', () => {
    it('renders step 1 when visible', () => {
      const wrapper = mountWizard()
      expect(wrapper.text()).toContain('Set Your Location')
    })

    it('does not render when isVisible is false', () => {
      const wrapper = mountWizard({ isVisible: false })
      expect(wrapper.text()).not.toContain('Set Your Location')
    })

    it('shows search input and coordinate fields', () => {
      const wrapper = mountWizard()
      expect(wrapper.find('input[placeholder*="City"]').exists()).toBe(true)
      expect(wrapper.find('#latitude').exists()).toBe(true)
      expect(wrapper.find('#longitude').exists()).toBe(true)
      expect(wrapper.text()).toContain('or enter coordinates manually')
    })

    it('enables Next button when valid coordinates are entered', async () => {
      const wrapper = mountWizard()

      await wrapper.find('#latitude').setValue(42.47)
      await wrapper.find('#longitude').setValue(-76.45)

      const nextButton = wrapper.findAll('button').find(b => b.text() === 'Next')
      expect(nextButton.attributes('disabled')).toBeUndefined()
    })

    it('disables Next button when coordinates are invalid', async () => {
      const wrapper = mountWizard()

      await wrapper.find('#latitude').setValue(999)
      await wrapper.find('#longitude').setValue(-76.45)

      const nextButton = wrapper.findAll('button').find(b => b.text() === 'Next')
      expect(nextButton.attributes('disabled')).toBeDefined()
    })

    it('displays selected location for valid coordinates including zero', async () => {
      const wrapper = mountWizard()

      await wrapper.find('#latitude').setValue(0)
      await wrapper.find('#longitude').setValue(0)

      expect(wrapper.text()).toContain('Selected:')
      expect(wrapper.text()).toContain('0.00')
    })

    it('shows error when address search returns no results', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([])
      })

      const wrapper = mountWizard()
      await wrapper.find('input[placeholder*="City"]').setValue('NonexistentPlace12345')

      const searchButton = wrapper.findAll('button')[0]
      await searchButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('No results found')
    })

    it('advances to step 2 on Next click', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      expect(wrapper.text()).toContain('Audio Source')
    })
  })

  describe('Step 2: Audio Source', () => {
    it('shows audio source options', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      expect(wrapper.text()).toContain('Microphone')
      expect(wrapper.text()).toContain('Use a USB or built-in microphone')
      expect(wrapper.text()).toContain('Network Stream')
      expect(wrapper.text()).toContain('RTSP')
    })

    it('defaults to microphone selection', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const micCard = wrapper.findAll('button').find(b => b.text().includes('Microphone'))
      expect(micCard.classes()).toContain('border-green-500')
    })

    it('shows RTSP fields when Network Stream is selected', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const streamCard = wrapper.findAll('button').find(b => b.text().includes('Network Stream'))
      await streamCard.trigger('click')

      expect(wrapper.find('#rtsp-url').exists()).toBe(true)
      expect(wrapper.find('#rtsp-label').exists()).toBe(true)
    })

    it('navigates back to step 1 on Back click', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const backButton = wrapper.findAll('button').find(b => b.text() === 'Back')
      await backButton.trigger('click')

      expect(wrapper.text()).toContain('Set Your Location')
    })

    it('shows footer hint about adding more sources', async () => {
      const wrapper = mountWizard()
      await goToStep2(wrapper)

      expect(wrapper.text()).toContain('You can add more audio sources later in Settings')
    })
  })

  describe('Save Flow', () => {
    it('saves location and creates mic source on fresh install', async () => {
      let savedSettings = null
      mockApi.get.mockResolvedValueOnce({
        data: {
          location: { latitude: 0, longitude: 0, configured: false },
          audio: {
            sources: [],
            next_source_id: 0
          }
        }
      })
      mockApi.put.mockImplementationOnce((url, settings) => {
        savedSettings = settings
        return Promise.resolve({
          data: {
            settings: { location: { configured: true, timezone: 'America/New_York' } },
            changes: { full_restart_required: true }
          }
        })
      })

      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const finishButton = wrapper.findAll('button').find(b => b.text() === 'Finish')
      await finishButton.trigger('click')
      await flushPromises()

      expect(savedSettings.location.latitude).toBe(42.47)
      expect(savedSettings.location.longitude).toBe(-76.45)
      expect(savedSettings.location.configured).toBe(true)

      expect(savedSettings.audio.sources).toHaveLength(1)
      expect(savedSettings.audio.sources[0].type).toBe('pulseaudio')
      expect(savedSettings.audio.sources[0].id).toBe('source_0')
      expect(savedSettings.audio.sources[0].enabled).toBe(true)
      expect(savedSettings.audio.next_source_id).toBe(1)

      expect(mockRequestRestart).toHaveBeenCalled()
      expect(mockWaitForRestart).toHaveBeenCalledWith(
        expect.objectContaining({
          autoReload: true,
          message: 'Applying settings'
        })
      )
    })

    it('saves RTSP source only (no mic) on fresh install', async () => {
      let savedSettings = null
      mockApi.get.mockResolvedValueOnce({
        data: {
          location: { latitude: 0, longitude: 0, configured: false },
          audio: {
            sources: [],
            next_source_id: 0
          }
        }
      })
      mockApi.post.mockResolvedValueOnce({ data: { success: true } })
      mockApi.put.mockImplementationOnce((url, settings) => {
        savedSettings = settings
        return Promise.resolve({
          data: {
            settings: { location: { configured: true, timezone: 'America/New_York' } },
            changes: { full_restart_required: true }
          }
        })
      })

      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const streamCard = wrapper.findAll('button').find(b => b.text().includes('Network Stream'))
      await streamCard.trigger('click')

      await wrapper.find('#rtsp-url').setValue('rtsp://192.168.1.100/stream')

      const finishButton = wrapper.findAll('button').find(b => b.text() === 'Finish')
      await finishButton.trigger('click')
      await flushPromises()

      expect(savedSettings.audio.sources).toHaveLength(1)
      const rtspSource = savedSettings.audio.sources[0]
      expect(rtspSource.type).toBe('rtsp')
      expect(rtspSource.url).toBe('rtsp://192.168.1.100/stream')
      expect(rtspSource.enabled).toBe(true)
      expect(rtspSource.id).toBe('source_0')
      expect(savedSettings.audio.next_source_id).toBe(1)
    })

    it('re-enables existing RTSP source instead of duplicating on retry', async () => {
      let savedSettings = null
      mockApi.get.mockResolvedValueOnce({
        data: {
          location: { latitude: 0, longitude: 0, configured: false },
          audio: {
            sources: [
              { id: 'source_0', type: 'pulseaudio', device: 'default', label: 'Local Mic', enabled: false },
              { id: 'source_1', type: 'rtsp', url: 'rtsp://192.168.1.100/stream', label: 'Cam', enabled: false }
            ],
            next_source_id: 2
          }
        }
      })
      mockApi.post.mockResolvedValueOnce({ data: { success: true } })
      mockApi.put.mockImplementationOnce((url, settings) => {
        savedSettings = settings
        return Promise.resolve({
          data: {
            settings: { location: { configured: true, timezone: 'America/New_York' } },
            changes: { full_restart_required: true }
          }
        })
      })

      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const streamCard = wrapper.findAll('button').find(b => b.text().includes('Network Stream'))
      await streamCard.trigger('click')
      await wrapper.find('#rtsp-url').setValue('rtsp://192.168.1.100/stream')

      const finishButton = wrapper.findAll('button').find(b => b.text() === 'Finish')
      await finishButton.trigger('click')
      await flushPromises()

      expect(savedSettings.audio.sources).toHaveLength(2)

      const rtspSource = savedSettings.audio.sources.find(s => s.type === 'rtsp')
      expect(rtspSource.enabled).toBe(true)
      expect(rtspSource.id).toBe('source_1')

      expect(savedSettings.audio.next_source_id).toBe(2)
    })

    it('shows error and stays on wizard when timezone lookup fails', async () => {
      mockApi.get.mockResolvedValueOnce({
        data: {
          location: { latitude: 0, longitude: 0, configured: false },
          audio: {
            sources: [],
            next_source_id: 0
          }
        }
      })
      mockApi.put.mockResolvedValueOnce({
        data: {
          settings: { location: { configured: true } },
          changes: { full_restart_required: true }
        }
      })

      const wrapper = mountWizard()
      await goToStep2(wrapper)

      const finishButton = wrapper.findAll('button').find(b => b.text() === 'Finish')
      await finishButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Could not determine timezone')
      expect(mockRequestRestart).not.toHaveBeenCalled()

      expect(wrapper.text()).toContain('Set Your Location')
    })
  })
})
