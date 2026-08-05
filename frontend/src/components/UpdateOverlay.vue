<template>
  <div
    v-if="visible"
    class="fixed inset-0 z-[100] flex items-center justify-center bg-black/20 backdrop-blur-sm"
  >
    <div class="bg-white rounded-2xl shadow-2xl px-10 py-8 flex flex-col items-center text-center max-w-sm mx-4">
      <div class="flex items-center justify-center h-16 w-16 rounded-full bg-green-100 mb-4">
        <svg
          class="h-10 w-10 text-green-600 animate-spin"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="3"
          />
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      </div>
      <h1 class="text-lg font-semibold text-gray-900 mb-1">
        System is updating
      </h1>
      <p class="text-sm text-gray-500">
        {{ reloading ? 'Back online — reloading…' : stageMessage }}
      </p>
      <p class="text-xs text-gray-400 mt-3">
        This page will reload automatically when the update finishes.
      </p>
    </div>
  </div>
</template>

<script>
import { useUpdateOverlay } from '@/composables/useUpdateOverlay'

export default {
  name: 'UpdateOverlay',
  setup() {
    const { visible, stageMessage, reloading } = useUpdateOverlay()
    return { visible, stageMessage, reloading }
  }
}
</script>
