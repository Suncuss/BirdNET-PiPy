<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="$emit('cancel')"
    />
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-2">
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
export default {
  name: 'ConfirmModal',
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
  emits: ['confirm', 'cancel']
}
</script>
