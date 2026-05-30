/**
 * Tests for BirdImageModal.vue: candidate grid, selection, apply flows.
 */

import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import BirdImageModal from '@/components/BirdImageModal.vue'

const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// useAuth — default to "no login required" so the apply path runs end-to-end.
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    needsLogin: { value: false }
  })
}))

const mockCandidates = [
  {
    fileTitle: 'File:A.jpg',
    imageUrl: 'https://upload.wikimedia.org/A.jpg',
    thumbUrl: 'https://upload.wikimedia.org/thumb/A_400.jpg',
    pageUrl: 'https://commons.wikimedia.org/wiki/File:A.jpg',
    authorName: 'Alice',
    authorUrl: 'https://example.com/a',
    licenseType: 'CC BY 2.0'
  },
  {
    fileTitle: 'File:B.jpg',
    imageUrl: 'https://upload.wikimedia.org/B.jpg',
    thumbUrl: 'https://upload.wikimedia.org/thumb/B_400.jpg',
    pageUrl: 'https://commons.wikimedia.org/wiki/File:B.jpg',
    authorName: 'Bob',
    authorUrl: null,
    licenseType: 'CC0'
  }
]

const mountOpen = (overrides = {}) =>
  mount(BirdImageModal, {
    props: {
      isVisible: true,
      speciesName: 'American Robin',
      hasCustomImage: false,
      selectedFileTitle: null,
      ...overrides
    }
  })

