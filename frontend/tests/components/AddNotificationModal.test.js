import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AddNotificationModal from '@/components/AddNotificationModal.vue'
import {
  SERVICES,
  deriveScheme
} from '@/utils/notificationServices'

// Mock the api service
const mockApi = vi.hoisted(() => ({
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

const mountModal = () => mount(AddNotificationModal)

describe('notificationServices - URL builders', () => {
  it('Telegram: builds correct URL', () => {
    const service = SERVICES.find(s => s.id === 'telegram')
    expect(service.buildUrl({ bot_token: '123:ABC', chat_id: '-100123' }))
      .toBe('tgram://123%3AABC/-100123')
  })

  it('Telegram: encodes special characters', () => {
    const service = SERVICES.find(s => s.id === 'telegram')
    expect(service.buildUrl({ bot_token: 'a/b@c', chat_id: 'd#e' }))
      .toBe('tgram://a%2Fb%40c/d%23e')
  })

  it('ntfy: builds URL with default server (ntfys)', () => {
    const service = SERVICES.find(s => s.id === 'ntfy')
    expect(service.buildUrl({ topic: 'birds', server: '' }))
      .toBe('ntfys://birds')
  })

  it('ntfy: uses insecure scheme for http:// server', () => {
    const service = SERVICES.find(s => s.id === 'ntfy')
    expect(service.buildUrl({ topic: 'birds', server: 'http://my-server.local' }))
      .toBe('ntfy://my-server.local/birds')
  })

  it('ntfy: uses secure scheme for https:// server', () => {
    const service = SERVICES.find(s => s.id === 'ntfy')
    expect(service.buildUrl({ topic: 'birds', server: 'https://ntfy.example.com' }))
      .toBe('ntfys://ntfy.example.com/birds')
  })

  it('Email: builds URL from email and password', () => {
    const service = SERVICES.find(s => s.id === 'email')
    const url = service.buildUrl({ email: 'user@gmail.com', password: 'pass123', smtp: '' })
    expect(url).toBe('mailtos://user:pass123@gmail.com')
  })

  it('Email: appends SMTP when provided', () => {
    const service = SERVICES.find(s => s.id === 'email')
    const url = service.buildUrl({ email: 'user@example.com', password: 'p', smtp: 'smtp.example.com' })
    expect(url).toBe('mailtos://user:p@example.com?smtp=smtp.example.com')
  })

  it('Email: encodes special characters in password', () => {
    const service = SERVICES.find(s => s.id === 'email')
    const url = service.buildUrl({ email: 'user@gmail.com', password: 'p@ss/word', smtp: '' })
    expect(url).toBe('mailtos://user:p%40ss%2Fword@gmail.com')
  })

  it('Email: returns null for invalid email', () => {
    const service = SERVICES.find(s => s.id === 'email')
    expect(service.buildUrl({ email: 'nope', password: 'p', smtp: '' })).toBeNull()
  })

  it('Home Assistant: builds URL with secure scheme', () => {
    const service = SERVICES.find(s => s.id === 'homeassistant')
    expect(service.buildUrl({ server: 'https://ha.example.com', token: 'mytoken123' }))
      .toBe('hassios://ha.example.com/mytoken123')
  })

  it('Home Assistant: uses insecure scheme for http://', () => {
    const service = SERVICES.find(s => s.id === 'homeassistant')
    expect(service.buildUrl({ server: 'http://homeassistant.local:8123', token: 'tok' }))
      .toBe('hassio://homeassistant.local:8123/tok')
  })

  it('Home Assistant: defaults to secure scheme without prefix', () => {
    const service = SERVICES.find(s => s.id === 'homeassistant')
    expect(service.buildUrl({ server: 'homeassistant.local:8123', token: 'tok' }))
      .toBe('hassios://homeassistant.local:8123/tok')
  })

  it('Home Assistant: encodes token with special characters', () => {
    const service = SERVICES.find(s => s.id === 'homeassistant')
    expect(service.buildUrl({ server: 'ha.local', token: 'tok/en@val' }))
      .toBe('hassios://ha.local/tok%2Fen%40val')
  })

  it('MQTT: builds URL with broker and topic', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'localhost', topic: 'birdnet/detections', user: '', password: '' }))
      .toBe('mqtt://localhost/birdnet%2Fdetections')
  })

  it('MQTT: includes user and password when provided', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'broker.local', topic: 'birds', user: 'admin', password: 'secret' }))
      .toBe('mqtt://admin:secret@broker.local/birds')
  })

  it('MQTT: includes user without password', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'broker.local', topic: 'birds', user: 'admin', password: '' }))
      .toBe('mqtt://admin@broker.local/birds')
  })

  it('MQTT: uses mqtts scheme for mqtts:// input', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'mqtts://broker.example.com', topic: 'birds', user: '', password: '' }))
      .toBe('mqtts://broker.example.com/birds')
  })

  it('MQTT: strips mqtt:// prefix from broker', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'mqtt://broker.local', topic: 'test', user: '', password: '' }))
      .toBe('mqtt://broker.local/test')
  })

  it('MQTT: encodes special characters in credentials', () => {
    const service = SERVICES.find(s => s.id === 'mqtt')
    expect(service.buildUrl({ server: 'broker.local', topic: 'birds', user: 'u@ser', password: 'p/ass' }))
      .toBe('mqtt://u%40ser:p%2Fass@broker.local/birds')
  })

  it('Custom: passes through raw URL', () => {
    const service = SERVICES.find(s => s.id === 'custom')
    expect(service.buildUrl({ url: '  json://localhost  ' }))
      .toBe('json://localhost')
  })
})

