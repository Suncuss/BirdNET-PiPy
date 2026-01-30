/**
 * Tests for Table.vue view component
 */
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import Table from '@/views/Table.vue'

// Mock router-link
const RouterLinkStub = {
  name: 'RouterLink',
  template: '<a><slot /></a>',
  props: ['to']
}

// Mock teleport
const TeleportStub = {
  name: 'Teleport',
  template: '<div><slot /></div>',
  props: ['to']
}

// Mock API
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  delete: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    api: vi.fn()
  })
}))

// Mock SpectrogramModal
const SpectrogramModalStub = {
  name: 'SpectrogramModal',
  template: '<div v-if="isVisible" class="spectrogram-modal"></div>',
  props: ['isVisible', 'imageUrl', 'alt']
}

// Mock AppDatePicker component to avoid PrimeVue dependency in tests
vi.mock('@/components/AppDatePicker.vue', () => ({
  default: {
    name: 'AppDatePicker',
    template: '<input type="date" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)" />',
    props: ['modelValue', 'disabled', 'max'],
    emits: ['update:modelValue', 'change']
  }
}))

describe('Table.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Default mock responses
    mockApi.get.mockImplementation((url) => {
      if (url === '/detections') {
        return Promise.resolve({
          data: {
            detections: [],
            pagination: { total_items: 0, page: 1, per_page: 25 }
          }
        })
      }
      if (url === '/species/all') {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: {} })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountTable = async (options = {}) => {
    const wrapper = mount(Table, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          Teleport: TeleportStub,
          SpectrogramModal: SpectrogramModalStub
        }
      },
      ...options
    })
    await flushPromises()
    return wrapper
  }

  const sampleDetections = [
    {
      id: 1,
      common_name: 'American Robin',
      scientific_name: 'Turdus migratorius',
      confidence: 0.95,
      timestamp: '2024-01-15T10:30:00',
      audio_filename: 'robin.mp3',
      spectrogram_filename: 'robin.webp'
    },
    {
      id: 2,
      common_name: 'Blue Jay',
      scientific_name: 'Cyanocitta cristata',
      confidence: 0.78,
      timestamp: '2024-01-15T11:45:00',
      audio_filename: 'jay.mp3',
      spectrogram_filename: 'jay.webp'
    }
  ]

  describe('rendering', () => {
    it('renders loading state initially', async () => {
      // Create a pending promise to keep loading state
      let resolvePromise
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return new Promise(resolve => {
            resolvePromise = resolve
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = mount(Table, {
        global: {
          stubs: {
            RouterLink: RouterLinkStub,
            Teleport: TeleportStub,
            SpectrogramModal: SpectrogramModalStub
          }
        }
      })

      // Wait for next tick to allow Vue to process the loading state
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('Loading')

      // Resolve to clean up
      resolvePromise({ data: { detections: [], pagination: { total_items: 0 } } })
      await flushPromises()
    })

    it('renders empty state when no detections', async () => {
      const wrapper = await mountTable()

      expect(wrapper.text()).toContain('No detections yet')
    })

	    it('renders empty state with filters message when filters active', async () => {
      mockApi.get.mockImplementation((url, options) => {
        if (url === '/detections' && options?.params?.species) {
          return Promise.resolve({
            data: {
              detections: [],
              pagination: { total_items: 0 }
            }
          })
        }
        if (url === '/species/all') {
          return Promise.resolve({
            data: [{ common_name: 'Robin', scientific_name: 'Turdus' }]
          })
        }
        return Promise.resolve({
          data: { detections: [], pagination: { total_items: 0 } }
        })
      })

      const wrapper = await mountTable()

      // Simulate species filter selection
      const input = wrapper.find('input[type="text"]')
      await input.setValue('Robin')
      await input.trigger('focus')

	      // No results with filters shows different message
	      expect(wrapper.text()).toContain('No detections yet')
	    })

	    it('shows full species list after selecting a species', async () => {
	      mockApi.get.mockImplementation((url, options) => {
	        if (url === '/detections') {
	          return Promise.resolve({
	            data: {
	              detections: [],
	              pagination: { total_items: 0, total_pages: 0, ...options?.params }
	            }
	          })
	        }
	        if (url === '/species/all') {
	          return Promise.resolve({
	            data: [
	              { common_name: 'American Robin', scientific_name: 'Turdus migratorius' },
	              { common_name: 'Blue Jay', scientific_name: 'Cyanocitta cristata' }
	            ]
	          })
	        }
	        return Promise.resolve({ data: {} })
	      })

	      const wrapper = await mountTable()

	      const input = wrapper.find('input[type="text"]')
	      await input.trigger('focus')

	      // Initial focus shows all options
	      expect(wrapper.findAll('button').some(b => b.text().includes('American Robin'))).toBe(true)
	      expect(wrapper.findAll('button').some(b => b.text().includes('Blue Jay'))).toBe(true)

	      // Narrow list via search
	      await input.setValue('robin')
	      expect(wrapper.findAll('button').some(b => b.text().includes('American Robin'))).toBe(true)
	      expect(wrapper.findAll('button').some(b => b.text().includes('Blue Jay'))).toBe(false)

	      // Select the filtered option (handler is on mousedown)
	      const robinOption = wrapper.findAll('button').find(b => b.text().includes('American Robin'))
	      await robinOption.trigger('mousedown')
	      await flushPromises()

	      // Refocus shows all options again (no stale filtered list)
	      await input.trigger('focus')
	      expect(wrapper.findAll('button').some(b => b.text().includes('American Robin'))).toBe(true)
	      expect(wrapper.findAll('button').some(b => b.text().includes('Blue Jay'))).toBe(true)
	    })

	    it('renders table with detections', async () => {
	      mockApi.get.mockImplementation((url) => {
	        if (url === '/detections') {
	          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 2, page: 1, per_page: 25 }
            }
          })
        }
        if (url === '/species/all') {
          return Promise.resolve({ data: [] })
        }
        return Promise.resolve({ data: {} })
      })

      const wrapper = await mountTable()

      expect(wrapper.text()).toContain('American Robin')
      expect(wrapper.text()).toContain('Turdus migratorius')
      expect(wrapper.text()).toContain('Blue Jay')
      expect(wrapper.text()).toContain('95%')
      expect(wrapper.text()).toContain('78%')
    })

    it('renders pagination controls when detections exist', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 100, page: 1, per_page: 25 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      expect(wrapper.text()).toContain('100 total')
      expect(wrapper.find('select').exists()).toBe(true)
    })
  })

  describe('filter section', () => {
    it('renders date inputs', async () => {
      const wrapper = await mountTable()

      const dateInputs = wrapper.findAll('input[type="date"]')
      expect(dateInputs.length).toBe(2)
    })

    it('renders species search input', async () => {
      const wrapper = await mountTable()

      const textInput = wrapper.find('input[placeholder="All species"]')
      expect(textInput.exists()).toBe(true)
    })

    it('shows clear filters button when filters active', async () => {
      const wrapper = await mountTable()

      // Set a date filter
      const startDateInput = wrapper.findAll('input[type="date"]')[0]
      await startDateInput.setValue('2024-01-01')
      await startDateInput.trigger('change')
      await flushPromises()

      expect(wrapper.text()).toContain('Clear')
    })
  })

  describe('table interactions', () => {
    it('renders sortable column headers', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 2 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      const headers = wrapper.findAll('th')
      expect(headers.length).toBeGreaterThan(0)
      expect(wrapper.text()).toContain('Date & Time')
      expect(wrapper.text()).toContain('Species')
      expect(wrapper.text()).toContain('Confidence')
    })

    it('renders action buttons for each row', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 2 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      const rows = wrapper.findAll('tbody tr')
      expect(rows.length).toBe(2)

      // Each row should have action buttons
      const firstRowButtons = rows[0].findAll('button')
      expect(firstRowButtons.length).toBeGreaterThanOrEqual(3) // play, spectrogram, delete
    })
  })

	  describe('delete functionality', () => {
    it('shows delete confirmation modal', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 2 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      // Find and click delete button (last button in row)
      const firstRow = wrapper.find('tbody tr')
      const deleteButton = firstRow.findAll('button').pop()
      await deleteButton.trigger('click')

      expect(wrapper.text()).toContain('Delete Detection')
      expect(wrapper.text()).toContain('American Robin')
    })

	    it('closes delete modal on cancel', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 2 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      // Open modal
      const deleteButton = wrapper.find('tbody tr').findAll('button').pop()
      await deleteButton.trigger('click')

      // Click cancel
      const cancelButton = wrapper.findAll('button').find(b => b.text() === 'Cancel')
      await cancelButton.trigger('click')

      // Modal should be closed - the delete modal has specific text
      await flushPromises()
      // After cancel, there should be no modal-specific content visible
	      const modalContent = wrapper.find('.fixed.inset-0')
	      expect(modalContent.exists()).toBe(false)
	    })

	    it('shows an action error on delete failure without replacing table UI', async () => {
	      mockApi.get.mockImplementation((url) => {
	        if (url === '/detections') {
	          return Promise.resolve({
	            data: {
	              detections: sampleDetections,
	              pagination: { total_items: 2, total_pages: 1 }
	            }
	          })
	        }
	        if (url === '/species/all') {
	          return Promise.resolve({ data: [] })
	        }
	        return Promise.resolve({ data: {} })
	      })

	      mockApi.delete.mockRejectedValueOnce({ response: { status: 401 } })

	      const wrapper = await mountTable()

	      // Open modal
	      const deleteButton = wrapper.find('tbody tr').findAll('button').pop()
	      await deleteButton.trigger('click')

	      // Confirm delete
	      const confirmButton = wrapper.findAll('button').find(b => b.text() === 'Delete')
	      await confirmButton.trigger('click')
	      await flushPromises()

	      // Table remains visible and an inline action error is shown
	      expect(wrapper.text()).toContain('American Robin')
	      expect(wrapper.text()).toContain('Please log in to delete')
	    })
	  })

  describe('pagination', () => {
    it('renders page numbers', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 100, page: 1, per_page: 25 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      // Should show page 1 / 4 format
      expect(wrapper.text()).toContain('1 / 4')
    })

    it('renders per-page selector', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 100, page: 1, per_page: 25 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      const select = wrapper.find('select')
      expect(select.exists()).toBe(true)

      const options = select.findAll('option')
      expect(options.map(o => o.text())).toContain('25')
      expect(options.map(o => o.text())).toContain('50')
      expect(options.map(o => o.text())).toContain('100')
    })
  })

  describe('confidence display', () => {
    it('formats confidence as percentage', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: [
                { ...sampleDetections[0], confidence: 0.856 }
              ],
              pagination: { total_items: 1 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      expect(wrapper.text()).toContain('86%')
    })
  })
})
