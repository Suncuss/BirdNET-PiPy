import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FormatDriveModal from '@/components/FormatDriveModal.vue'

const mockApi = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/services/api', () => ({ default: mockApi }))
beforeEach(() => {
  mockApi.post.mockReset()
  mockApi.post.mockResolvedValue({ data: { id: 'synthetic-job', state: 'queued' } })
})

enableAutoUnmount(afterEach)
const mountDialog = () => mount(FormatDriveModal, {
  attachTo: document.body,
  props: { drive: { name: 'BIRDSTORE', path: '/dev/sda', device_id: 'synthetic-device' }, sizeLabel: '500 GB' }
})

describe('Format drive confirmation', () => {
  it('requires the exact drive name before submitting a real formatting request', async () => {
    const wrapper = mountDialog()
    expect(wrapper.get('dialog').attributes('open')).toBeDefined()
    expect(wrapper.text()).toContain('BIRDSTORE · 500 GB')
    expect(wrapper.text()).toContain('/dev/sda')
    expect(wrapper.text()).toContain('Formatting will erase all data on this drive.')
    expect(wrapper.text()).toContain('ext4')
    const input = wrapper.get('input')
    const check = wrapper.findAll('button').find(button => button.text() === 'Erase and format')
    expect(check.element.disabled).toBe(true)
    await input.setValue('wrong drive')
    expect(input.attributes('aria-invalid')).toBe('true')
    await input.setValue('BIRDSTORE')
    expect(wrapper.text()).toContain('Drive name matches.')
    expect(input.attributes('aria-invalid')).toBe('false')
    expect(check.element.disabled).toBe(false)
    await check.trigger('click')
    await flushPromises()
    expect(mockApi.post).toHaveBeenCalledWith('/system/storage/format', {
      path: '/dev/sda', device_id: 'synthetic-device', confirmation: 'BIRDSTORE'
    })
    expect(wrapper.emitted('started')[0][0]).toEqual({ id: 'synthetic-job', state: 'queued' })
    expect(wrapper.text()).toContain('Formatting drive')
    expect(wrapper.find('progress').exists()).toBe(true)
  })

  it('shows a rejected request without reporting a started job', async () => {
    mockApi.post.mockRejectedValue({ response: { data: { error: 'Drive information changed.' } } })
    const wrapper = mountDialog()
    await wrapper.get('input').setValue('BIRDSTORE')
    await wrapper.findAll('button').find(button => button.text() === 'Erase and format').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('Drive information changed.')
    expect(wrapper.emitted('started')).toBeUndefined()
  })

  it('allows Escape to dismiss the preview', async () => {
    const wrapper = mountDialog()
    await wrapper.get('dialog').trigger('cancel')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})


describe('Format drive progress', () => {
  it('keeps drive identity and progress visible through mounting and completion', async () => {
    const wrapper = mountDialog()
    await wrapper.get('input').setValue('BIRDSTORE')
    await wrapper.findAll('button').find(button => button.text() === 'Erase and format').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').attributes('open')).toBeDefined()
    expect(wrapper.text()).toContain('BIRDSTORE · 500 GB')
    expect(wrapper.text()).toContain('/dev/sda')
    expect(wrapper.get('progress').attributes('value')).toBeUndefined()
    expect(wrapper.text()).not.toContain('Erase and format')
    await wrapper.setProps({ progress: { id: 'synthetic-job', state: 'mounting', message: 'Mounting formatted drive…' } })
    expect(wrapper.get('[role="status"]').text()).toContain('Mounting formatted drive…')
    expect(wrapper.find('progress').exists()).toBe(true)
    await wrapper.setProps({ progress: { id: 'synthetic-job', state: 'complete', message: 'Drive formatted and mounted. Select it under Media storage.' } })
    expect(wrapper.text()).toContain('Drive ready')
    expect(wrapper.text()).toContain('Select it under Media storage.')
    expect(wrapper.find('progress').exists()).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
    await wrapper.findAll('button').find(button => button.text() === 'Done').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('keeps a job failure visible and does not offer to erase again', async () => {
    const wrapper = mountDialog()
    await wrapper.get('input').setValue('BIRDSTORE')
    await wrapper.findAll('button').find(button => button.text() === 'Erase and format').trigger('click')
    await flushPromises()
    await wrapper.setProps({ progress: { id: 'synthetic-job', state: 'failed', message: 'Drive formatted, but mounting failed.' } })
    expect(wrapper.text()).toContain('Formatting failed')
    expect(wrapper.get('[role="alert"]').text()).toContain('Drive formatted, but mounting failed.')
    expect(wrapper.text()).not.toContain('Erase and format')
    expect(wrapper.find('progress').exists()).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
