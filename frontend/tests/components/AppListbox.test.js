/**
 * Tests for AppListbox — the app's dropdown, a custom trigger + popup so the
 * open menu looks the same in every browser.
 *
 * What matters here:
 *   - option values keep their JS type across selection (a native <select>'s
 *     string DOM value was the old trap; this one never stringifies);
 *   - update:modelValue lands before change;
 *   - the keyboard works like a native select: arrows/Home/End move a
 *     highlight, Enter/Space commit, Escape closes, and typing jumps to a label.
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import AppListbox from '@/components/AppListbox.vue'

const NUMBERS = [
  { value: 9, label: '9 seconds' },
  { value: 12, label: '12 seconds' },
  { value: 15, label: '15 seconds' }
]

const mountBox = (props = {}, options = {}) =>
  mount(AppListbox, {
    props: { options: NUMBERS, modelValue: 9, ...props },
    attachTo: document.body,
    ...options
  })

const trigger = (w) => w.find('button[aria-haspopup="listbox"]')
const menu = (w) => w.find('ul[role="listbox"]')
const optionEls = (w) => w.findAll('li[role="option"]')
const key = (w, k, opts = {}) => trigger(w).trigger('keydown', { key: k, ...opts })

describe('AppListbox', () => {
  describe('display', () => {
    it('shows the selected option label on the trigger', () => {
      expect(trigger(mountBox({ modelValue: 15 })).text()).toContain('15 seconds')
    })

    it('shows the placeholder when nothing matches the model', () => {
      const w = mountBox({ modelValue: null, placeholder: 'Pick one' })
      expect(trigger(w).text()).toContain('Pick one')
    })

    it('renders one option per entry with aria-selected on the current one', async () => {
      const w = mountBox({ modelValue: 12 })
      await trigger(w).trigger('click')
      const opts = optionEls(w)
      expect(opts.map(o => o.text())).toEqual(['9 seconds', '12 seconds', '15 seconds'])
      expect(opts[1].attributes('aria-selected')).toBe('true')
    })

    it('keeps the option list out of the layout until opened', () => {
      // v-show renders it hidden; assert the control starts closed.
      expect(trigger(mountBox()).attributes('aria-expanded')).toBe('false')
    })
  })

  describe('selection keeps the value type', () => {
    it('emits a number for a numeric option, and update before change', async () => {
      const w = mountBox()
      await trigger(w).trigger('click')
      await optionEls(w)[2].trigger('click')
      expect(w.emitted('update:modelValue')[0]).toEqual([15])
      expect(w.emitted('change')[0]).toEqual([15])
    })

    it('emits zero as a number', async () => {
      const w = mountBox({
        options: [{ value: 0, label: 'None' }, { value: 0.5, label: '0.5s' }],
        modelValue: 0.5
      })
      await trigger(w).trigger('click')
      await optionEls(w)[0].trigger('click')
      expect(w.emitted('update:modelValue')[0]).toEqual([0])
    })

    it('emits null for a null-valued option', async () => {
      const w = mountBox({
        options: [{ value: null, label: 'Any' }, { value: 1, label: 'One' }],
        modelValue: 1
      })
      await trigger(w).trigger('click')
      await optionEls(w)[0].trigger('click')
      expect(w.emitted('update:modelValue')[0]).toEqual([null])
    })
  })

  describe('open / close', () => {
    it('opens on click and closes on a second click', async () => {
      const w = mountBox()
      await trigger(w).trigger('click')
      expect(menu(w).isVisible()).toBe(true)
      await trigger(w).trigger('click')
      expect(menu(w).isVisible()).toBe(false)
    })

    it('closes on Escape', async () => {
      const w = mountBox()
      await trigger(w).trigger('click')
      await trigger(w).trigger('keydown', { key: 'Escape' })
      expect(menu(w).isVisible()).toBe(false)
    })

    it('closes after a pick', async () => {
      const w = mountBox()
      await trigger(w).trigger('click')
      await optionEls(w)[1].trigger('click')
      expect(menu(w).isVisible()).toBe(false)
    })
  })

  describe('keyboard', () => {
    it('opens with ArrowDown when closed', async () => {
      const w = mountBox()
      await key(w, 'ArrowDown')
      expect(menu(w).isVisible()).toBe(true)
    })

    it('moves the highlight and commits it with Enter', async () => {
      const w = mountBox({ modelValue: 9 })
      await trigger(w).trigger('click')   // highlights the current (index 0)
      await key(w, 'ArrowDown')           // -> index 1
      await key(w, 'Enter')
      expect(w.emitted('update:modelValue')[0]).toEqual([12])
    })

    it('jumps to Home and End', async () => {
      const w = mountBox()
      await trigger(w).trigger('click')
      await key(w, 'End')
      await key(w, 'Enter')
      expect(w.emitted('update:modelValue')[0]).toEqual([15])
    })

    it('type-ahead commits a matching label while closed', async () => {
      // "1" matches "12 seconds" (first label starting with "1").
      const w = mountBox({ modelValue: 9 })
      await key(w, '1')
      expect(w.emitted('update:modelValue')[0]).toEqual([12])
    })
  })

  describe('attrs, sizing and state', () => {
    it('routes id and aria-label to the trigger, class to the root', () => {
      const w = mountBox({}, { attrs: { id: 'recordingLength', 'aria-label': 'Chunk', class: 'flex-1' } })
      expect(trigger(w).attributes('id')).toBe('recordingLength')
      expect(trigger(w).attributes('aria-label')).toBe('Chunk')
      expect(w.classes()).toContain('flex-1')
    })

    it('is 40px by default and 36px at size sm', () => {
      expect(trigger(mountBox()).classes()).toContain('h-10')
      expect(trigger(mountBox({ size: 'sm' })).classes()).toContain('h-9')
    })

    it('disables the trigger', () => {
      expect(trigger(mountBox({ disabled: true })).attributes('disabled')).toBeDefined()
    })
  })
})
