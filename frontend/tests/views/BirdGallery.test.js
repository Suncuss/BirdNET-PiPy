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

  it('loads species catalog without per-species detail fan-out', async () => {
    mockApi.get.mockImplementation((url) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/species/all') {
        return Promise.resolve({
          data: [
            {
              common_name: 'Blue Jay',
              scientific_name: 'Cyanocitta cristata',
              last_detected: '2024-08-02T10:00:00Z'
            }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: { imageUrl: '/bird.jpg', authorName: 'Photographer', authorUrl: '#', licenseType: 'CC' }
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    await wrapper.vm.selectTab('all')
    await flushPromises()

    expect(mockApi.get).toHaveBeenCalledWith('/species/all')
    // N+1 collapsed: last_detected comes from /species/all, no /bird/<name> calls
    const birdDetailCalls = mockApi.get.mock.calls.filter(c => c[0].startsWith('/bird/'))
    expect(birdDetailCalls).toHaveLength(0)
    expect(wrapper.text()).toContain('Blue Jay')
    expect(wrapper.text()).not.toContain('Detection info available in details')
  })

  it('ignores a slow tab response when the user switches away mid-load', async () => {
    let resolveAll
    mockApi.get.mockImplementation((url) => {
      if (url === '/species/all') {
        return new Promise(resolve => {
          resolveAll = () => resolve({
            data: [{ common_name: 'Slow Species', scientific_name: 'Tardus', last_detected: null }]
          })
        })
      }
      if (url === '/sightings') {
        return Promise.resolve({
          data: [
            { id: 1, common_name: 'Fast Bird', scientific_name: 'Rapidus', timestamp: '2024-08-02T10:00:00Z' }
          ]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({
          data: { imageUrl: '/bird.jpg', authorName: 'P', authorUrl: '#', licenseType: 'CC' }
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    // Start the slow 'all' tab, then switch to 'frequent' before it resolves.
    wrapper.vm.selectTab('all')
    await wrapper.vm.selectTab('frequent')
    await flushPromises()

    // The 'all' response arrives late — its stale version must be discarded.
    resolveAll()
    await flushPromises()

    expect(wrapper.text()).toContain('Fast Bird')
    expect(wrapper.text()).not.toContain('Slow Species')
  })

  it('serves a revisited tab from cache without refetching', async () => {
    mockApi.get.mockImplementation((url, config) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({
          data: [{ id: 1, common_name: 'Sparrow', scientific_name: 'Passer domesticus', timestamp: '2024-08-01T12:00:00Z' }]
        })
      }
      if (url === '/sightings' && config?.params?.type === 'frequent') {
        return Promise.resolve({
          data: [{ id: 2, common_name: 'Blue Jay', scientific_name: 'Cyanocitta cristata', timestamp: '2024-08-02T10:00:00Z' }]
        })
      }
      if (url === '/wikimedia_image') {
        return Promise.resolve({ data: { imageUrl: '/bird.jpg', authorName: 'P', authorUrl: '#', licenseType: 'CC' } })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    await wrapper.vm.selectTab('frequent')
    await flushPromises()
    const callsAfterFirstVisit = mockApi.get.mock.calls.filter(c => c[0] === '/sightings').length

    // Switch away and back — the cached 'frequent' tab must not refetch.
    await wrapper.vm.selectTab('recent')
    await flushPromises()
    await wrapper.vm.selectTab('frequent')
    await flushPromises()

    expect(mockApi.get.mock.calls.filter(c => c[0] === '/sightings').length).toBe(callsAfterFirstVisit)
    expect(wrapper.text()).toContain('Blue Jay')
  })

  it('resumes image loading when returning to a tab abandoned mid-load', async () => {
    const wikimediaResolvers = []
    mockApi.get.mockImplementation((url, config) => {
      if (url === '/sightings/unique') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/sightings' && config?.params?.type === 'frequent') {
        return Promise.resolve({
          data: [{ id: 1, common_name: 'Blue Jay', scientific_name: 'Cyanocitta cristata', timestamp: '2024-08-02T10:00:00Z' }]
        })
      }
      if (url === '/wikimedia_image') {
        // Hand the test control over when each image lookup resolves.
        return new Promise(resolve => { wikimediaResolvers.push(resolve) })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = mountGallery()
    await flushPromises()

    // Visit 'frequent' — its image lookup is now pending.
    await wrapper.vm.selectTab('frequent')
    await flushPromises()
    expect(wikimediaResolvers).toHaveLength(1)

    // Switch away, then let the now-stale lookup resolve — it must be discarded.
    await wrapper.vm.selectTab('recent')
    await flushPromises()
    wikimediaResolvers[0]({
      data: { imageUrl: '/jay.jpg', authorName: 'StalePhotographer', authorUrl: '#', licenseType: 'CC' }
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('StalePhotographer')

    // Return to the cached tab — image loading must resume for the placeholder card.
    await wrapper.vm.selectTab('frequent')
    await flushPromises()
    expect(wikimediaResolvers).toHaveLength(2)
    wikimediaResolvers[1]({
      data: { imageUrl: '/jay.jpg', authorName: 'FreshPhotographer', authorUrl: '#', licenseType: 'CC' }
    })
    await flushPromises()

    expect(wrapper.text()).toContain('FreshPhotographer')
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
