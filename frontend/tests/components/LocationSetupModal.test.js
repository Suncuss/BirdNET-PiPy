import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import LocationSetupModal from '@/components/LocationSetupModal.vue'

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

describe('LocationSetupModal', () => {
  let fetchMock

  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock = vi.fn()
    global.fetch = fetchMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountModal = (props = {}) => mount(LocationSetupModal, {
    props: {
      isVisible: true,
      ...props
    }
  })

  describe('Rendering', () => {
    it('renders when isVisible is true', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Set Your Location')
    })

    it('does not render when isVisible is false', () => {
      const wrapper = mountModal({ isVisible: false })
      expect(wrapper.text()).not.toContain('Set Your Location')
    })

    it('displays all input options', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Use My Current Location')
      expect(wrapper.text()).toContain('or search by address')
      expect(wrapper.text()).toContain('or enter coordinates manually')
    })

    it('shows latitude and longitude input fields', () => {
      const wrapper = mountModal()
      expect(wrapper.find('#latitude').exists()).toBe(true)
      expect(wrapper.find('#longitude').exists()).toBe(true)
    })

    it('shows skip option', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Skip for now')
    })
  })

  describe('Manual Coordinate Entry', () => {
    it('enables save button when valid coordinates are entered', async () => {
      const wrapper = mountModal()

      await wrapper.find('#latitude').setValue(42.47)
      await wrapper.find('#longitude').setValue(-76.45)

      const saveButton = wrapper.findAll('button').find(b => b.text().includes('Save Location'))
      expect(saveButton.attributes('disabled')).toBeUndefined()
    })

    it('disables save button when coordinates are invalid', async () => {
      const wrapper = mountModal()

      await wrapper.find('#latitude').setValue(999) // Invalid latitude
      await wrapper.find('#longitude').setValue(-76.45)

      const saveButton = wrapper.findAll('button').find(b => b.text().includes('Save Location'))
      expect(saveButton.attributes('disabled')).toBeDefined()
    })

    it('displays selected location when coordinates are entered', async () => {
      const wrapper = mountModal()

      await wrapper.find('#latitude').setValue(42.47)
      await wrapper.find('#longitude').setValue(-76.45)

      expect(wrapper.text()).toContain('Selected:')
      expect(wrapper.text()).toContain('42.47')
      expect(wrapper.text()).toContain('-76.45')
    })
  })

  describe('Save Location', () => {
    it('saves location and emits location-saved event', async () => {
      mockApi.get.mockResolvedValueOnce({
        data: { location: { latitude: 0, longitude: 0, configured: false } }
      })
      mockApi.put.mockResolvedValueOnce({ data: { message: 'Settings saved' } })

      const wrapper = mountModal()

      await wrapper.find('#latitude').setValue(42.47)
      await wrapper.find('#longitude').setValue(-76.45)

      const saveButton = wrapper.findAll('button').find(b => b.text().includes('Save Location'))
      await saveButton.trigger('click')
      await flushPromises()

      expect(wrapper.emitted('location-saved')).toBeTruthy()
      // Note: close is not emitted - page reloads after service restart
    })

    it('sets configured flag to true when saving', async () => {
      let savedSettings = null
      mockApi.get.mockResolvedValueOnce({
        data: { location: { latitude: 0, longitude: 0, configured: false } }
      })
      mockApi.put.mockImplementationOnce((url, settings) => {
        savedSettings = settings
        return Promise.resolve({ data: { message: 'Settings saved' } })
      })

      const wrapper = mountModal()

      await wrapper.find('#latitude').setValue(42.47)
      await wrapper.find('#longitude').setValue(-76.45)

      const saveButton = wrapper.findAll('button').find(b => b.text().includes('Save Location'))
      await saveButton.trigger('click')
      await flushPromises()

      expect(savedSettings.location.configured).toBe(true)
    })
  })

  describe('Skip Setup', () => {
    it('marks location as configured when skipping', async () => {
      let savedSettings = null
      mockApi.get.mockResolvedValueOnce({
        data: { location: { latitude: 42.47, longitude: -76.45, configured: false } }
      })
      mockApi.put.mockImplementationOnce((url, settings) => {
        savedSettings = settings
        return Promise.resolve({ data: { message: 'Settings saved' } })
      })

      const wrapper = mountModal()

      const skipButton = wrapper.findAll('button').find(b => b.text().includes('Skip for now'))
      await skipButton.trigger('click')
      await flushPromises()

      expect(savedSettings.location.configured).toBe(true)
      // Note: close is not emitted - page reloads after service restart
    })
  })

  describe('Address Search', () => {
    it('shows search input field', () => {
      const wrapper = mountModal()
      const searchInput = wrapper.find('input[placeholder*="City"]')
      expect(searchInput.exists()).toBe(true)
    })

    it('shows error message when search returns no results', async () => {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([])
      })

      const wrapper = mountModal()

      // Directly set the search query through the component
      await wrapper.find('input[placeholder*="City"]').setValue('NonexistentPlace12345')

      // Find and click the search button
      const buttons = wrapper.findAll('button')
      const searchButton = buttons[1] // Second button is the search button
      await searchButton.trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('No results found')
    })
  })

  describe('Browser Geolocation', () => {
    it('shows geolocation button', () => {
      const wrapper = mountModal()
      const geoButton = wrapper.findAll('button').find(b => b.text().includes('Use My Current Location'))
      expect(geoButton).toBeTruthy()
    })
  })
})
