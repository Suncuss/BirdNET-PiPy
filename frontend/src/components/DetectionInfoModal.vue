<template>
  <Transition
    enter-active-class="transition ease-out duration-200"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition ease-in duration-150"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="isVisible"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      @click.self="close"
    >
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full max-h-[85vh] overflow-hidden">
        <!-- Header -->
        <div class="px-5 py-4 border-b border-gray-200 bg-gray-50">
          <h3 class="text-lg font-semibold text-gray-900">Detection Info</h3>
          <p v-if="detection" class="text-sm text-gray-500 mt-0.5">
            {{ detection.common_name }}
          </p>
        </div>

        <!-- Content -->
        <div class="px-5 py-4 overflow-y-auto max-h-[60vh]">
          <template v-if="detection">
            <!-- Extra Field Data -->
            <div v-if="hasExtraData">
              <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Metadata
              </h4>
              <dl class="space-y-3">
                <div
                  v-for="(value, key) in extraData"
                  :key="key"
                  class="flex justify-between items-start gap-4"
                >
                  <dt class="text-sm text-gray-600 flex-shrink-0">
                    {{ formatKey(key) }}
                  </dt>
                  <dd class="text-sm font-medium text-gray-900 text-right break-all">
                    {{ formatValue(value) }}
                  </dd>
                </div>
              </dl>
            </div>

            <!-- No Extra Data -->
            <div v-else class="text-center py-6">
              <p class="text-sm text-gray-500">No additional metadata available.</p>
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-gray-200 bg-gray-50">
          <button
            @click="close"
            class="w-full px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
          >
            Close
          </button>
        </div>

        <!-- Close button -->
        <button
          @click="close"
          class="absolute top-3 right-3 p-1 rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          title="Close"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  isVisible: {
    type: Boolean,
    default: false
  },
  detection: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close'])

const close = () => {
  emit('close')
}

const extraData = computed(() => {
  if (!props.detection?.extra) return {}
  // Handle both string (JSON) and object
  if (typeof props.detection.extra === 'string') {
    try {
      return JSON.parse(props.detection.extra)
    } catch {
      return {}
    }
  }
  return props.detection.extra
})

const hasExtraData = computed(() => {
  return Object.keys(extraData.value).length > 0
})

const formatKey = (key) => {
  // Convert snake_case or camelCase to Title Case
  return key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, str => str.toUpperCase())
    .trim()
}

const formatValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>
