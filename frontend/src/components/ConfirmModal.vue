<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="requestDismiss"
    />
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
        <button
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          title="Close"
          @click="requestDismiss"
        >
          <CloseIcon class="w-5 h-5" />
        </button>
        <h3 class="text-lg font-semibold text-gray-900 mb-2 pr-8">
          {{ title }}
        </h3>
        <p class="text-sm text-gray-600 mb-4">
          {{ message }}
        </p>
        <div class="flex gap-3">
          <button
            class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
            @click="$emit('cancel')"
          >
            {{ cancelLabel }}
          </button>
          <button
            class="flex-1 py-2 text-sm bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
            @click="$emit('confirm')"
          >
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import CloseIcon from '@/components/icons/CloseIcon.vue'
import { useModalDismiss } from '@/composables/useModalDismiss'

export default {
  name: 'ConfirmModal',
  components: { CloseIcon },
  props: {
    title: {
      type: String,
      default: 'Are you sure?'
    },
    message: {
      type: String,
      default: ''
    },
    confirmLabel: {
      type: String,
      default: 'Remove'
    },
    cancelLabel: {
      type: String,
      default: 'Cancel'
    }
  },
  emits: ['confirm', 'cancel'],
  setup(_, { emit }) {
    const { requestDismiss } = useModalDismiss(
      () => true,
      () => emit('cancel')
    )

    return {
      requestDismiss
    }
  }
}
</script>