describe('BirdImageModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApi.get.mockResolvedValue({ data: { candidates: mockCandidates } })
    mockApi.put.mockResolvedValue({ data: {} })
    mockApi.post.mockResolvedValue({ data: { hasCustomImage: true } })
    mockApi.delete.mockResolvedValue({ data: { hasChoice: false } })
    // Avoid jsdom complaining about missing URL.createObjectURL
    if (!global.URL.createObjectURL) {
      global.URL.createObjectURL = vi.fn(() => 'blob:mock')
      global.URL.revokeObjectURL = vi.fn()
    }
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches candidates when opened and renders one tile per candidate plus an upload tile', async () => {
    const wrapper = mountOpen()
    await flushPromises()

    expect(mockApi.get).toHaveBeenCalledWith('/wikimedia_image/candidates', {
      params: { species: 'American Robin', limit: 8 }
    })

    const candidateImgs = wrapper.findAll('img').filter(img =>
      img.attributes('src')?.startsWith('https://upload.wikimedia.org/')
    )
    expect(candidateImgs.length).toBe(2)
    // Apply button starts disabled (selection unchanged).
    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    expect(applyBtn.attributes('disabled')).toBeDefined()
  })

  it('highlights the saved choice when selectedFileTitle matches a candidate', async () => {
    const wrapper = mountOpen({ selectedFileTitle: 'File:B.jpg' })
    await flushPromises()
    // Selected tile carries the green ring class.
    const selected = wrapper.findAll('button').filter(b => b.classes().includes('ring-green-600'))
    expect(selected.length).toBe(1)
  })

  it('selecting a different Wikimedia tile and clicking Apply PUTs the choice and emits applied', async () => {
    const wrapper = mountOpen({ selectedFileTitle: 'File:A.jpg' })
    await flushPromises()

    // Click the second candidate (File:B.jpg).
    const candidateButtons = wrapper.findAll('button').filter(b =>
      b.find('img[src^="https://upload.wikimedia.org/"]').exists()
    )
    await candidateButtons[1].trigger('click')
    await flushPromises()

    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    expect(applyBtn.attributes('disabled')).toBeUndefined()
    await applyBtn.trigger('click')
    await flushPromises()

    expect(mockApi.put).toHaveBeenCalledWith(
      '/bird/American%20Robin/wikimedia_choice',
      expect.objectContaining({
        fileTitle: 'File:B.jpg',
        thumbUrl: 'https://upload.wikimedia.org/thumb/B_400.jpg'
      })
    )
    // No custom image existed → no DELETE /image call.
    expect(mockApi.delete).not.toHaveBeenCalled()
    expect(wrapper.emitted('applied')).toBeTruthy()
    expect(wrapper.emitted('applied')[0][0]).toMatchObject({
      kind: 'wikimedia',
      candidate: { fileTitle: 'File:B.jpg' }
    })
  })

  it('also DELETEs the existing custom upload when applying a Wikimedia choice', async () => {
    const wrapper = mountOpen({ hasCustomImage: true })
    await flushPromises()

    const candidateButtons = wrapper.findAll('button').filter(b =>
      b.find('img[src^="https://upload.wikimedia.org/"]').exists()
    )
    await candidateButtons[0].trigger('click')
    await flushPromises()

    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    await applyBtn.trigger('click')
    await flushPromises()

    expect(mockApi.put).toHaveBeenCalled()
    expect(mockApi.delete).toHaveBeenCalledWith('/bird/American%20Robin/image')
  })

  it('uploading a file POSTs to /image and emits applied with kind=upload', async () => {
    const wrapper = mountOpen()
    await flushPromises()

    const file = new File(['x'], 'bird.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')
    await flushPromises()

    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    expect(applyBtn.attributes('disabled')).toBeUndefined()
    await applyBtn.trigger('click')
    await flushPromises()

    expect(mockApi.post).toHaveBeenCalledWith(
      '/bird/American%20Robin/image',
      expect.any(FormData),
      expect.objectContaining({
        headers: { 'Content-Type': 'multipart/form-data' }
      })
    )
    expect(wrapper.emitted('applied')[0][0]).toMatchObject({ kind: 'upload', hasCustomImage: true })
  })

  it('reset flow DELETEs both /image and /wikimedia_choice', async () => {
    const wrapper = mountOpen({
      hasCustomImage: true,
      selectedFileTitle: 'File:A.jpg'
    })
    await flushPromises()

    // Click the small X badge on the upload tile to mark reset.
    const removeBtn = wrapper.find('button[title="Remove custom image"]')
    expect(removeBtn.exists()).toBe(true)
    await removeBtn.trigger('click')
    await flushPromises()

    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    await applyBtn.trigger('click')
    await flushPromises()

    expect(mockApi.delete).toHaveBeenCalledWith('/bird/American%20Robin/image')
    expect(mockApi.delete).toHaveBeenCalledWith('/bird/American%20Robin/wikimedia_choice')
    expect(wrapper.emitted('applied')[0][0]).toMatchObject({ kind: 'reset', hasCustomImage: false })
  })

  it('tiles render the thumbnail URL, not the full-resolution original', async () => {
    const wrapper = mountOpen()
    await flushPromises()

    const tileImgs = wrapper.findAll('img').filter(img =>
      img.attributes('src')?.startsWith('https://upload.wikimedia.org/thumb/')
    )
    expect(tileImgs.length).toBe(2)
    // No tile <img> should be loading the full-res original.
    const fullResTiles = wrapper.findAll('img').filter(img => {
      const src = img.attributes('src') || ''
      return src === 'https://upload.wikimedia.org/A.jpg' ||
             src === 'https://upload.wikimedia.org/B.jpg'
    })
    expect(fullResTiles.length).toBe(0)
  })

  it('apply dispatches a window bird-image:changed event with the new state', async () => {
    const listener = vi.fn()
    window.addEventListener('bird-image:changed', listener)
    try {
      const wrapper = mountOpen({ selectedFileTitle: 'File:A.jpg' })
      await flushPromises()

      const candidateButtons = wrapper.findAll('button').filter(b =>
        b.find('img[src^="https://upload.wikimedia.org/thumb/"]').exists()
      )
      await candidateButtons[1].trigger('click')
      await flushPromises()

      const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
      await applyBtn.trigger('click')
      await flushPromises()

      expect(listener).toHaveBeenCalledTimes(1)
      const detail = listener.mock.calls[0][0].detail
      expect(detail).toMatchObject({
        species: 'American Robin',
        kind: 'wikimedia',
        hasCustomImage: false,
        fileTitle: 'File:B.jpg',
        imageUrl: 'https://upload.wikimedia.org/B.jpg',
        thumbUrl: 'https://upload.wikimedia.org/thumb/B_400.jpg'
      })
    } finally {
      window.removeEventListener('bird-image:changed', listener)
    }
  })

  it('shows a friendly retry message when Wikimedia rate-limits the candidates request', async () => {
    mockApi.get.mockRejectedValueOnce({
      response: {
        status: 502,
        data: { error: 'Error fetching Wikimedia image: 429 Client Error: Too Many Requests for url: https://commons.wikimedia.org/...' }
      }
    })
    const wrapper = mountOpen()
    await flushPromises()

    expect(wrapper.text()).toContain('Wikimedia is temporarily rate-limiting')
    const retryBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Retry')
    expect(retryBtn).toBeTruthy()

    // Retry on the next click should re-issue the candidates fetch.
    mockApi.get.mockResolvedValueOnce({ data: { candidates: mockCandidates } })
    await retryBtn.trigger('click')
    await flushPromises()
    expect(mockApi.get).toHaveBeenCalledTimes(2)
  })

  it('rejects an oversize file with an inline error and disables Apply', async () => {
    const wrapper = mountOpen()
    await flushPromises()

    const big = new File([new Uint8Array(11 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [big] })
    await fileInput.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toMatch(/too large/i)
    const applyBtn = wrapper.findAll('button').find(b => b.text().trim() === 'Apply')
    expect(applyBtn.attributes('disabled')).toBeDefined()
  })
})
