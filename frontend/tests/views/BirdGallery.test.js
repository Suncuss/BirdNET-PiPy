import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import BirdGallery from '@/views/BirdGallery.vue'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
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
})
