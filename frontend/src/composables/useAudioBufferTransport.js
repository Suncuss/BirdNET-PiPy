import { ref, computed, onUnmounted } from 'vue'
import { formatClock, progressPercentString } from '@/utils/format'

/**
 * Transport for playing a decoded AudioBuffer through a Web Audio graph, with a
 * smooth requestAnimationFrame playhead derived from AudioContext.currentTime —
 * NOT from an HTMLMediaElement clock.
 *
 * Why this exists (DetectionPlayer only): routing an <audio> element through
 * createMediaElementSource triggers a first-second startup glitch on WebKit
 * (iOS + macOS Safari). The element's samples and its currentTime both flow
 * through WebKit's AVFoundation media->WebAudio bridge, which mis-syncs once on
 * the first paused->playing transition: the element briefly stalls, freezing
 * both the audible audio AND the playhead before ~1s, then jumps to catch up.
 * (See WebKit bugs #221334 / #204228.) An AudioBufferSourceNode keeps every
 * sample resident and never touches that bridge, so playback starts cleanly and
 * the AudioContext clock gives a glitch-free playhead.
 *
 * AudioBufferSourceNodes are one-shot — each play/seek (re)creates the source.
 * The caller wires the resources in after they load via configure():
 *   configure({ context, buffer, destination })
 * where `destination` is the node the source connects into (the head of the
 * filter chain, e.g. the high-pass node). The same interface as
 * useAudioTransport is returned so the player template is unchanged.
 */
export function useAudioBufferTransport() {
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)

  let ctx = null
  let buffer = null
  let destination = null
  let sourceNode = null
  let envNode = null // per-play attack-ramp gain (de-click), source -> envNode -> destination
  let rafId = null

  // Attack ramp applied at every source start. An AudioBufferSourceNode begins
  // output at the sample value sitting at its start offset; from silence that
  // step is an audible click — most noticeable when you seek into the middle of
  // the clip and play. A ~12ms ramp from 0 to unity removes it.
  const FADE_IN = 0.012

  // The playhead is derived from the context clock:
  //   position = offset + (ctx.currentTime - startedAtCtxTime)
  // `offset` is where the live source started in the buffer; `startedAtCtxTime`
  // is the context time at which it started. On pause/seek we snapshot the
  // position back into `offset` and recreate the source.
  let offset = 0
  let startedAtCtxTime = 0

  const progressPercent = computed(() => progressPercentString(currentTime.value, duration.value))

  const elapsed = () => {
    if (!ctx || !isPlaying.value) return offset
    return offset + (ctx.currentTime - startedAtCtxTime)
  }

  // rAF mirrors the context clock while playing (smooth ~60fps), clamped to the
  // clip length. Started/stopped by play/pause/ended — never gated on a value.
  const tick = () => {
    currentTime.value = Math.min(elapsed(), duration.value || Infinity)
    if (isPlaying.value) rafId = requestAnimationFrame(tick)
  }

  // Tear down the live one-shot source. Clearing onended first means a manual
  // stop never reaches onSourceEnded (which is reserved for natural end).
  const releaseNodes = () => {
    if (sourceNode) {
      try { sourceNode.disconnect() } catch { /* already disconnected */ }
      sourceNode = null
    }
    if (envNode) {
      try { envNode.disconnect() } catch { /* already disconnected */ }
      envNode = null
    }
  }

  const stopSource = () => {
    if (!sourceNode) return
    sourceNode.onended = null // a manual stop must not fire onSourceEnded (natural end only)
    try { sourceNode.stop() } catch { /* already stopped/never started */ }
    releaseNodes()
  }

  const onSourceEnded = () => {
    releaseNodes()
    isPlaying.value = false
    cancelAnimationFrame(rafId)
    offset = duration.value
    currentTime.value = duration.value
  }

  // (Re)create a one-shot source playing from `at` seconds into the buffer, with
  // an attack ramp on its own gain node so starting mid-waveform doesn't click.
  const startSource = (at) => {
    stopSource()
    offset = Math.max(0, Math.min(at, duration.value))
    const t0 = ctx.currentTime
    sourceNode = ctx.createBufferSource()
    sourceNode.buffer = buffer
    envNode = ctx.createGain()
    envNode.gain.setValueAtTime(0, t0)
    envNode.gain.linearRampToValueAtTime(1, t0 + FADE_IN)
    sourceNode.connect(envNode).connect(destination)
    sourceNode.onended = onSourceEnded
    startedAtCtxTime = t0
    sourceNode.start(0, offset)
  }

  const play = async () => {
    if (!ctx || !buffer || !destination) return
    // != 'running' rather than == 'suspended': iOS Safari parks the context in
    // a non-standard 'interrupted' state after a phone call or backgrounding,
    // and it needs the same gesture-driven resume().
    if (ctx.state !== 'running') await ctx.resume()
    // Replay from the start once we've reached the end.
    startSource(offset >= duration.value ? 0 : offset)
    isPlaying.value = true
    cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(tick)
  }

  const pause = () => {
    if (!isPlaying.value) return
    offset = Math.min(elapsed(), duration.value)
    stopSource()
    isPlaying.value = false
    cancelAnimationFrame(rafId)
    currentTime.value = offset
  }

  const togglePlay = () => (isPlaying.value ? pause() : play())

  const seekTo = (seconds) => {
    if (!duration.value) return
    const clamped = Math.max(0, Math.min(duration.value, seconds))
    if (isPlaying.value) {
      startSource(clamped) // restart from the new offset, keep playing
    } else {
      offset = clamped
    }
    currentTime.value = clamped // reflect the seek immediately, don't wait a frame
  }
  const seekToFraction = (fraction) => {
    if (!duration.value) return
    seekTo(Math.max(0, Math.min(1, fraction)) * duration.value)
  }

  // Wire the audio resources once they're decoded/built. `destination` is the
  // node the source feeds into (head of the filter chain).
  const configure = ({ context, buffer: buf, destination: dest }) => {
    ctx = context
    buffer = buf
    destination = dest
    if (buf && Number.isFinite(buf.duration)) duration.value = buf.duration
  }

  const teardown = () => {
    cancelAnimationFrame(rafId)
    stopSource()
  }

  onUnmounted(teardown)

  return {
    isPlaying, currentTime, duration, progressPercent, clock: formatClock,
    togglePlay, seekTo, seekToFraction, configure
  }
}
