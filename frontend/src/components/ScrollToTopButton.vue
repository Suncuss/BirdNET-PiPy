<template>
  <button
    v-show="visible"
    class="fixed bottom-4 right-4 w-10 h-10 bg-green-600 hover:bg-green-700 text-white rounded-full shadow-lg flex items-center justify-center z-50 transition-colors"
    title="Scroll to top"
    @click="scrollToTop"
  >
    <svg
      class="w-5 h-5"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        stroke-width="2"
        d="M5 15l7-7 7 7"
      />
    </svg>
  </button>
</template>

<script setup>
import { onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useScrollToTop } from '@/composables/useScrollToTop'

const props = defineProps({
  // Pixels scrolled before the button appears.
  threshold: {
    type: Number,
    default: 300
  }
})

// Shared so App.vue's global status FABs yield the bottom-right corner while
// this button is showing.
const { isVisible: visible } = useScrollToTop()

const handleScroll = () => {
  visible.value = window.scrollY > props.threshold
}

const scrollToTop = () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const start = () => {
  // passive: the handler never calls preventDefault, so the browser needn't
  // wait on it before scrolling. Re-adding the same reference is a browser
  // no-op, so the onMounted+onActivated double-call on first keep-alive mount
  // is harmless.
  window.addEventListener('scroll', handleScroll, { passive: true })
  // Reflect the current scroll position immediately (e.g. on keep-alive return).
  handleScroll()
}

const stop = () => {
  window.removeEventListener('scroll', handleScroll)
  // Release the shared corner so App.vue's status FABs can reclaim it once this
  // page is gone or cached-but-hidden.
  visible.value = false
}

// onMounted/onUnmounted cover non-cached use (e.g. Table). onActivated/
// onDeactivated additionally fire when this lives inside <keep-alive>
// (BirdGallery): deactivation must release the corner, else the shared flag
// would suppress the status FABs on other pages.
onMounted(start)
onUnmounted(stop)
onActivated(start)
onDeactivated(stop)
</script>
