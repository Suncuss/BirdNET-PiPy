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
      <div class="relative max-w-full">
        <!-- Image container -->
        <div class="bg-gray-900 rounded-lg shadow-xl overflow-hidden">
          <img
            :src="imageUrl"
            :alt="alt"
            class="w-full max-h-[85vh] object-contain"
          >
        </div>

        <!-- Close button (positioned outside top-right corner) -->
        <button
          class="absolute -top-2 -right-2 sm:-top-3 sm:-right-3 p-1 sm:p-1.5 rounded-full bg-gray-800 text-gray-200 hover:bg-gray-700 hover:text-white transition-colors focus:outline-none shadow-lg"
          title="Close"
          @click="close"
        >
          <svg
            class="h-4 w-4 sm:h-5 sm:w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="2.5"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
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
