// Safari-only live-audio path for the Live Feed.
//
// WebKit's `createMediaElementSource` delivers NO samples to the Web Audio graph
// when the <audio> element is playing a live, infinite-duration Icecast stream
// (chunked MP3, unknown length). The element plays fine natively, but the graph
// tapping it is inert — which is why the live spectrogram (an AnalyserNode) and
// the high-pass/gain filters are dead on Safari. (Same-origin, so this is the
// streaming limitation, not CORS. See DetectionPlayer.vue, which works on Safari
// only because it decodes a *finite, fully-downloaded* clip.)
//
// This composable sidesteps the element: it fetches the MP3 mount as a byte
// stream, decodes it to PCM with a WASM mpg123 decoder, and schedules the PCM
// into a caller-provided Web Audio node. The caller owns the graph
//   (scheduled buffers) → highpass → analyser → gain → destination
// so the analyser and filters carry real signal on Safari, just like other
// browsers get from `createMediaElementSource`.
//
// The mpg123 decoder (~77 KiB) is loaded lazily via dynamic import, so it is
// code-split into its own chunk and only fetched on Safari. The WASM is inlined
// in the module (no separate .wasm file to serve).

import { ref } from 'vue'

export function useIcecastStream ({
  getContext,
  getDestination,
  onPlaying,
  onEnded,
  onError,
  // Lead time (s) the scheduler stays ahead of the audio clock. Absorbs network
  // and decode jitter so a brief stall produces one short gap, not continuous
  // crackle. ~0.3 s is inaudible as latency for a monitoring feed.
  jitterSec = 0.3
}) {
  const isActive = ref(false)

  let decoder = null
  let abortController = null
  let reader = null
  // The Web Audio time at which the NEXT decoded chunk should start playing.
  // 0 means "unset": armed with a jitter cushion on the first chunk, and
  // re-armed whenever we fall behind real time (network/decode underrun).
  let playheadTime = 0
  const scheduledSources = new Set()

  // Probe that this browser can actually load + instantiate the WASM decoder.
  // Returns false (rather than throwing) so the caller can fall back to plain
  // <audio> playback on the rare browser where the import or WASM compile fails.
  const canDecode = async () => {
    try {
      const { MPEGDecoder } = await import('mpg123-decoder')
      const probe = new MPEGDecoder({ enableGapless: false })
      await probe.ready
      probe.free()
      return true
    } catch (err) {
      console.warn(`[useIcecastStream] decoder unavailable: ${err?.message || err}`)
      return false
    }
  }

  // Schedule one decoded PCM chunk gaplessly after the previous one.
  const scheduleChunk = (channelData, sampleRate, frames) => {
    const ctx = getContext()
    const destination = getDestination()
    if (!ctx || !destination) return

    const buffer = ctx.createBuffer(channelData.length, frames, sampleRate)
    for (let c = 0; c < channelData.length; c++) {
      buffer.copyToChannel(channelData[c], c)
    }
    const node = ctx.createBufferSource()
    node.buffer = buffer
    node.connect(destination)

    const now = ctx.currentTime
    // (Re)arm the jitter buffer on the first chunk or after an underrun: if the
    // playhead has caught up to (or passed) real time, restart it a cushion
    // ahead so we don't schedule in the past.
    if (playheadTime < now + 0.02) {
      playheadTime = now + jitterSec
    }
    node.start(playheadTime)
    playheadTime += buffer.duration

    scheduledSources.add(node)
    node.onended = () => scheduledSources.delete(node)
  }

  // Drain the byte stream until it ends, errors, or stop() aborts it. Runs in
  // the background (not awaited by start) so playback continues after connect.
  const pump = async () => {
    let signaledPlaying = false
    try {
      while (isActive.value) {
        const { done, value } = await reader.read()
        if (done) break
        const { channelData, samplesDecoded, sampleRate } = decoder.decode(value)
        if (samplesDecoded > 0) {
          scheduleChunk(channelData, sampleRate, samplesDecoded)
          if (!signaledPlaying) {
            signaledPlaying = true
            onPlaying && onPlaying()
          }
        }
      }
      // A clean end means the Icecast mount closed — i.e. the upstream source
      // dropped (GH #56 flap). Surface it like an <audio> 'ended' so the caller
      // can reconnect.
      if (isActive.value) onEnded && onEnded()
    } catch (err) {
      // An abort from stop() lands here too; only surface genuine failures.
      if (isActive.value) onError && onError(err)
    }
  }

  // Free the current session's resources. Idempotent; safe to call repeatedly.
  const teardown = () => {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    if (reader) {
      try { reader.cancel() } catch { /* already released */ }
      reader = null
    }
    scheduledSources.forEach((node) => {
      try { node.stop() } catch { /* never started */ }
      try { node.disconnect() } catch { /* already disconnected */ }
    })
    scheduledSources.clear()
    if (decoder) {
      try { decoder.free() } catch { /* already freed */ }
      decoder = null
    }
    playheadTime = 0
  }

  // Open the stream and begin decoding into the caller's graph. Resolves once
  // the connection is established (HTTP OK); the decode/playback loop then runs
  // until the stream ends, errors, or stop() is called. THROWS on a connection
  // failure so the caller's reconnect logic can run.
  const start = async (url) => {
    // Free any prior session first so a reconnect doesn't orphan a decoder.
    teardown()
    isActive.value = true
    abortController = new AbortController()
    try {
      const { MPEGDecoder } = await import('mpg123-decoder')
      // No XING/LAME header at an arbitrary live-stream offset, so gapless
      // trimming has nothing to do — disable it to keep every sample and avoid
      // any start/end padding latency.
      decoder = new MPEGDecoder({ enableGapless: false })
      await decoder.ready

      // Resolve relative to the document base the same way the <audio> element
      // would (HA ingress serves under a /api/hassio_ingress/<token>/ prefix),
      // and send cookies so nginx's auth_request sees the session.
      const resolved = new URL(url, document.baseURI).href
      const response = await fetch(resolved, {
        signal: abortController.signal,
        credentials: 'same-origin'
      })
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }
      reader = response.body.getReader()
      pump()
      return true
    } catch (err) {
      // Reset so the next attempt starts from a clean slate, then rethrow.
      teardown()
      isActive.value = false
      throw err
    }
  }

  const stop = () => {
    isActive.value = false
    teardown()
  }

  return { isActive, canDecode, start, stop }
}
