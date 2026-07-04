/**
 * Tests for SpectrogramPlayer.vue — the spectrogram-as-scrubber player
 * (play/pause, seek, download, and a detail-page link) used by the BirdDetails
 * recordings cards. Sharing lives on the detail page (DetectionPlayer), not here.
 */
import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import SpectrogramPlayer from '@/components/SpectrogramPlayer.vue'

const recording = {
  id: 42,
  common_name: 'American Robin',
  audio_filename: 'robin.mp3',
  spectrogram_filename: 'robin.webp'
}

const mountPlayer = (props = {}) =>
  mount(SpectrogramPlayer, {
    props: { recording, ...props },
    global: { stubs: { 'font-awesome-icon': true, 'router-link': RouterLinkStub } }
  })

describe('SpectrogramPlayer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the spectrogram and audio from the recording filenames', () => {
    const wrapper = mountPlayer()
    expect(wrapper.find('img').attributes('src')).toContain('robin.webp')
    expect(wrapper.find('audio').attributes('src')).toContain('robin.mp3')
  })

  it('links to the detection detail page for this recording', () => {
    const wrapper = mountPlayer()
    const link = wrapper.findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({
      name: 'BirdRecording',
      params: { name: 'American Robin', id: 42 }
    })
  })

  it('offers a download link to the recording audio', () => {
    const wrapper = mountPlayer()
    const download = wrapper.find('a[title="Download audio"]')
    expect(download.exists()).toBe(true)
    expect(download.attributes('href')).toContain('robin.mp3')
    expect(download.attributes('download')).toBe('robin.mp3')
  })

  it('renders a seek bar (not an overlay on the non-time-faithful spectrogram)', () => {
    const wrapper = mountPlayer()
    expect(wrapper.find('input[type="range"]').exists()).toBe(true)
  })

  it('emits "expand" when the spectrogram image is clicked', async () => {
    const wrapper = mountPlayer()
    await wrapper.find('.cursor-zoom-in').trigger('click')
    expect(wrapper.emitted('expand')).toHaveLength(1)
  })

  it('does not make the spectrogram clickable-to-expand when showExpand is false', async () => {
    const wrapper = mountPlayer({ showExpand: false })
    expect(wrapper.find('.cursor-zoom-in').exists()).toBe(false)

    await wrapper.find('img').trigger('click')
    expect(wrapper.emitted('expand')).toBeUndefined()
  })
})
