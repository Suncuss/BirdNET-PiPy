/**
 * Tests for Table.vue view component
 */
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
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
  default: mockApi,
  SLOW_QUERY_TIMEOUT: 45000
}))

// Mock vue-router's useRoute — Table seeds filters from route.query on mount.
// Tests mutate mockRoute.query before mounting to exercise deep-link seeding.
const mockRoute = vi.hoisted(() => ({ query: {} }))
const mockRouter = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter
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

// Mock DetectionModal — avoids mounting the audio/spectrogram player; exposes the
// props so tests can assert which detection it was opened for.
const DetectionModalStub = {
  name: 'DetectionModal',
  template: '<div v-if="isVisible" class="detection-modal" :data-name="name" :data-id="String(id)"></div>',
  props: ['isVisible', 'name', 'id']
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

enableAutoUnmount(afterEach)

describe('Table.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRoute.query = {}

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
    document.body.style.overflow = ''
  })

  const mountTable = async (options = {}) => {
    const wrapper = mount(Table, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          Teleport: TeleportStub,
          SpectrogramModal: SpectrogramModalStub,
          DetectionModal: DetectionModalStub
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
            SpectrogramModal: SpectrogramModalStub,
            DetectionModal: DetectionModalStub
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

	      const input = wrapper.find('input[role="combobox"]')
	      await input.trigger('focus')

	      // Initial focus shows all options
	      const optionTexts = () => wrapper.findAll('li[role="option"]').map(o => o.text())
	      expect(optionTexts().some(t => t.includes('American Robin'))).toBe(true)
	      expect(optionTexts().some(t => t.includes('Blue Jay'))).toBe(true)

	      // Narrow list via search
	      await input.setValue('robin')
	      expect(optionTexts().some(t => t.includes('American Robin'))).toBe(true)
	      expect(optionTexts().some(t => t.includes('Blue Jay'))).toBe(false)

	      // Select the filtered option
	      const robinOption = wrapper.findAll('li[role="option"]').find(o => o.text().includes('American Robin'))
	      await robinOption.trigger('mousedown')
	      await flushPromises()

	      // Refocus shows all options again: the query resets to the committed
	      // label, which lists everything rather than only the current pick.
	      await input.trigger('focus')
	      expect(optionTexts().some(t => t.includes('American Robin'))).toBe(true)
	      expect(optionTexts().some(t => t.includes('Blue Jay'))).toBe(true)
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
      expect(wrapper.find('button[aria-label="Rows per page"]').exists()).toBe(true)
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

  describe('hour filter', () => {
    it('renders a desktop-only hour dropdown: Any hour + 24 hours', async () => {
      const wrapper = await mountTable()

      const hourLabel = wrapper.findAll('label').find(l => l.text() === 'Hour')
      expect(hourLabel).toBeTruthy()

      // Hidden on mobile, shown from the lg breakpoint up
      const container = hourLabel.element.parentElement
      expect(container.className).toContain('hidden')
      expect(container.className).toContain('lg:block')

      const trigger = container.querySelector('button[aria-label="Hour"]')
      expect(trigger).toBeTruthy()
      await trigger.click()
      await wrapper.vm.$nextTick()

      const options = [...container.querySelectorAll('li[role="option"]')]
      // Leading "no filter" option + 24 hours
      expect(options).toHaveLength(25)
      expect(options[0].textContent.trim()).toBe('Any hour')
    })

    it('selecting an hour applies it as a detections filter, as a number', async () => {
      const wrapper = await mountTable()

      const container = wrapper
        .findAll('label')
        .find(l => l.text() === 'Hour')
        .element.parentElement
      const trigger = wrapper.find('button[aria-label="Hour"]')
      await trigger.trigger('click')

      // Options are [Any hour, 0, 1, ... 23]; index 15 is hour 14.
      const options = [...container.querySelectorAll('li[role="option"]')]
      options[15].click()
      await flushPromises()

      const detectionCalls = mockApi.get.mock.calls.filter(
        ([url]) => url === '/detections'
      )
      // Not "14": AppListbox restores the option's original numeric type.
      expect(detectionCalls.at(-1)[1].params.hour).toBe(14)
    })

    it('keeps the hour control box-aligned with the other filter controls', async () => {
      const wrapper = await mountTable()

      const trigger = wrapper.find('button[aria-label="Hour"]')

      // The Hour control must share the h-10 height its From/To/Species
      // siblings use, or the filter row stops lining up.
      expect(trigger.classes()).toContain('h-10')
      const speciesInput = wrapper.find('input[placeholder="All species"]')
      expect(speciesInput.classes()).toContain('h-10')
    })

    it('seeds date + hour filters from the route query on mount', async () => {
      mockRoute.query = { date: '2024-01-15', hour: '14' }

      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall).toBeTruthy()
      expect(detectionCall[1].params).toMatchObject({
        start_date: '2024-01-15',
        end_date: '2024-01-15',
        hour: 14
      })
    })

    it('seeds hour 0 from the route query (falsy but valid)', async () => {
      mockRoute.query = { date: '2024-01-15', hour: '0' }

      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall[1].params.hour).toBe(0)
    })

    it('seeds the species filter from the route query (heatmap cell deep-link)', async () => {
      mockRoute.query = { date: '2024-01-15', hour: '14', species: 'American Robin' }

      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall[1].params).toMatchObject({
        start_date: '2024-01-15',
        end_date: '2024-01-15',
        hour: 14,
        species: 'American Robin'
      })
    })

    it('trims a space-padded species from the route query', async () => {
      mockRoute.query = { species: '  American Robin  ' }

      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall[1].params.species).toBe('American Robin')
    })

    it('does not send date/hour params when the route query is empty', async () => {
      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall[1].params).not.toHaveProperty('hour')
      expect(detectionCall[1].params).not.toHaveProperty('start_date')
    })

    it('strips date/hour/species from the route query when filters are cleared', async () => {
      mockRoute.query = { date: '2024-01-15', hour: '14', species: 'American Robin' }

      const wrapper = await mountTable()

      const clearBtn = wrapper.findAll('button').find(b => b.text() === 'Clear')
      expect(clearBtn).toBeTruthy()
      await clearBtn.trigger('click')

      // Without this, a remount/refresh re-seeds the just-cleared filters.
      expect(mockRouter.replace).toHaveBeenCalledWith({ query: {} })
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

    it('closes delete modal on Escape', async () => {
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

      const deleteButton = wrapper.find('tbody tr').findAll('button').pop()
      await deleteButton.trigger('click')
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      await wrapper.vm.$nextTick()

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

      const trigger = wrapper.find('button[aria-label="Rows per page"]')
      expect(trigger.exists()).toBe(true)
      await trigger.trigger('click')

      const options = trigger.element.parentElement.querySelectorAll('li[role="option"]')
      const labels = [...options].map(o => o.textContent.trim())
      expect(labels).toEqual(['25', '50', '100', '200'])
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

  describe('detection detail modal', () => {
    it('opens the detail modal for the clicked row instead of navigating', async () => {
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
      expect(wrapper.find('.detection-modal').exists()).toBe(false)

      const infoLink = wrapper.find('tbody tr').find('a[title="Detection info"]')
      expect(infoLink.exists()).toBe(true)
      await infoLink.trigger('click')

      const modal = wrapper.find('.detection-modal')
      expect(modal.exists()).toBe(true)
      expect(modal.attributes('data-name')).toBe('American Robin')
      expect(modal.attributes('data-id')).toBe('1')
    })
  })

  describe('url state (page in url)', () => {
    it('seeds the page number from the route query', async () => {
      mockRoute.query = { page: '3' }

      await mountTable()

      const detectionCall = mockApi.get.mock.calls.find(
        ([url]) => url === '/detections'
      )
      expect(detectionCall[1].params.page).toBe(3)
    })

    it('writes the page to the route query when paging', async () => {
      mockApi.get.mockImplementation((url) => {
        if (url === '/detections') {
          return Promise.resolve({
            data: {
              detections: sampleDetections,
              pagination: { total_items: 100, page: 1, per_page: 25, total_pages: 4 }
            }
          })
        }
        return Promise.resolve({ data: [] })
      })

      const wrapper = await mountTable()

      // Footer holds the per-page listbox trigger plus the nav buttons; drop
      // the listbox trigger so the nav buttons are [first, prev, next, last].
      const navButtons = wrapper
        .find('.bg-gray-50.border-t')
        .findAll('button')
        .filter(b => b.attributes('aria-haspopup') !== 'listbox')
      await navButtons[2].trigger('click') // next page
      await flushPromises()

      expect(mockRouter.replace).toHaveBeenCalledWith({ query: { page: 2 } })
    })
  })
})
