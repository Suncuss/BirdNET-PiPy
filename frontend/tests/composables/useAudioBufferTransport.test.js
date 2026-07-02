/**
 * Tests for useAudioBufferTransport — DetectionPlayer's playback transport.
 *
 * It plays a decoded AudioBuffer through an AudioBufferSourceNode (recreated per
 * play/seek, since they're one-shot) and derives the playhead from
 * AudioContext.currentTime rather than an HTMLMediaElement clock. Web Audio and
 * requestAnimationFrame are faked so we can drive the context clock and step
 * frames deterministically.
 */
import { createApp } from 'vue'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAudioBufferTransport } from '@/composables/useAudioBufferTransport'

// --- Fakes ------------------------------------------------------------------
class FakeBufferSource {
  constructor(ctx) {
    this.ctx = ctx
    this.buffer = null
    this.onended = null
    this.started = null
    this.stopCount = 0
    this.disconnected = false
    ctx._sources.push(this)
  }
  connect(node) { this.connectedTo = node; return node }
  disconnect() { this.disconnected = true }
  start(when, offset) { this.started = { when, offset } }
  stop() { this.stopCount += 1 }
}

class FakeGain {
  constructor() {
    this.gain = {
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn()
    }
    this.connectedTo = null
    this.disconnected = false
  }
  connect(node) { this.connectedTo = node; return node }
  disconnect() { this.disconnected = true }
}

class FakeAudioContext {
  constructor() {
    this.state = 'suspended'
    this.currentTime = 0
    this._sources = []
    this.resumeCount = 0
  }
  async resume() { this.resumeCount += 1; this.state = 'running' }
  createBufferSource() { return new FakeBufferSource(this) }
  createGain() { return new FakeGain() }
}

// Run the composable inside a real app instance so onUnmounted is valid and
// app.unmount() exercises the teardown path.
function withSetup(composable) {
  let result
  const app = createApp({ setup() { result = composable(); return () => null } })
  app.mount(document.createElement('div'))
  return [result, app]
}

// --- rAF control ------------------------------------------------------------
let rafCbs
let realRaf
let realCancel
function flushFrame() {
  const cbs = rafCbs
  rafCbs = []
  cbs.forEach((cb) => cb())
}

describe('useAudioBufferTransport', () => {
  let ctx
  let destination
  let buffer
  let lastSource

  beforeEach(() => {
    rafCbs = []
    realRaf = globalThis.requestAnimationFrame
    realCancel = globalThis.cancelAnimationFrame
    globalThis.requestAnimationFrame = vi.fn((cb) => { rafCbs.push(cb); return rafCbs.length })
    globalThis.cancelAnimationFrame = vi.fn()

    ctx = new FakeAudioContext()
    destination = { name: 'highpass' }
    buffer = { duration: 10 }
    lastSource = () => ctx._sources[ctx._sources.length - 1]
  })

  afterEach(() => {
    globalThis.requestAnimationFrame = realRaf
    globalThis.cancelAnimationFrame = realCancel
    vi.restoreAllMocks()
  })

  it('configure() sets duration from the buffer', () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    expect(t.duration.value).toBe(0)
    t.configure({ context: ctx, buffer, destination })
    expect(t.duration.value).toBe(10)
    app.unmount()
  })

  it('play() resumes a suspended context, starts a source from 0, and marks playing', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })

    await t.togglePlay()

    expect(ctx.resumeCount).toBe(1)
    expect(ctx.state).toBe('running')
    expect(t.isPlaying.value).toBe(true)
    const src = lastSource()
    expect(src.buffer).toBe(buffer)
    // source -> envelope gain -> destination
    const env = src.connectedTo
    expect(env).toBeTruthy()
    expect(env.connectedTo).toBe(destination)
    expect(src.started).toEqual({ when: 0, offset: 0 })
    // de-click: the envelope ramps from 0 up to unity at the start
    expect(env.gain.setValueAtTime).toHaveBeenCalledWith(0, expect.any(Number))
    expect(env.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, expect.any(Number))
    app.unmount()
  })

  it('derives the playhead from the context clock and pause snapshots the position', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })

    await t.togglePlay()
    ctx.currentTime = 3
    flushFrame()
    expect(t.currentTime.value).toBe(3)
    expect(t.progressPercent.value).toBe('30%')

    t.togglePlay() // pause
    expect(t.isPlaying.value).toBe(false)
    expect(t.currentTime.value).toBe(3)
    expect(lastSource().stopCount).toBe(1)

    // Resume continues from the snapshot, not from 0.
    await t.togglePlay()
    expect(lastSource().started).toEqual({ when: 0, offset: 3 })
    ctx.currentTime = 5
    flushFrame()
    expect(t.currentTime.value).toBe(5)
    app.unmount()
  })

  it('clamps the playhead to the clip duration', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })
    await t.togglePlay()
    ctx.currentTime = 999
    flushFrame()
    expect(t.currentTime.value).toBe(10)
    expect(t.progressPercent.value).toBe('100%')
    app.unmount()
  })

  it('natural end stops playback and parks the playhead at the end; next play restarts from 0', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })
    await t.togglePlay()

    lastSource().onended() // simulate reaching the end of the buffer
    expect(t.isPlaying.value).toBe(false)
    expect(t.currentTime.value).toBe(10)

    await t.togglePlay()
    expect(lastSource().started).toEqual({ when: 0, offset: 0 })
    app.unmount()
  })

  it('seekToFraction sets the position while paused without starting a source', () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })

    t.seekToFraction(0.5)
    expect(t.currentTime.value).toBe(5)
    expect(t.isPlaying.value).toBe(false)
    expect(ctx._sources.length).toBe(0)
    app.unmount()
  })

  it('seeking while playing restarts the source from the new offset and keeps playing', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })
    await t.togglePlay()
    const before = ctx._sources.length

    t.seekToFraction(0.2)
    expect(t.isPlaying.value).toBe(true)
    expect(ctx._sources.length).toBe(before + 1)
    expect(lastSource().started).toEqual({ when: 0, offset: 2 })
    app.unmount()
  })

  it('does nothing on play() before configure()', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    await t.togglePlay()
    expect(t.isPlaying.value).toBe(false)
    expect(ctx._sources.length).toBe(0)
    app.unmount()
  })

  it('unmount tears down the live source', async () => {
    const [t, app] = withSetup(useAudioBufferTransport)
    t.configure({ context: ctx, buffer, destination })
    await t.togglePlay()
    const src = lastSource()
    app.unmount()
    expect(src.stopCount).toBeGreaterThanOrEqual(1)
  })
})
