/**
 * Tests for DetectionPlayer.vue — the shared detection detail player used by the
 * standalone permalink page and the in-table modal. Covers the Share button,
 * which copies a permalink to this recording (relocated here from the per-card
 * SpectrogramPlayer in the detail-page redesign).
 */
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import DetectionPlayer from '@/components/DetectionPlayer.vue'
import api from '@/services/api'
import { copyText } from '@/utils/clipboard'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn() }
}))

vi.mock('@/utils/clipboard', () => ({
  copyText: vi.fn().mockResolvedValue(true)
}))

const recording = {
  id: 42,
  common_name: 'American Robin',
  display_common_name: 'American Robin',
  scientific_name: 'Turdus migratorius',
  confidence: 0.91,
  timestamp: '2026-06-01T08:15:00',
  audio_filename: 'robin.mp3',
  has_media: true,
  extra: {}
}

const mountPlayer = () =>
  mount(DetectionPlayer, {
    props: { name: 'American Robin', id: 42 },
    global: {
      stubs: { 'font-awesome-icon': true, 'router-link': RouterLinkStub, Spinner: true }
    }
  })

describe('DetectionPlayer share button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    copyText.mockResolvedValue(true)
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

  it('copies the recording permalink (from common_name) and confirms when Share is clicked', async () => {
    const wrapper = mountPlayer()
    await flushPromises()

    await wrapper.find('button[title="Copy share link"]').trigger('click')
    await flushPromises()

    expect(copyText).toHaveBeenCalledTimes(1)
    expect(copyText.mock.calls[0][0]).toContain('/bird/American%20Robin/recording/42')
    expect(wrapper.find('button[title="Link copied"]').exists()).toBe(true)
  })
})
