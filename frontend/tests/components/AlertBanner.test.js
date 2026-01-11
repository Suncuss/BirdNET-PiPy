/**
 * Tests for AlertBanner component
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import AlertBanner from '@/components/AlertBanner.vue'

describe('AlertBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  const mountBanner = (props = {}) => mount(AlertBanner, {
    props: {
      message: 'Test error message',
      ...props
    }
  })

  describe('Rendering', () => {
    it('renders when message is provided', () => {
      const wrapper = mountBanner()
      expect(wrapper.text()).toContain('Test error message')
    })

    it('does not render when message is empty', () => {
      const wrapper = mountBanner({ message: '' })
      expect(wrapper.text()).not.toContain('Test error message')
      expect(wrapper.find('div').exists()).toBe(false)
    })

    it('shows dismiss button by default', () => {
      const wrapper = mountBanner()
      expect(wrapper.text()).toContain('Dismiss')
    })

    it('hides dismiss button when dismissible is false', () => {
      const wrapper = mountBanner({ dismissible: false })
      expect(wrapper.text()).not.toContain('Dismiss')
    })

    it('applies warning variant classes by default', () => {
      const wrapper = mountBanner()
      expect(wrapper.find('div').classes()).toContain('bg-amber-50')
      expect(wrapper.find('div').classes()).toContain('border-amber-200')
    })

    it('applies error variant classes', () => {
      const wrapper = mountBanner({ variant: 'error' })
      expect(wrapper.find('div').classes()).toContain('bg-red-50')
      expect(wrapper.find('div').classes()).toContain('border-red-200')
    })
  })

  describe('Dismiss functionality', () => {
    it('emits dismiss event when button clicked', async () => {
      const wrapper = mountBanner()
      await wrapper.find('button').trigger('click')
      expect(wrapper.emitted('dismiss')).toHaveLength(1)
    })

    it('auto-dismisses after default timeout (15s)', async () => {
      const wrapper = mountBanner()

      // Should not emit immediately
      expect(wrapper.emitted('dismiss')).toBeUndefined()

      // Advance time by 15 seconds
      vi.advanceTimersByTime(15000)

      expect(wrapper.emitted('dismiss')).toHaveLength(1)
    })

    it('auto-dismisses after custom timeout', async () => {
      const wrapper = mountBanner({ autoDismiss: 5000 })

      // Should not emit at 4 seconds
      vi.advanceTimersByTime(4000)
      expect(wrapper.emitted('dismiss')).toBeUndefined()

      // Should emit at 5 seconds
      vi.advanceTimersByTime(1000)
      expect(wrapper.emitted('dismiss')).toHaveLength(1)
    })

    it('does not auto-dismiss when autoDismiss is 0', async () => {
      const wrapper = mountBanner({ autoDismiss: 0 })

      // Advance time significantly
      vi.advanceTimersByTime(60000)

      expect(wrapper.emitted('dismiss')).toBeUndefined()
    })

    it('clears timer when manually dismissed', async () => {
      const wrapper = mountBanner()

      // Manually dismiss
      await wrapper.find('button').trigger('click')
      expect(wrapper.emitted('dismiss')).toHaveLength(1)

      // Advance time past auto-dismiss
      vi.advanceTimersByTime(20000)

      // Should still only have 1 dismiss event
      expect(wrapper.emitted('dismiss')).toHaveLength(1)
    })
  })
})
