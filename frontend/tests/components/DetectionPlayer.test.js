/**
 * Tests for DetectionPlayer.vue — the shared detection detail player used by the
 * standalone permalink page and the in-table modal. Covers the Share button
 * (owner mints a scoped token; anonymous re-shares a detection permalink; mint
 * failure surfaces instead of faking success) and that a share-link viewer
 * requests media with the token plus the payload signature as a fallback.
 */
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import DetectionPlayer from '@/components/DetectionPlayer.vue'
import api from '@/services/api'
import { copyText } from '@/utils/clipboard'

// Controllable auth state for the share branches (owner vs anonymous).
const { authState } = vi.hoisted(() => ({ authState: { value: true } }))

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() }
}))

vi.mock('@/utils/clipboard', () => ({
  copyText: vi.fn().mockResolvedValue(true)
}))

vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: authState })
}))

const recording = {
  id: 42,
  common_name: 'American Robin',
  display_common_name: 'American Robin',
  scientific_name: 'Turdus migratorius',
  confidence: 0.91,
  timestamp: '2026-06-01T08:15:00',
  audio_filename: 'robin.mp3',
  audio_sig: 'exp=999&sig=abc',
  has_media: true,
  extra: {}
}

const mountPlayer = (props = {}) =>
  mount(DetectionPlayer, {
    props: { name: 'American Robin', id: 42, ...props },
    global: {
      stubs: { 'font-awesome-icon': true, 'router-link': RouterLinkStub, Spinner: true }
    }
  })

const clickShare = async (wrapper) => {
  await wrapper.find('button[title="Copy share link"]').trigger('click')
  await flushPromises()
}

describe('DetectionPlayer share button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.value = true
    copyText.mockResolvedValue(true)
    api.post.mockResolvedValue({ data: { token: 'sharetok123' } })
    api.get.mockImplementation((url) =>
      url.includes('/recording/')
        ? Promise.resolve({ data: recording })
        : Promise.resolve({ data: {} })
    )
    // Web Audio isn't available in the test DOM; keep loadAudio's fetch off the
    // network — the Share button renders off has_media, not the audio state.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no audio in tests')))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('owner: mints a scoped token and copies the tokenized permalink', async () => {
    const wrapper = mountPlayer()
    await flushPromises()
    await clickShare(wrapper)

    expect(api.post).toHaveBeenCalledWith('/detections/42/share')
    expect(copyText).toHaveBeenCalledTimes(1)
    expect(copyText.mock.calls[0][0]).toContain('/bird/American%20Robin/recording/42')
    expect(copyText.mock.calls[0][0]).toContain('?s=sharetok123')
    expect(wrapper.find('button[title="Link copied"]').exists()).toBe(true)
  })

  it('owner: surfaces failure (no fake "Copied") when minting fails', async () => {
    api.post.mockRejectedValue(new Error('mint failed'))
    const wrapper = mountPlayer()
    await flushPromises()
    await clickShare(wrapper)

    expect(copyText).not.toHaveBeenCalled()
    expect(wrapper.find('button[title="Link copied"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Failed')
  })

  it('anonymous in-table modal (no token): copies a detection permalink, not the page URL, and does not mint', async () => {
    authState.value = false
    const wrapper = mountPlayer()  // no shareToken -> the in-table-modal case
    await flushPromises()
    await clickShare(wrapper)

    expect(api.post).not.toHaveBeenCalled()
    expect(copyText).toHaveBeenCalledTimes(1)
    expect(copyText.mock.calls[0][0]).toContain('/bird/American%20Robin/recording/42')
    expect(copyText.mock.calls[0][0]).not.toContain('?s=')
  })

  it('anonymous with a share token: re-shares the tokenized permalink', async () => {
    authState.value = false
    const wrapper = mountPlayer({ shareToken: 'tok-xyz' })
    await flushPromises()
    await clickShare(wrapper)

    expect(api.post).not.toHaveBeenCalled()
    expect(copyText.mock.calls[0][0]).toContain('?s=tok-xyz')
  })

  it('share-link viewer requests audio with the token AND the payload signature (fallback)', async () => {
    const wrapper = mountPlayer({ shareToken: 'tok-xyz' })
    await flushPromises()

    const href = wrapper.find('a[title="Download original audio"]').attributes('href')
    expect(href).toContain('s=tok-xyz')
    expect(href).toContain('sig=abc')
  })
})
