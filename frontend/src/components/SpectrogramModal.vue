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
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
      @click.self="close"
    >
      <div class="relative bg-gray-900 rounded-lg shadow-xl overflow-hidden">
        <!-- Close button -->
        <button
          @click="close"
          class="absolute top-1 right-1 sm:top-2 sm:right-2 z-10 p-0.5 sm:p-1 rounded-full bg-green-900/40 text-gray-200 hover:bg-green-800/60 hover:text-white transition-colors focus:outline-none"
          title="Close"
        >
          <svg class="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <!-- Image container -->
        <img
          :src="imageUrl"
          :alt="alt"
          class="w-full max-h-[85vh] object-contain"
        >
      </div>
    </div>
  </Transition>
</template>

<script>
export default {
  name: 'SpectrogramModal',
  props: {
    isVisible: {
      type: Boolean,
      default: false
    },
    imageUrl: {
      type: String,
      required: true
    },
    alt: {
      type: String,
      default: 'Spectrogram'
    }
  },
  emits: ['close'],
  setup(props, { emit }) {
    const close = () => {
      emit('close')
    }

    return {
      close
    }
  }
}
</script>
