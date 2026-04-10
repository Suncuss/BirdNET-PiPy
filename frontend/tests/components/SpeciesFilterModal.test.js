import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SpeciesFilterModal from '@/components/SpeciesFilterModal.vue'

const mockApi = vi.hoisted(() => ({
  get: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

const mockSpecies = [
  { common_name: 'American Robin', display_common_name: 'Amsel', scientific_name: 'Turdus migratorius' },
  { common_name: 'Blue Jay', display_common_name: 'Blauhaeher', scientific_name: 'Cyanocitta cristata' }
]

const mountModal = (props = {}) => mount(SpeciesFilterModal, {
  props: {
    title: 'Allowed Species',
    description: 'Pick species',
    modelValue: [],
    speciesList: mockSpecies,
    ...props
  }
})

describe('SpeciesFilterModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('closes after successful save and clears saving state', async () => {
    let resolveSave
    const onSave = vi.fn(() => new Promise((resolve) => {
      resolveSave = resolve
    }))
    const wrapper = mountModal({
      modelValue: ['Turdus migratorius'],
      onSave
    })

    await flushPromises()

    const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save')
    await saveButton.trigger('click')
    await wrapper.vm.$nextTick()

    expect(onSave).toHaveBeenCalledWith(['Turdus migratorius'])
    expect(wrapper.text()).toContain('Saving...')

    resolveSave()
    await flushPromises()

    expect(wrapper.vm.saving).toBe(false)
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('shows error and keeps modal open when save fails', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('save failed'))
    const wrapper = mountModal({
      modelValue: ['Turdus migratorius'],
      onSave
    })

    await flushPromises()

    const saveButton = wrapper.findAll('button').find(btn => btn.text() === 'Save')
    await saveButton.trigger('click')
    await flushPromises()

    expect(wrapper.vm.saving).toBe(false)
    expect(wrapper.text()).toContain('Failed to save. Please try again.')
    expect(wrapper.emitted('close')).toBeFalsy()
  })

  it('renders and searches localized display names', async () => {
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.text()).toContain('Amsel')

    await wrapper.find('input[type="text"]').setValue('Blau')
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.filteredSpecies).toHaveLength(1)
    expect(wrapper.vm.filteredSpecies[0].common_name).toBe('Blue Jay')
  })
})
