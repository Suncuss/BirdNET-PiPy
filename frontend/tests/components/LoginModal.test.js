/**
 * Tests for LoginModal component
 */
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import LoginModal from '@/components/LoginModal.vue'

// Mock the useAuth composable
const mockAuth = {
  loading: { value: false },
  error: { value: '' },
  login: vi.fn(),
  clearError: vi.fn()
}

vi.mock('@/composables/useAuth', () => ({
  useAuth: () => mockAuth
}))

describe('LoginModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuth.loading.value = false
    mockAuth.error.value = ''
    mockAuth.login.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountModal = (props = {}) => mount(LoginModal, {
    props: {
      isVisible: true,
      ...props
    }
  })

  describe('Rendering', () => {
    it('renders when isVisible is true', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Authentication Required')
    })

    it('does not render when isVisible is false', () => {
      const wrapper = mountModal({ isVisible: false })
      expect(wrapper.text()).not.toContain('Authentication Required')
    })

    it('shows login title and description', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Authentication Required')
      expect(wrapper.text()).toContain('Enter your password')
    })

    it('shows password input field', () => {
      const wrapper = mountModal()
      expect(wrapper.find('#password').exists()).toBe(true)
    })

    it('shows login button', () => {
      const wrapper = mountModal()
      const button = wrapper.find('button[type="submit"]')
      expect(button.text()).toBe('Login')
    })

    it('shows close button (X icon)', () => {
      const wrapper = mountModal()
      const closeButton = wrapper.find('button[title="Close"]')
      expect(closeButton.exists()).toBe(true)
    })

    it('shows password reset help text', () => {
      const wrapper = mountModal()
      expect(wrapper.text()).toContain('Forgot password?')
      expect(wrapper.text()).toContain('RESET_PASSWORD')
    })
  })

  describe('Form Validation', () => {
    it('disables submit button when password is empty', () => {
      const wrapper = mountModal()
      const button = wrapper.find('button[type="submit"]')
      expect(button.attributes('disabled')).toBeDefined()
    })

    it('enables submit button when password is entered', async () => {
      const wrapper = mountModal()
      await wrapper.find('#password').setValue('testpassword')
      const button = wrapper.find('button[type="submit"]')
      expect(button.attributes('disabled')).toBeUndefined()
    })
  })

  describe('Login Flow', () => {
    it('calls login with password on submit', async () => {
      const wrapper = mountModal()
      await wrapper.find('#password').setValue('mypassword')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(mockAuth.login).toHaveBeenCalledWith('mypassword')
    })

    it('emits success event on successful login', async () => {
      mockAuth.login.mockResolvedValue(true)
      const wrapper = mountModal()

      await wrapper.find('#password').setValue('mypassword')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(wrapper.emitted('success')).toBeTruthy()
    })

    it('does not emit success on failed login', async () => {
      mockAuth.login.mockResolvedValue(false)
      const wrapper = mountModal()

      await wrapper.find('#password').setValue('wrongpassword')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(wrapper.emitted('success')).toBeFalsy()
    })
  })

  describe('Error Display', () => {
    it('displays error message when error is set', async () => {
      mockAuth.error.value = 'Invalid password'
      const wrapper = mountModal()

      expect(wrapper.text()).toContain('Invalid password')
    })

    it('hides error message when no error', () => {
      mockAuth.error.value = ''
      const wrapper = mountModal()

      const errorDiv = wrapper.find('.bg-red-50')
      expect(errorDiv.exists()).toBe(false)
    })
  })

  describe('Loading State', () => {
    it('shows loading spinner when loading', async () => {
      mockAuth.loading.value = true
      const wrapper = mountModal()

      expect(wrapper.text()).toContain('Please wait...')
      expect(wrapper.find('.animate-spin').exists()).toBe(true)
    })

    it('disables submit button when loading', async () => {
      mockAuth.loading.value = true
      const wrapper = mountModal()
      await wrapper.find('#password').setValue('password')

      const button = wrapper.find('button[type="submit"]')
      expect(button.attributes('disabled')).toBeDefined()
    })

    it('disables password input when loading', async () => {
      mockAuth.loading.value = true
      const wrapper = mountModal()

      const input = wrapper.find('#password')
      expect(input.attributes('disabled')).toBeDefined()
    })
  })

  describe('Cancel Action', () => {
    it('emits cancel event when close button clicked', async () => {
      const wrapper = mountModal()

      // Find the close button (X icon) by its title attribute
      const closeButton = wrapper.find('button[title="Close"]')
      await closeButton.trigger('click')

      expect(wrapper.emitted('cancel')).toBeTruthy()
    })

    it('emits cancel event when backdrop clicked', async () => {
      const wrapper = mountModal()

      // Find and click the backdrop
      const backdrop = wrapper.find('.bg-black.bg-opacity-50')
      await backdrop.trigger('click')

      expect(wrapper.emitted('cancel')).toBeTruthy()
    })

    it('clears error on cancel', async () => {
      const wrapper = mountModal()

      const closeButton = wrapper.find('button[title="Close"]')
      await closeButton.trigger('click')

      expect(mockAuth.clearError).toHaveBeenCalled()
    })

    it('hides close button when loading', async () => {
      mockAuth.loading.value = true
      const wrapper = mountModal()

      const closeButton = wrapper.find('button[title="Close"]')
      expect(closeButton.exists()).toBe(false)
    })
  })

  describe('Form Reset', () => {
    it('clears password on successful login', async () => {
      mockAuth.login.mockResolvedValue(true)
      const wrapper = mountModal()

      const passwordInput = wrapper.find('#password')
      await passwordInput.setValue('mypassword')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(passwordInput.element.value).toBe('')
    })
  })
})
