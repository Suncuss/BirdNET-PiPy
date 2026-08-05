import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import UpdateOverlay from '@/components/UpdateOverlay.vue'
import { useUpdateOverlay } from '@/composables/useUpdateOverlay'

// The overlay composable imports useServiceRestart, which pulls in the api service
vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  createLongRequest: vi.fn()
}))

vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    info: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn()
  })
}))

describe('UpdateOverlay', () => {
  const overlay = useUpdateOverlay()

  afterEach(() => {
    overlay.deactivateUpdateOverlay()
  })

  it('renders nothing while inactive', () => {
    const wrapper = mount(UpdateOverlay)
    expect(wrapper.find('div').exists()).toBe(false)
  })

  it('shows the current stage while an update runs', async () => {
    overlay.visible.value = true
    overlay.stageMessage.value = 'Downloading updated images (2 of 3)'

    const wrapper = mount(UpdateOverlay)

    expect(wrapper.text()).toContain('System is updating')
    expect(wrapper.text()).toContain('Downloading updated images (2 of 3)')
    expect(wrapper.text()).toContain('reload automatically')
  })

  it('switches to the reloading message once the API is back', async () => {
    overlay.visible.value = true
    overlay.stageMessage.value = 'Restarting services with the new version'
    overlay.reloading.value = true

    const wrapper = mount(UpdateOverlay)

    expect(wrapper.text()).toContain('Back online — reloading…')
    expect(wrapper.text()).not.toContain('Restarting services with the new version')
  })
})
