<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop (disabled while saving) -->
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="!saving && $emit('cancel')"
    />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6">
        <!-- Header -->
        <div class="text-center mb-6">
          <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-orange-100 mb-4">
            <!-- Warning icon -->
            <svg
              class="h-6 w-6 text-orange-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
          </div>
          <h2 class="text-xl font-semibold text-gray-900">
            Unsaved Changes
          </h2>
          <p class="mt-2 text-sm text-gray-600">
            You have unsaved changes that will be lost if you leave.
          </p>
        </div>

        <!-- Error message -->
        <div
          v-if="error"
          class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm"
        >
          {{ error }}
        </div>

        <!-- Buttons -->
        <div class="flex gap-3">
          <button
            :disabled="saving"
            class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors disabled:text-gray-400 disabled:hover:bg-transparent disabled:cursor-not-allowed"
            @click="$emit('discard')"
          >
            Discard
          </button>
          <button
            :disabled="saving"
            class="flex-1 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            @click="$emit('save')"
          >
            <Spinner
              v-if="saving"
              class="h-4 w-4"
            />
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import Spinner from '@/components/Spinner.vue'

export default {
  name: 'UnsavedChangesModal',
  components: { Spinner },
  props: {
    saving: {
      type: Boolean,
      default: false
    },
    error: {
      type: String,
      default: ''
    }
  },
  emits: ['save', 'discard', 'cancel']
}
</script>
