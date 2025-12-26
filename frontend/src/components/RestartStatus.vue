<template>
  <!-- Banner variant (for Settings page) -->
  <template v-if="variant === 'banner'">
    <!-- Restart Progress Banner -->
    <div v-if="isRestarting && restartMessage" class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
      <div class="flex items-center gap-2 text-blue-700 text-sm">
        <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>{{ restartMessage }}</span>
      </div>
    </div>

    <!-- Restart Error Banner -->
    <div v-if="restartError" class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2 text-amber-700 text-sm">
          <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>{{ restartError }}</span>
        </div>
        <button
          @click="$emit('dismiss')"
          class="text-amber-700 hover:text-amber-900 text-sm underline"
        >
          Dismiss
        </button>
      </div>
    </div>

    <!-- Save Error Banner -->
    <div v-if="saveError" class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2 text-red-700 text-sm">
          <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span>{{ saveError }}</span>
        </div>
        <button
          @click="$emit('dismiss')"
          class="text-red-700 hover:text-red-900 text-sm underline"
        >
          Dismiss
        </button>
      </div>
    </div>
  </template>

  <!-- Inline variant (for modals) -->
  <template v-else-if="variant === 'inline'">
    <!-- Restart Progress -->
    <div v-if="isRestarting && restartMessage" class="flex items-center gap-2 text-blue-700 text-sm">
      <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <span>{{ restartMessage }}</span>
    </div>

    <!-- Restart Error -->
    <div v-else-if="restartError" class="flex items-center justify-between w-full">
      <div class="flex items-center gap-2 text-amber-700 text-sm">
        <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <span>{{ restartError }}</span>
      </div>
      <button
        @click="$emit('dismiss')"
        class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
      >
        Close
      </button>
    </div>

    <!-- Save Error -->
    <div v-else-if="saveError" class="flex items-center justify-between w-full">
      <div class="flex items-center gap-2 text-red-600 text-sm">
        <svg class="h-4 w-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span>{{ saveError }}</span>
      </div>
      <div class="flex gap-2">
        <button
          @click="$emit('dismiss')"
          class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
        >
          Cancel
        </button>
        <button
          @click="$emit('retry')"
          class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
        >
          Retry
        </button>
      </div>
    </div>
  </template>
</template>

<script>
export default {
  name: 'RestartStatus',
  props: {
    variant: {
      type: String,
      default: 'banner',
      validator: (value) => ['banner', 'inline'].includes(value)
    },
    isRestarting: {
      type: Boolean,
      default: false
    },
    restartMessage: {
      type: String,
      default: ''
    },
    restartError: {
      type: String,
      default: ''
    },
    saveError: {
      type: String,
      default: ''
    }
  },
  emits: ['dismiss', 'retry']
}
</script>
