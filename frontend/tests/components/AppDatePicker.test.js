/**
 * Tests for AppDatePicker.
 *
 * Locks in behaviors users have already hit regressions on:
 *   - The PrimeVue date-format follows the time-format preference
 *     (12h → mm/dd/yy, 24h → yy-mm-dd).
 *   - The root width class adapts to the chosen format so neither layout
 *     clips the ISO year nor pads the MM/DD/YYYY box.
 *   - The `fluid` prop switches to a mobile-friendly fill-parent layout
 *     while keeping the natural fixed width at the sm breakpoint, so the
 *     Table.vue From/To row stretches edge-to-edge on phones.
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const hour12 = ref(true)

vi.mock('@/composables/useTimeFormat', () => ({
  useTimeFormat: () => ({ hour12 })
}))

// Stub PrimeVue's DatePicker so we can inspect the props AppDatePicker passes
// it without rendering its internals (and without pulling PrimeVue's styles).
vi.mock('primevue/datepicker', () => ({
  default: {
    name: 'DatePicker',
    props: ['modelValue', 'disabled', 'minDate', 'maxDate', 'dateFormat', 'showIcon', 'iconDisplay', 'pt'],
    emits: ['update:modelValue', 'date-select'],
    template: '<div class="datepicker-stub" :data-date-format="dateFormat" :data-root-class="pt && pt.root && pt.root.class"></div>'
  }
}))

import AppDatePicker from '@/components/AppDatePicker.vue'

const mountPicker = (props = {}) => mount(AppDatePicker, { props })

describe('AppDatePicker', () => {
  beforeEach(() => {
    hour12.value = true
  })

  describe('date-format follows time-format preference', () => {
    it('uses mm/dd/yy when the user is on 12-hour time', () => {
      hour12.value = true
      const wrapper = mountPicker()
      expect(wrapper.find('.datepicker-stub').attributes('data-date-format')).toBe('mm/dd/yy')
    })

    it('uses ISO yy-mm-dd when the user is on 24-hour time', () => {
      hour12.value = false
      const wrapper = mountPicker()
      expect(wrapper.find('.datepicker-stub').attributes('data-date-format')).toBe('yy-mm-dd')
    })

    it('reactively updates the date-format when the preference flips', async () => {
      hour12.value = true
      const wrapper = mountPicker()
      expect(wrapper.find('.datepicker-stub').attributes('data-date-format')).toBe('mm/dd/yy')

      hour12.value = false
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.datepicker-stub').attributes('data-date-format')).toBe('yy-mm-dd')
    })
  })

  describe('root width adapts to the date format', () => {
    it('renders 140px wide for MM/DD/YYYY (12h)', () => {
      hour12.value = true
      const wrapper = mountPicker()
      const rootClass = wrapper.find('.datepicker-stub').attributes('data-root-class')
      expect(rootClass).toContain('inline-block')
      expect(rootClass).toContain('w-[140px]')
      expect(rootClass).not.toContain('w-[150px]')
    })

    it('renders 150px wide for ISO YYYY-MM-DD (24h) so the leading year clears the calendar icon', () => {
      hour12.value = false
      const wrapper = mountPicker()
      const rootClass = wrapper.find('.datepicker-stub').attributes('data-root-class')
      expect(rootClass).toContain('inline-block')
      expect(rootClass).toContain('w-[150px]')
      expect(rootClass).not.toContain('w-[140px]')
    })
  })

  describe('fluid mode', () => {
    it('defaults to a fixed inline-block width (no w-full)', () => {
      hour12.value = false
      const wrapper = mountPicker()
      const rootClass = wrapper.find('.datepicker-stub').attributes('data-root-class')
      expect(rootClass).not.toContain('w-full')
      expect(rootClass).not.toContain('block w-full')
    })

    it('fills the parent on mobile and reverts to the natural width at sm — 12h', () => {
      hour12.value = true
      const wrapper = mountPicker({ fluid: true })
      const rootClass = wrapper.find('.datepicker-stub').attributes('data-root-class')
      expect(rootClass).toContain('block w-full')
      expect(rootClass).toContain('sm:inline-block')
      expect(rootClass).toContain('sm:w-[140px]')
    })

    it('fills the parent on mobile and reverts to the natural width at sm — 24h', () => {
      hour12.value = false
      const wrapper = mountPicker({ fluid: true })
      const rootClass = wrapper.find('.datepicker-stub').attributes('data-root-class')
      expect(rootClass).toContain('block w-full')
      expect(rootClass).toContain('sm:inline-block')
      expect(rootClass).toContain('sm:w-[150px]')
    })
  })
})
