<template>
  <div
    v-if="isVisible"
    class="fixed inset-0 z-50 overflow-y-auto"
  >
    <!-- Backdrop -->
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="handleCancel"
    />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
        <!-- Close button -->
        <button
          v-if="!loading"
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors"
          title="Close"
          @click="handleCancel"
        >
          <svg
            class="h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="2"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>

        <!-- Header -->
        <div class="text-center mb-6">
          <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
            <!-- Lock icon -->
            <svg
              class="h-6 w-6 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
              />
            </svg>
          </div>
          <h2 class="text-xl font-semibold text-gray-900">
            Authentication Required
          </h2>
          <p class="mt-2 text-sm text-gray-600">
            Enter your password to access protected features.
          </p>
        </div>

        <!-- Error message -->
        <div
          v-if="error"
          class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm"
        >
          {{ error }}
        </div>

        <!-- Password form -->
        <form
          class="space-y-4"
          @submit.prevent="handleSubmit"
        >
          <!-- Password input -->
          <div>
            <label
              for="password"
              class="block text-sm text-gray-600 mb-1"
            >
              Password
            </label>
            <input
              id="password"
              ref="passwordInput"
              v-model="password"
              type="password"
              placeholder="Enter your password"
              class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-green-500 focus:ring-1 focus:ring-green-500"
              :disabled="loading"
              autocomplete="current-password"
            >
          </div>

          <!-- Submit button -->
          <button
            type="submit"
            :disabled="loading || !isValid"
            class="w-full flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg shadow transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
          >
            <svg
              v-if="loading"
              class="animate-spin h-5 w-5"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            {{ loading ? 'Please wait...' : 'Login' }}
          </button>
        </form>

        <!-- Forgot password help -->
        <p class="mt-4 text-xs text-gray-500 text-center">
          Forgot password? Create a file named <code class="bg-gray-100 px-1 rounded">RESET_PASSWORD</code>
          in <code class="bg-gray-100 px-1 rounded">data/config/</code> on your device to reset.
        </p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, nextTick } from 'vue'
import { useAuth } from '@/composables/useAuth'

export default {
  name: 'LoginModal',
  props: {
    isVisible: {
      type: Boolean,
      default: false
    }
  },
  emits: ['success', 'cancel'],
  setup(props, { emit }) {
    const auth = useAuth()

    // Local state
    const password = ref('')
    const passwordInput = ref(null)

    // Computed
    const loading = computed(() => auth.loading.value)
    const error = computed(() => auth.error.value)
    const isValid = computed(() => password.value.length > 0)

    // Focus input when modal becomes visible
    watch(() => props.isVisible, async (visible) => {
      if (visible) {
        // Clear form
        password.value = ''
        auth.clearError()

        // Focus input
        await nextTick()
        passwordInput.value?.focus()
      }
    })

    // Methods
    const handleSubmit = async () => {
      if (!isValid.value || loading.value) return

      const success = await auth.login(password.value)

      if (success) {
        password.value = ''
        emit('success')
      }
    }

    const handleCancel = () => {
      password.value = ''
      auth.clearError()
      emit('cancel')
    }

    return {
      password,
      passwordInput,
      loading,
      error,
      isValid,
      handleSubmit,
      handleCancel
    }
  }
}
</script>
