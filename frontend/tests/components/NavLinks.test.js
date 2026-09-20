import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'
import NavLinks from '@/components/NavLinks.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/' })
}))

const mountNav = () => mount(NavLinks, {
  global: { stubs: { 'router-link': RouterLinkStub } },
  attachTo: document.body
})

// happy-dom has no layout, so give the strip a geometry by hand.
const setGeometry = (el, { scrollWidth, clientWidth, scrollLeft = 0 }) => {
  Object.defineProperty(el, 'scrollWidth', { configurable: true, value: scrollWidth })
  Object.defineProperty(el, 'clientWidth', { configurable: true, value: clientWidth })
  el.scrollLeft = scrollLeft
}

const chevrons = (wrapper) => wrapper.findAll('button').map((b) => b.isVisible())

describe('NavLinks', () => {
  it('renders all six destinations in order', () => {
    const wrapper = mountNav()
    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links.map((l) => l.text())).toEqual(
      ['Dashboard', 'Gallery', 'Live Feed', 'Charts', 'Table', 'Settings']
    )
    expect(links.map((l) => l.props('to'))).toEqual(
      ['/', '/gallery', '/live', '/charts', '/table', '/settings']
    )
    wrapper.unmount()
  })

  it('shows no chevrons or fades when the row fits', async () => {
    const wrapper = mountNav()
    await flushPromises()
    expect(chevrons(wrapper)).toEqual([false, false])
    expect(wrapper.find('.nav-strip').classes()).not.toContain('more-right')
    wrapper.unmount()
  })

  it('points right at rest, both ways mid-scroll, and left at the end', async () => {
    const wrapper = mountNav()
    const strip = wrapper.find('.nav-strip')

    setGeometry(strip.element, { scrollWidth: 560, clientWidth: 375 })
    await strip.trigger('scroll')
    expect(chevrons(wrapper)).toEqual([false, true])
    expect(strip.classes()).toContain('more-right')

    setGeometry(strip.element, { scrollWidth: 560, clientWidth: 375, scrollLeft: 90 })
    await strip.trigger('scroll')
    expect(chevrons(wrapper)).toEqual([true, true])

    setGeometry(strip.element, { scrollWidth: 560, clientWidth: 375, scrollLeft: 185 })
    await strip.trigger('scroll')
    expect(chevrons(wrapper)).toEqual([true, false])
    expect(strip.classes()).not.toContain('more-right')
    wrapper.unmount()
  })

  it('keeps every phone-only style below sm, so wider screens get the plain row', () => {
    const wrapper = mountNav()
    const plain = ['nav-link', 'relative', 'shrink-0', 'hover:text-green-200']

    for (const link of wrapper.findAllComponents(RouterLinkStub)) {
      const styled = link.classes().filter((c) => !plain.includes(c))
      expect(styled.length).toBeGreaterThan(0)
      expect(styled.every((c) => c.startsWith('max-sm:'))).toBe(true)
    }
    // ...and from sm up the row wraps with the original spacing
    expect(wrapper.find('.nav-strip').classes()).toEqual(
      expect.arrayContaining(['sm:flex-wrap', 'sm:gap-4'])
    )
  })

  it('keeps the chevrons out of the tab order', () => {
    const wrapper = mountNav()
    for (const button of wrapper.findAll('button')) {
      expect(button.attributes('tabindex')).toBe('-1')
    }
    wrapper.unmount()
  })
})
