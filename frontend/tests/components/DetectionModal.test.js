/**
 * Tests for DetectionModal — the dismiss behaviour (outside-click, Esc, close
 * button) and that a click on the card itself does not close it. The player body
 * is stubbed out so this stays focused on the modal shell.
 */
import { mount, enableAutoUnmount } from '@vue/test-utils'
import { describe, it, expect, afterEach } from 'vitest'
import DetectionModal from '@/components/DetectionModal.vue'

enableAutoUnmount(afterEach)
afterEach(() => { document.body.style.overflow = '' })

// Render the teleported content inline so it can be queried from the wrapper.
const TeleportStub = { name: 'Teleport', template: '<div><slot /></div>', props: ['to'] }

const mountModal = (props = {}) =>
  mount(DetectionModal, {
    props: { isVisible: true, name: 'American Robin', id: 1, ...props },
    global: {
      stubs: {
        Teleport: TeleportStub,
        DetectionPlayer: true,
        CloseIcon: true
      }
    }
  })

describe('DetectionModal', () => {
  it('closes when clicking the area around the card', async () => {
    const wrapper = mountModal()
    await wrapper.find('.min-h-full').trigger('click')

    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('does not close when the click originates on the card', async () => {
    const wrapper = mountModal()
    await wrapper.find('.bg-white').trigger('click')

    expect(wrapper.emitted('close')).toBeFalsy()
  })

  it('closes on the close button', async () => {
    const wrapper = mountModal()
    await wrapper.find('button[title="Close"]').trigger('click')

    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('closes on Escape', async () => {
    const wrapper = mountModal()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders nothing while hidden', () => {
    const wrapper = mountModal({ isVisible: false })

    expect(wrapper.find('.bg-white').exists()).toBe(false)
  })
})
