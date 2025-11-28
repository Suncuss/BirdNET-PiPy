import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'
import UpdateManager from '@/components/UpdateManager.vue'

vi.mock('axios')

const originalLocation = window.location

const mountComponent = () => mount(UpdateManager)

const mockLocationReload = () => {
  const reloadMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, reload: reloadMock }
  })
  return reloadMock
}

describe('UpdateManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation
    })
    vi.useRealTimers()
  })

  it('checks for updates on mount and shows current version', async () => {
    axios.get.mockResolvedValueOnce({
      data: { current_version: '1.0.0', update_available: false }
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(axios.get).toHaveBeenCalledWith('/api/update/check')
    expect(wrapper.text()).toContain('Current Version:')
    expect(wrapper.text()).toContain('1.0.0')
    expect(wrapper.text()).toContain('System is up to date')
  })

  it('renders available update details and actions', async () => {
    axios.get.mockResolvedValueOnce({
      data: {
        current_tag: 'v1.0.0',
        remote_tag: 'v1.1.0',
        update_available: true,
        changes: ['Add dashboard cards', 'Improve audio player']
      }
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('Update Available!')
    expect(wrapper.text()).toContain('v1.1.0')
    expect(wrapper.findAll('li').length).toBe(2)
    expect(wrapper.findAll('button').some(btn => btn.text().includes('Apply Update'))).toBe(true)
  })

  it('applies update after confirmation and shows progress', async () => {
    axios.get.mockResolvedValueOnce({
      data: { current_version: '1.0.0', remote_version: '1.1.0', update_available: true, changes: [] }
    })
    axios.post.mockResolvedValueOnce({ data: { status: 'success' } })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const reloadMock = mockLocationReload()
    vi.useFakeTimers()

    const wrapper = mountComponent()
    await flushPromises()

    const applyButton = wrapper.findAll('button').find(btn => btn.text().includes('Apply Update'))
    expect(applyButton).toBeDefined()

    await applyButton.trigger('click')
    await flushPromises()
    vi.runAllTimers()

    expect(axios.post).toHaveBeenCalledWith('/api/update/apply')
    expect(wrapper.text()).toContain('Update complete! Reloading...')
    expect(reloadMock).toHaveBeenCalled()
  })

  it('surfaces error messages when update check fails', async () => {
    axios.get.mockRejectedValueOnce({
      response: { data: { message: 'network down' } }
    })

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
  })

  it('does not apply update when user cancels confirmation', async () => {
    axios.get.mockResolvedValueOnce({
      data: { update_available: true, current_version: '1.0.0', remote_version: '1.1.0', changes: [] }
    })
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    const wrapper = mountComponent()
    await flushPromises()

    const applyButton = wrapper.findAll('button').find(btn => btn.text().includes('Apply Update'))
    expect(applyButton).toBeDefined()

    await applyButton.trigger('click')

    expect(axios.post).not.toHaveBeenCalled()
  })
})
