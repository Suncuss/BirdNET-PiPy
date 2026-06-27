import { ref, computed, watch, onUnmounted } from 'vue'

/**
 * Shared transport for an <audio> element: play/pause state, a smooth
 * requestAnimationFrame-driven clock, seeking, and listener/teardown plumbing.
 * Used by both the SpectrogramPlayer (template-ref <audio>) and the Detection
 * Detail page (an imperatively-created Audio() routed through a Web Audio graph).
 *
 * Pass a ref holding the element (a template ref, or one assigned later); the
 * composable (de)attaches its listeners as that ref changes and on unmount.
 *
 * @param {import('vue').Ref<HTMLAudioElement|null>} audioElRef
 * @param {Object} [opts]
 * @param {() => (void | Promise<void>)} [opts.onBeforePlay] - awaited before the
 *   first/each play() — e.g. resume an AudioContext and build the graph.
 */
export function useAudioTransport(audioElRef, { onBeforePlay } = {}) {
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  let rafId = null

  const progressPercent = computed(() => {
    if (!duration.value) return '0%'
    return `${Math.min(100, (currentTime.value / duration.value) * 100)}%`
  })

  const clock = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${String(s).padStart(2, '0')}`
  }

  // Drive the clock from rAF while playing (smooth ~60fps) rather than the
  // element's coarse `timeupdate` (~4/s). Started/stopped by play/pause/ended,
  // never gated on a currentTime value — see the media-clock-granularity lesson.
  const tick = () => {
    const el = audioElRef.value
    if (el) currentTime.value = el.currentTime
    if (isPlaying.value) rafId = requestAnimationFrame(tick)
  }

  const onLoaded = () => {
    const d = audioElRef.value?.duration
    if (Number.isFinite(d)) duration.value = d
  }
  const onPlay = () => {
    isPlaying.value = true
    cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(tick)
  }
  const onPause = () => {
    isPlaying.value = false
    cancelAnimationFrame(rafId)
    const el = audioElRef.value
    if (el) currentTime.value = el.currentTime
  }
  const onEnded = () => {
    isPlaying.value = false
    cancelAnimationFrame(rafId)
    currentTime.value = duration.value
  }

  const togglePlay = async () => {
    const el = audioElRef.value
    if (!el) return
    if (el.paused) {
      if (onBeforePlay) await onBeforePlay()
      el.play()?.catch(() => {})
    } else {
      el.pause()
    }
  }

  const seekTo = (seconds) => {
    const el = audioElRef.value
    if (!el || !duration.value) return
    el.currentTime = Math.max(0, Math.min(duration.value, seconds))
    currentTime.value = el.currentTime
  }
  const seekToFraction = (fraction) => {
    if (!duration.value) return
    seekTo(Math.max(0, Math.min(1, fraction)) * duration.value)
  }

  const attach = (el) => {
    if (!el) return
    el.addEventListener('loadedmetadata', onLoaded)
    el.addEventListener('durationchange', onLoaded)
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    el.addEventListener('ended', onEnded)
    onLoaded() // metadata may already be available
  }
  const detach = (el) => {
    if (!el) return
    el.removeEventListener('loadedmetadata', onLoaded)
    el.removeEventListener('durationchange', onLoaded)
    el.removeEventListener('play', onPlay)
    el.removeEventListener('pause', onPause)
    el.removeEventListener('ended', onEnded)
  }

  // The element may be a template ref (set on mount) or assigned later — react to
  // either, swapping listeners as it changes.
  watch(audioElRef, (el, prev) => {
    detach(prev)
    attach(el)
  }, { immediate: true })

  onUnmounted(() => {
    cancelAnimationFrame(rafId)
    detach(audioElRef.value)
  })

  return { isPlaying, currentTime, duration, progressPercent, clock, togglePlay, seekTo, seekToFraction }
}
