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
      @click.self="requestDismiss"
    >
      <div class="relative bg-white rounded-lg shadow-xl max-w-md w-full max-h-[85vh] overflow-hidden">
        <!-- Header -->
        <div class="px-5 py-4 border-b border-gray-200 bg-gray-50">
          <h3 class="text-lg font-semibold text-gray-900">
            Detection Info
          </h3>
          <p
            v-if="detection"
            class="text-sm text-gray-500 mt-0.5"
          >
            {{ detection.display_common_name || detection.common_name }}
          </p>
        </div>

        <!-- Content -->
        <div class="px-5 py-4 overflow-y-auto max-h-[60vh]">
          <DetectionInfo :detection="detection" />
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-gray-200 bg-gray-50">
          <button
            class="w-full px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
            @click="requestDismiss"
          >
            Close
          </button>
        </div>

        <!-- Close button -->
        <button
          class="absolute top-3 right-3 p-1 rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          title="Close"
          @click="requestDismiss"
        >
          <CloseIcon class="h-5 w-5" />
        </button>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import CloseIcon from '@/components/icons/CloseIcon.vue'
import DetectionInfo from '@/components/DetectionInfo.vue'
import { useModalDismiss } from '@/composables/useModalDismiss'

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

const { requestDismiss } = useModalDismiss(
  () => props.isVisible,
  () => emit('close')
)
</script>
