/**
 * Tests for DetectionActions — the per-row action buttons. The info control is a
 * real link to the detection's detail page, but a plain click opens it in-place
 * (emits show-detail) while modified clicks fall through to the link. Play /
 * spectrogram / delete emit to the parent.
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import DetectionActions from '@/components/DetectionActions.vue'
import { BASE } from '@/services/baseUrl'

const detection = {
  id: 42,
  common_name: 'American Robin',
  scientific_name: 'Turdus migratorius',
  timestamp: '2024-01-15T10:30:00',
  confidence: 0.9,
  audio_filename: 'robin.mp3',
  spectrogram_filename: 'robin.webp'
}

const mountComponent = (props = {}) =>
  mount(DetectionActions, {
    props: { detection, ...props },
    // Stub the icon so the test doesn't depend on FA icon registration.
    global: { stubs: { 'font-awesome-icon': true } }
  })

const infoLink = (wrapper) => wrapper.find('a[title="Detection info"]')

describe('DetectionActions', () => {
  it('points the info link at the standalone detail page', () => {
    const wrapper = mountComponent()
    expect(infoLink(wrapper).attributes('href')).toBe(
      `${BASE}bird/American%20Robin/recording/42`
    )
  })

  it('opens the detail in-place on a plain click (emits show-detail, no nav)', async () => {
    const wrapper = mountComponent()
    await infoLink(wrapper).trigger('click')

    expect(wrapper.emitted('show-detail')[0]).toEqual([detection])
  })

  it('lets a modified click fall through to the link instead of emitting', async () => {
    const wrapper = mountComponent()
    await infoLink(wrapper).trigger('click', { metaKey: true })

    expect(wrapper.emitted('show-detail')).toBeUndefined()
  })

  it('emits toggle-play with the detection', async () => {
    const wrapper = mountComponent()
    await wrapper.find('button[title="Play"]').trigger('click')

    expect(wrapper.emitted('toggle-play')[0]).toEqual([detection])
  })

  it('emits spectrogram with the detection', async () => {
    const wrapper = mountComponent()
    await wrapper.find('button[title="View spectrogram"]').trigger('click')

    expect(wrapper.emitted('spectrogram')[0]).toEqual([detection])
  })

  it('emits delete with the detection', async () => {
    const wrapper = mountComponent()
    await wrapper.find('button[title="Delete"]').trigger('click')

    expect(wrapper.emitted('delete')[0]).toEqual([detection])
  })

  it('hides the delete button when hideDelete is set', () => {
    const wrapper = mountComponent({ hideDelete: true })

    expect(wrapper.find('button[title="Delete"]').exists()).toBe(false)
  })
})
