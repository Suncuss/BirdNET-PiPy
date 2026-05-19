<template>
  <Transition
    name="welcome"
    appear
    @after-leave="$emit('done')"
  >
    <div
      v-if="visible"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-black/20 backdrop-blur-sm"
    >
      <div class="welcome-card bg-white rounded-2xl shadow-2xl px-10 py-8 flex flex-col items-center text-center max-w-xs mx-4">
        <div class="flex items-center justify-center h-16 w-16 rounded-full bg-green-100 mb-4">
          <svg
            class="h-10 w-10 text-green-600"
            viewBox="0 0 52 52"
            fill="none"
          >
            <circle
              class="welcome-circle"
              cx="26"
              cy="26"
              r="24"
              stroke="currentColor"
              stroke-width="3"
            />
            <path
              class="welcome-check"
              stroke="currentColor"
              stroke-width="4"
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M14 27l8 8 16-18"
            />
          </svg>
        </div>
        <h1 class="welcome-text text-lg font-semibold text-gray-900 mb-1">
          You're all set!
        </h1>
        <p class="welcome-text welcome-text-delayed text-sm text-gray-500">
          Happy birding
        </p>
      </div>
    </div>
  </Transition>
</template>

<script>
import { ref, onMounted, onBeforeUnmount } from 'vue'

export default {
  name: 'WelcomeOverlay',
  emits: ['done'],
  setup() {
    const visible = ref(true)
    let timer = null

    onMounted(() => {
      timer = setTimeout(() => {
        visible.value = false
      }, 3200)
    })

    onBeforeUnmount(() => {
      if (timer) clearTimeout(timer)
    })

    return { visible }
  }
}
</script>

<style scoped>
.welcome-enter-active,
.welcome-leave-active {
  transition: opacity 400ms ease;
}
.welcome-enter-from,
.welcome-leave-to {
  opacity: 0;
}

.welcome-card {
  animation: welcome-pop 500ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}

.welcome-circle {
  stroke-dasharray: 151;
  stroke-dashoffset: 151;
  animation: welcome-draw-circle 600ms ease-out 200ms forwards;
}
.welcome-check {
  stroke-dasharray: 60;
  stroke-dashoffset: 60;
  animation: welcome-draw-check 400ms ease-out 700ms forwards;
}
.welcome-text {
  opacity: 0;
  transform: translateY(6px);
  animation: welcome-rise 500ms ease-out 950ms forwards;
}
.welcome-text-delayed {
  animation-delay: 1150ms;
}

@keyframes welcome-pop {
  from {
    opacity: 0;
    transform: scale(0.85);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
@keyframes welcome-draw-circle {
  to { stroke-dashoffset: 0; }
}
@keyframes welcome-draw-check {
  to { stroke-dashoffset: 0; }
}
@keyframes welcome-rise {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
