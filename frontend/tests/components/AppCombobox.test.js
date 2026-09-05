/**
 * Tests for AppCombobox — the shared search-and-select field behind the Table
 * and Charts species pickers.
 *
 * What matters here is the unified behaviour those two copies didn't share:
 *   - the committed value shows as text, and focus lists everything (not just
 *     the current match) so you can browse;
 *   - typing filters; picking commits the whole option object;
 *   - the ✕ clears; blur/Escape without a pick restores the committed value;
 *   - selection works by keyboard (arrow + Enter), which the mousedown-only
 *     originals did not.
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import AppCombobox from '@/components/AppCombobox.vue'

const OPTIONS = [
  { id: 'robin', name: 'American Robin' },
  { id: 'jay', name: 'Blue Jay' },
  { id: 'crow', name: 'American Crow' }
]

const mountBox = (props = {}) =>
  mount(AppCombobox, {
    props: {
      options: OPTIONS,
      getLabel: (o) => o.name,
      optionKey: (o) => o.id,
      placeholder: 'All species',
      ...props
    },
    attachTo: document.body
  })

const input = (w) => w.find('input[role="combobox"]')
const optionTexts = (w) => w.findAll('li[role="option"]').map(o => o.text())
const options = (w) => w.findAll('li[role="option"]')

describe('AppCombobox', () => {
  describe('display', () => {
    it('shows the placeholder and no committed text when nothing is selected', () => {
      const w = mountBox()
      expect(input(w).element.value).toBe('')
      expect(input(w).attributes('placeholder')).toBe('All species')
    })

    it('shows the selected option as normal text', () => {
      const w = mountBox({ modelValue: OPTIONS[0] })
      expect(input(w).element.value).toBe('American Robin')
    })
  })

  describe('opening and filtering', () => {
    it('lists every option on focus', async () => {
      const w = mountBox()
      await input(w).trigger('focus')
      expect(optionTexts(w)).toEqual(['American Robin', 'Blue Jay', 'American Crow'])
    })

    it('lists all options on focus even with a value selected, so you can browse', async () => {
      const w = mountBox({ modelValue: OPTIONS[1] })
      await input(w).trigger('focus')
      expect(optionTexts(w)).toHaveLength(3)
    })

    it('filters by the default label substring, case-insensitively', async () => {
      const w = mountBox()
      await input(w).setValue('american')
      expect(optionTexts(w)).toEqual(['American Robin', 'American Crow'])
    })

    it('uses a supplied filter over the label default', async () => {
      // Match on id instead of label.
      const w = mountBox({ filter: (o, q) => o.id.includes(q) })
      await input(w).setValue('jay')
      expect(optionTexts(w)).toEqual(['Blue Jay'])
    })

    it('shows the empty-text when nothing matches', async () => {
      const w = mountBox({ emptyText: 'No species found' })
      await input(w).setValue('zzz')
      expect(w.find('li').text()).toBe('No species found')
    })
  })

  describe('selection', () => {
    it('emits the whole option object on click and shows its label', async () => {
      const w = mountBox()
      await input(w).trigger('focus')
      await options(w)[1].trigger('mousedown')

      expect(w.emitted('update:modelValue')[0]).toEqual([OPTIONS[1]])
      expect(w.emitted('change')[0]).toEqual([OPTIONS[1]])
    })

    it('selects the arrow-highlighted option with Enter', async () => {
      const w = mountBox()
      await input(w).trigger('focus')
      await input(w).trigger('keydown', { key: 'ArrowDown' })
      await input(w).trigger('keydown', { key: 'ArrowDown' })  // -> Blue Jay
      await input(w).trigger('keydown', { key: 'Enter' })

      expect(w.emitted('update:modelValue')[0]).toEqual([OPTIONS[1]])
    })
  })

  describe('clearing and restoring', () => {
    it('clears to null via the ✕ button', async () => {
      const w = mountBox({ modelValue: OPTIONS[0] })
      const clear = w.find('button[aria-label="Clear selection"]')
      expect(clear.exists()).toBe(true)
      await clear.trigger('mousedown')
      expect(w.emitted('update:modelValue')[0]).toEqual([null])
    })

    it('has no ✕ when nothing is selected', () => {
      expect(mountBox().find('button[aria-label="Clear selection"]').exists()).toBe(false)
    })

    it('restores the committed label on Escape after typing without picking', async () => {
      const w = mountBox({ modelValue: OPTIONS[0] })
      await input(w).trigger('focus')
      await input(w).setValue('blah')
      await input(w).trigger('keydown', { key: 'Escape' })
      expect(input(w).element.value).toBe('American Robin')
      expect(w.emitted('update:modelValue')).toBeUndefined()
    })
  })

  describe('sizing and state', () => {
    it('is 40px by default and 36px at size sm', () => {
      expect(input(mountBox()).classes()).toContain('h-10')
      expect(input(mountBox({ size: 'sm' })).classes()).toContain('h-9')
    })

    it('disables the input and hides the clear button when disabled', () => {
      const w = mountBox({ modelValue: OPTIONS[0], disabled: true })
      expect(input(w).attributes('disabled')).toBeDefined()
      expect(w.find('button[aria-label="Clear selection"]').exists()).toBe(false)
    })
  })
})
