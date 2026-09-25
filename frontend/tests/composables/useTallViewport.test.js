import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { useTallViewport, ACTIVITY_ROWS } from '@/composables/useTallViewport'
import { stubViewportTier } from '../helpers/viewportTier'

const mountWithTier = () => {
  let tier
  const wrapper = mount({
    setup() {
      tier = useTallViewport()
      return () => null
    }
  })
  return { wrapper, tier }
}

describe('useTallViewport', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('gates the tall tier on lg width and the tall-viewport height', () => {
    stubViewportTier(false)
    mountWithTier()
    expect(window.matchMedia).toHaveBeenCalledWith(
      '(min-width: 1024px) and (min-height: 1150px)'
    )
  })

  it('starts from the current match and follows tier flips', () => {
    const mql = stubViewportTier(true)
    const { tier } = mountWithTier()
    expect(tier.isTallViewport.value).toBe(true)

    mql.dispatch(false)
    expect(tier.isTallViewport.value).toBe(false)
  })

  it('removes its media-query listener on unmount', () => {
    const mql = stubViewportTier(false)
    const { wrapper } = mountWithTier()
    expect(mql.listenerCount).toBe(1)

    wrapper.unmount()
    expect(mql.listenerCount).toBe(0)
  })

  it('shows more species on the tall tier', () => {
    expect(ACTIVITY_ROWS.tall).toBeGreaterThan(ACTIVITY_ROWS.base)
  })
})
