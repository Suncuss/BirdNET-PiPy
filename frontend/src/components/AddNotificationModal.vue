<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop -->
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="handleBackdropClick"
    />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-lg w-full p-6">
        <!-- Close button -->
        <button
          v-if="!testing"
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          @click="$emit('close')"
        >
          <svg
            class="w-5 h-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>

        <!-- Service Picker View -->
        <div v-if="!selectedService">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">
            Add Notification Service
          </h3>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <button
              v-for="service in services"
              :key="service.id"
              class="flex flex-col items-center gap-2 p-4 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors text-center"
              @click="selectService(service)"
            >
              <svg
                class="w-6 h-6 text-gray-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  :d="SERVICE_ICONS[service.id]"
                />
              </svg>
              <span class="text-xs font-medium text-gray-700">{{ service.label }}</span>
            </button>
          </div>
        </div>

        <!-- Service Form View -->
        <div v-else>
          <!-- Back + title -->
          <div class="flex items-center gap-2 mb-4">
            <button
              class="text-gray-400 hover:text-gray-600"
              @click="goBack"
            >
              <svg
                class="w-5 h-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18"
                />
              </svg>
            </button>
            <h3 class="text-lg font-semibold text-gray-900">
              {{ selectedService.label }}
            </h3>
          </div>

          <!-- Form fields -->
          <form
            class="space-y-3"
            @submit.prevent="handleTestAndAdd"
          >
            <div
              v-for="field in selectedService.fields"
              :key="field.key"
            >
              <label
                :for="'notif-' + field.key"
                class="block text-sm text-gray-600 mb-1"
              >{{ field.label }}</label>
              <input
                :id="'notif-' + field.key"
                v-model="formValues[field.key]"
                :type="field.type || 'text'"
                :placeholder="field.placeholder"
                class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              >
            </div>

            <!-- Error display -->
            <div
              v-if="error"
              class="text-xs text-red-600 bg-red-50 p-2 rounded-lg"
            >
              {{ error }}
            </div>

            <!-- Success display -->
            <div
              v-if="testSuccess"
              class="text-xs text-green-600 bg-green-50 p-2 rounded-lg"
            >
              {{ testSuccess }}
            </div>

            <!-- Actions -->
            <div class="flex items-center justify-between pt-2">
              <a
                v-if="selectedService.helpUrl"
                :href="selectedService.helpUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="text-xs text-blue-500 hover:underline"
              >Setup guide</a>
              <span v-else />
              <button
                type="submit"
                :disabled="!canSubmit || testing"
                class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
              >
                {{ testing ? 'Testing...' : 'Test & Add' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { SERVICES } from '@/utils/notificationServices'
import api from '@/services/api'

// SVG path data for each service icon (Heroicons outline)
const SERVICE_ICONS = {
  telegram: 'M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5',
  ntfy: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
  email: 'M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75',
  homeassistant: 'M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25',
  mqtt: 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5',
  custom: 'M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244'
}

export default {
  name: 'AddNotificationModal',
  emits: ['close', 'add'],
  setup(props, { emit }) {
    const services = SERVICES
    const selectedService = ref(null)
    const formValues = ref({})
    const testing = ref(false)
    const error = ref('')
    const testSuccess = ref('')

    const selectService = (service) => {
      selectedService.value = service
      // Initialize form values
      const values = {}
      for (const field of service.fields) {
        values[field.key] = ''
      }
      formValues.value = values
      error.value = ''
      testSuccess.value = ''
    }

    const goBack = () => {
      if (testing.value) return
      selectedService.value = null
      formValues.value = {}
      error.value = ''
      testSuccess.value = ''
    }

    const canSubmit = computed(() => {
      if (!selectedService.value) return false
      return selectedService.value.fields
        .filter(f => f.required)
        .every(f => formValues.value[f.key]?.trim())
    })

    const handleTestAndAdd = async () => {
      if (!canSubmit.value || testing.value) return

      error.value = ''
      testSuccess.value = ''

      // Build URL
      const url = selectedService.value.buildUrl(formValues.value)
      if (!url) {
        error.value = selectedService.value.parseError || 'Failed to build URL from the provided values.'
        return
      }

      // Test via API
      testing.value = true
      try {
        const { data } = await api.post('/notifications/test', { apprise_url: url })
        testSuccess.value = data.message || 'Test notification sent!'
        emit('add', url)
      } catch (err) {
        error.value = err.response?.data?.error || 'Failed to send test notification.'
      } finally {
        testing.value = false
      }
    }

    const handleBackdropClick = () => {
      if (!testing.value) {
        emit('close')
      }
    }

    return {
      services,
      SERVICE_ICONS,
      selectedService,
      formValues,
      testing,
      error,
      testSuccess,
      canSubmit,
      selectService,
      goBack,
      handleTestAndAdd,
      handleBackdropClick
    }
  }
}
</script>
