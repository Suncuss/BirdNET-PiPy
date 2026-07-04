import { ref } from 'vue'

// Module-level state (shared across all components - singleton).
// Tracks whether a page-level scroll-to-top button is currently shown, so the
// global status FABs in App.vue can yield the bottom-right corner to it
// (they share the same fixed position).
const isVisible = ref(false)

export function useScrollToTop() {
  return { isVisible }
}