describe('deriveScheme', () => {
  it('uses insecure scheme for http://', () => {
    const result = deriveScheme('http://example.com', { prefixMap: { 'http://': 'ntfy' }, defaultScheme: 'ntfys' })
    expect(result).toEqual({ scheme: 'ntfy', host: 'example.com' })
  })

  it('uses secure scheme for https://', () => {
    const result = deriveScheme('https://example.com', { prefixMap: { 'http://': 'ntfy' }, defaultScheme: 'ntfys' })
    expect(result).toEqual({ scheme: 'ntfys', host: 'example.com' })
  })

  it('uses default scheme for no prefix', () => {
    const result = deriveScheme('example.com', { prefixMap: { 'http://': 'gotify' }, defaultScheme: 'gotifys' })
    expect(result).toEqual({ scheme: 'gotifys', host: 'example.com' })
  })

  it('handles mqtt prefixes', () => {
    const opts = { prefixMap: { 'mqtts://': 'mqtts', 'mqtt://': 'mqtt' }, defaultScheme: 'mqtt' }
    expect(deriveScheme('broker.local', opts)).toEqual({ scheme: 'mqtt', host: 'broker.local' })
    expect(deriveScheme('mqtt://broker.local', opts)).toEqual({ scheme: 'mqtt', host: 'broker.local' })
    expect(deriveScheme('mqtts://broker.example.com', opts)).toEqual({ scheme: 'mqtts', host: 'broker.example.com' })
  })
})

describe('AddNotificationModal - component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders service picker grid on mount', () => {
    const wrapper = mountModal()
    expect(wrapper.text()).toContain('Add Notification Service')
    expect(wrapper.text()).toContain('Telegram')
    expect(wrapper.text()).toContain('Home Assistant')
    expect(wrapper.text()).toContain('MQTT')
    expect(wrapper.text()).toContain('Custom URL')
  })

  it('clicking a service card shows form view with correct fields', async () => {
    const wrapper = mountModal()

    // Click Telegram card
    const cards = wrapper.findAll('button').filter(b => b.text().includes('Telegram'))
    await cards[0].trigger('click')

    expect(wrapper.text()).toContain('Bot Token')
    expect(wrapper.text()).toContain('Chat ID')
    expect(wrapper.text()).not.toContain('Add Notification Service')
  })

  it('back button returns to picker and resets form', async () => {
    const wrapper = mountModal()

    // Select a service
    wrapper.vm.selectService(SERVICES.find(s => s.id === 'telegram'))
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.selectedService).not.toBeNull()

    // Click back
    wrapper.vm.goBack()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.selectedService).toBeNull()
    expect(wrapper.text()).toContain('Add Notification Service')
  })

  it('back button is blocked during testing', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'telegram'))
    await wrapper.vm.$nextTick()

    wrapper.vm.testing = true
    await wrapper.vm.$nextTick()

    wrapper.vm.goBack()
    await wrapper.vm.$nextTick()

    // Should still be on the form view
    expect(wrapper.vm.selectedService).not.toBeNull()
  })

  it('submit is disabled when required fields empty', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'telegram'))
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.canSubmit).toBe(false)

    const submitBtn = wrapper.find('button[type="submit"]')
    expect(submitBtn.attributes('disabled')).toBeDefined()
  })

  it('submit is enabled when required fields filled', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'telegram'))
    await wrapper.vm.$nextTick()

    wrapper.vm.formValues = { bot_token: '123:ABC', chat_id: '-100' }
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.canSubmit).toBe(true)
  })

  it('successful test emits add with URL', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'custom'))
    await wrapper.vm.$nextTick()
    wrapper.vm.formValues = { url: 'json://localhost' }
    await wrapper.vm.$nextTick()

    mockApi.post.mockResolvedValueOnce({ data: { message: 'Sent!' } })

    await wrapper.vm.handleTestAndAdd()
    await flushPromises()

    expect(mockApi.post).toHaveBeenCalledWith('/notifications/test', { apprise_url: 'json://localhost' })
    expect(wrapper.emitted('add')).toBeTruthy()
    expect(wrapper.emitted('add')[0]).toEqual(['json://localhost'])
  })

  it('failed test shows error and does not emit', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'custom'))
    await wrapper.vm.$nextTick()
    wrapper.vm.formValues = { url: 'bad://url' }
    await wrapper.vm.$nextTick()

    mockApi.post.mockRejectedValueOnce({
      response: { data: { error: 'Invalid token' } }
    })

    await wrapper.vm.handleTestAndAdd()
    await flushPromises()

    expect(wrapper.vm.error).toBe('Invalid token')
    expect(wrapper.emitted('add')).toBeFalsy()
  })

  it('shows parse error when URL build fails', async () => {
    const wrapper = mountModal()

    wrapper.vm.selectService(SERVICES.find(s => s.id === 'email'))
    await wrapper.vm.$nextTick()
    wrapper.vm.formValues = { email: 'nope', password: 'p', smtp: '' }
    await wrapper.vm.$nextTick()

    await wrapper.vm.handleTestAndAdd()
    await flushPromises()

    expect(wrapper.vm.error).toContain('email')
    expect(mockApi.post).not.toHaveBeenCalled()
  })

  it('backdrop click emits close when not testing', async () => {
    const wrapper = mountModal()

    const backdrop = wrapper.find('.bg-black')
    await backdrop.trigger('click')

    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('backdrop click does not emit close when testing', async () => {
    const wrapper = mountModal()

    wrapper.vm.testing = true
    await wrapper.vm.$nextTick()

    const backdrop = wrapper.find('.bg-black')
    await backdrop.trigger('click')

    expect(wrapper.emitted('close')).toBeFalsy()
  })

  it('X button emits close', async () => {
    const wrapper = mountModal()

    // The close button is the first button with the X SVG
    const closeBtn = wrapper.find('.absolute.top-4.right-4')
    await closeBtn.trigger('click')

    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
