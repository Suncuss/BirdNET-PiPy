/**
 * Tests for AppTimeSelect — the Quiet Hours clock picker, an AppListbox over the
 * half-hour grid.
 *
 * What matters here (the rest is AppListbox's job):
 *   - the model stays a strict 24-hour "HH:MM" string whatever the labels show;
 *   - labels follow the 12/24-hour preference — the reason this is not a native
 *     <input type="time">;
 *   - an off-grid stored value is still listed and stays selected.
 * The "HH:MM" -> label conversion is `formatClock`, covered in quietHours.test.js.
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { clock12, clock24 } from '../helpers/clock'

const hour12 = ref(false)

vi.mock('@/composables/useTimeFormat', () => ({
  useTimeFormat: () => ({
    hour12,
    formatTime: (date) => (hour12.value ? clock12(date) : clock24(date))
  })
}))

import AppTimeSelect from '@/components/AppTimeSelect.vue'

const mountSelect = (props = {}, options = {}) =>
  mount(AppTimeSelect, { props: { modelValue: '22:00', ...props }, attachTo: document.body, ...options })

const trigger = (w) => w.find('button[aria-haspopup="listbox"]')
const optionEls = (w) => w.findAll('li[role="option"]')
const labels = (w) => optionEls(w).map(o => o.text())

describe('AppTimeSelect', () => {
  beforeEach(() => {
    hour12.value = false
  })

  describe('labels follow the time-format preference', () => {
    it('shows the selected time in 24-hour form', () => {
      expect(trigger(mountSelect()).text()).toContain('22:00')
    })

    it('shows the selected time in 12-hour form', () => {
      hour12.value = true
      expect(trigger(mountSelect()).text()).toContain('10:00 PM')
    })
  })

  describe('options', () => {
    it('offers every whole hour of the day', async () => {
      const w = mountSelect()
      await trigger(w).trigger('click')
      const texts = labels(w)
      expect(texts).toHaveLength(24)
      expect(texts[0]).toBe('00:00')
      expect(texts[1]).toBe('01:00')
      expect(texts.at(-1)).toBe('23:00')
    })

    it('lists a stored time that is off the hour (e.g. an old half-hour value), in order', async () => {
      const w = mountSelect({ modelValue: '22:30' })
      await trigger(w).trigger('click')
      const texts = labels(w)
      expect(texts).toHaveLength(25)
      expect(texts.indexOf('22:30')).toBe(texts.indexOf('22:00') + 1)
    })

    it('keeps an off-grid time as the selection on the trigger', () => {
      expect(trigger(mountSelect({ modelValue: '22:30' })).text()).toContain('22:30')
    })
  })

  describe('selection', () => {
    it('emits the 24-hour string and a change on pick, even in 12-hour display', async () => {
      hour12.value = true
      const w = mountSelect()
      await trigger(w).trigger('click')
      // First option, shown as "12:00 AM" — the emitted value stays 24-hour.
      await optionEls(w)[0].trigger('click')
      expect(w.emitted('update:modelValue')).toEqual([['00:00']])
      expect(w.emitted('change')).toEqual([['00:00']])
    })

    it('emits each event once, not once per forwarding layer', async () => {
      const w = mountSelect()
      await trigger(w).trigger('click')
      await optionEls(w)[1].trigger('click')
      expect(w.emitted('update:modelValue')).toEqual([['01:00']])
      expect(w.emitted('change')).toEqual([['01:00']])
    })
  })

  it('disables the field when it is locked', () => {
    expect(trigger(mountSelect({ disabled: true })).attributes('disabled')).toBeDefined()
  })

  it('passes an id down to the trigger so an external <label for> keeps working', () => {
    const w = mountSelect({}, { attrs: { id: 'quietHoursStart' } })
    expect(trigger(w).attributes('id')).toBe('quietHoursStart')
  })
})
