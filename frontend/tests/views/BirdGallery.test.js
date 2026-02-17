import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, defineComponent, nextTick } from 'vue'
import BirdGallery from '@/views/BirdGallery.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock useSmartCrop composable
vi.mock('@/composables/useSmartCrop', () => ({
  useSmartCrop: () => ({
    calculateFocalPoint: vi.fn().mockResolvedValue('50% 50%'),
    processBirdImages: vi.fn().mockImplementation(async (birds) => {
      birds.forEach(bird => {
        bird.focalPoint = '50% 50%'
        bird.focalPointReady = true
      })
    }),
    useFocalPoint: () => ({
      focalPoint: { value: '50% 50%' },
      isReady: { value: true },
      updateFocalPoint: vi.fn()
    }),
    clearCache: vi.fn()
  })
}))

const mountGallery = () => mount(BirdGallery, {
  global: {
    stubs: {
      'font-awesome-icon': true,
      'router-link': RouterLinkStub
    }
  }
})

describe('BirdGallery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads recent unique birds on mount', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({
          data: [
            { id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: {
            imageUrl: '/sparrow.jpg',
            authorName: 'Jane Doe',
            authorUrl: 'https://example.com',
            licenseType: 'CC BY-SA 4.0'
          }
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    expect(mockApi.get).toHaveBeenCalledWith('/sightings/unique', { params: { date: expect.any(String) } })
    expect(mockApi.get).toHaveBeenCalledWith('/wikimedia_image', { params: { species: 'Sparrow' } })
    expect(wrapper.text()).toContain('Sparrow')
    expect(wrapper.text()).toContain('Passer domesticus')
    expect(wrapper.text()).toContain('Photo by')
  })

  it('switches tab to fetch frequent sightings', async () => {
    mockApi.get.mockImplementation((url, config) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({
          data: [
            { id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: { imageUrl: '/bird.jpg', authorName: 'Photographer', authorUrl: '#', licenseType: 'CC' }
        })
      }
      if (url === '/sightings' && config?.params?.type === 'frequent') {
        return Promise.resolve({
          data: [
            { id: 2, common_name: 'Blue Jay', scientific_name: 'Cyanocitta cristata', timestamp: '2024-08-02T10:00:00Z' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    await wrapper.vm.selectTab('frequent')
    await flushPromises()

    expect(mockApi.get).toHaveBeenCalledWith('/sightings', { params: { type: 'frequent' } })
    expect(wrapper.text()).toContain('Blue Jay')
    expect(wrapper.text()).not.toContain('Detection info available in details')
  })

  it('shows empty state when no birds are returned', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    expect(wrapper.text()).toContain('No birds to display yet.')
  })

  it('shows custom image label when bird has custom image', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({
          data: [
            { id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: {
            imageUrl: '/sparrow.jpg',
            authorName: 'Jane Doe',
            authorUrl: 'https://example.com',
            licenseType: 'CC BY-SA 4.0',
            hasCustomImage: true
          }
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    expect(wrapper.text()).toContain('Custom image')
    expect(wrapper.text()).not.toContain('Photo by')
  })

  it('shows wikimedia attribution when bird has no custom image', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({
          data: [
            { id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: {
            imageUrl: '/sparrow.jpg',
            authorName: 'Jane Doe',
            authorUrl: 'https://example.com',
            licenseType: 'CC BY-SA 4.0',
            hasCustomImage: false
          }
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    expect(wrapper.text()).toContain('Photo by')
    expect(wrapper.text()).toContain('Jane Doe')
  })

  describe('keep-alive behavior', () => {
    const Placeholder = defineComponent({
      name: 'Placeholder',
      template: '<div>placeholder</div>'
    })

    const mountInKeepAlive = () => {
      const showGallery = ref(true)
      const wrapper = mount(defineComponent({
        components: { BirdGallery, Placeholder },
        setup() { return { showGallery } },
        template: `
          <keep-alive include="BirdGallery">
            <BirdGallery v-if="showGallery" />
            <Placeholder v-else />
          </keep-alive>
        `
      }), {
        global: {
          stubs: { 'font-awesome-icon': true, 'router-link': RouterLinkStub }
        }
      })
      return { wrapper, showGallery }
    }

    beforeEach(() => {
      vi.useFakeTimers()
      mockApi.get.mockImplementation((url) => {
        if (url === '/sightings/unique') {
          return Promise.resolve({
            data: [{ id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }]
          })
        }
        if (url === '/wikimedia_image') {
          return Promise.resolve({
            data: { imageUrl: '/sparrow.jpg', authorName: 'Doe', authorUrl: '#', licenseType: 'CC' }
          })
        }
        return Promise.resolve({ data: [] })
      })
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('first mount does not double-fetch', async () => {
      mountInKeepAlive()
      await flushPromises()

      // onActivated fires on initial mount but hasBeenDeactivated is false, so no extra fetch
      const uniqueCalls = mockApi.get.mock.calls.filter(c => c[0] === '/sightings/unique')
      expect(uniqueCalls).toHaveLength(1)
    })

    it('re-activation after stale threshold triggers re-fetch', async () => {
      const { showGallery } = mountInKeepAlive()
      await flushPromises()

      const initialCalls = mockApi.get.mock.calls.filter(c => c[0] === '/sightings/unique').length

      // Deactivate
      showGallery.value = false
      await nextTick()

      // Advance time past stale threshold (2 minutes)
      vi.advanceTimersByTime(3 * 60 * 1000)

      // Reactivate
      showGallery.value = true
      await nextTick()
      await flushPromises()

      const totalCalls = mockApi.get.mock.calls.filter(c => c[0] === '/sightings/unique').length
      expect(totalCalls).toBeGreaterThan(initialCalls)
    })

    it('re-activation within threshold does not re-fetch', async () => {
      const { showGallery } = mountInKeepAlive()
      await flushPromises()

      const initialCalls = mockApi.get.mock.calls.filter(c => c[0] === '/sightings/unique').length

      // Deactivate
      showGallery.value = false
      await nextTick()

      // Advance time but stay within stale threshold
      vi.advanceTimersByTime(30 * 1000)

      // Reactivate
      showGallery.value = true
      await nextTick()
      await flushPromises()

      const totalCalls = mockApi.get.mock.calls.filter(c => c[0] === '/sightings/unique').length
      expect(totalCalls).toBe(initialCalls)
    })
  })
})
