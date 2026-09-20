import { ref, onMounted, onUnmounted } from 'vue'

// The tall desktop tier, where the Activity Overview (Dashboard and Charts)
// shows more species. min-width is Tailwind's lg breakpoint (below it the
// heatmap is hidden and the tier is always base); min-height clears a
// fullscreen 16" MacBook Pro viewport (1117px), so built-in laptop displays
// always stay compact while taller desktop monitors (1440p-class and up) get
// the tall tier.
const TALL_VIEWPORT_QUERY = '(min-width: 1024px) and (min-height: 1150px)'

// Activity Overview species rows per tier. The tall count matches the
// server's dashboard cap (the client slices down).
export const ACTIVITY_ROWS = { base: 10, tall: 15 }

/**
 * Tracks whether the viewport is in the tall desktop tier; watch the returned
 * ref to react to a flip. 'change' only fires when the tier actually flips,
 * so no debounce is needed.
 */
export function useTallViewport() {
  const mediaQuery = window.matchMedia(TALL_VIEWPORT_QUERY)
  const isTallViewport = ref(mediaQuery.matches)

  const handleChange = (event) => {
    isTallViewport.value = event.matches
  }

  onMounted(() => mediaQuery.addEventListener('change', handleChange))
  onUnmounted(() => mediaQuery.removeEventListener('change', handleChange))

  return { isTallViewport }
}
