import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useIcecastStream } from '@/composables/useIcecastStream'

// Controllable state shared with the hoisted vi.mock factory below.
const decoderState = vi.hoisted(() => ({
  instances: [],
  decode: null,      // (bytes) => { channelData, samplesDecoded, sampleRate }
  ctorThrows: false  // make `new MPEGDecoder()` throw (decoder unavailable)
}))

vi.mock('mpg123-decoder', () => {
  class MPEGDecoder {
    constructor () {
      if (decoderState.ctorThrows) throw new Error('decoder unavailable')
      this.freed = false
      this.ready = Promise.resolve()
      decoderState.instances.push(this)
    }

    decode (bytes) {
      return decoderState.decode
        ? decoderState.decode(bytes)
        : { channelData: [new Float32Array(0)], samplesDecoded: 0, sampleRate: 44100 }
    }

    free () { this.freed = true }
  }
  return { MPEGDecoder }
})

// Flush enough microtasks for the background pump loop to drain a short reader.
const tick = async (n = 12) => { for (let i = 0; i < n; i++) await Promise.resolve() }

const makeReader = (chunks) => {
  let i = 0
  return {
    read: vi.fn(async () => (
      i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined }
    )),
    cancel: vi.fn()
  }
}

const makeContext = () => {
  const sources = []
  return {
    sources,
    currentTime: 0,
    createBuffer: (channels, frames, sampleRate) => ({
      duration: frames / sampleRate,
      copyToChannel: vi.fn()
    }),
    createBufferSource: () => {
      const node = {
        buffer: null,
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        disconnect: vi.fn(),
        onended: null
      }
      sources.push(node)
      return node
    }
  }
}

const PCM = () => ({ channelData: [new Float32Array(1152)], samplesDecoded: 1152, sampleRate: 44100 })

describe('useIcecastStream', () => {
  let ctx, destination, onPlaying, onEnded, onError, stream, fetchMock

  beforeEach(() => {
    decoderState.instances = []
    decoderState.decode = null
    decoderState.ctorThrows = false

    ctx = makeContext()
    destination = { id: 'highpass' }
    onPlaying = vi.fn()
    onEnded = vi.fn()
    onError = vi.fn()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    stream = useIcecastStream({
      getContext: () => ctx,
      getDestination: () => destination,
      onPlaying,
      onEnded,
      onError
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  describe('canDecode', () => {
    it('returns true when the WASM decoder loads', async () => {
      expect(await stream.canDecode()).toBe(true)
      // The probe instance is freed, not leaked.
      expect(decoderState.instances.at(-1).freed).toBe(true)
    })

    it('returns false when the decoder cannot be instantiated', async () => {
      decoderState.ctorThrows = true
      expect(await stream.canDecode()).toBe(false)
    })
  })

  describe('start / pump', () => {
    it('decodes chunks into buffer sources, signals playing, then ends', async () => {
      decoderState.decode = () => PCM()
      fetchMock.mockResolvedValue({
        ok: true,
        body: { getReader: () => makeReader([new Uint8Array([1, 2, 3])]) }
      })

      await stream.start('stream/source_0.mp3')
      await tick()

      // One decoded chunk → one buffer source, connected to the caller's node.
      expect(ctx.sources).toHaveLength(1)
      expect(ctx.sources[0].connect).toHaveBeenCalledWith(destination)
      expect(ctx.sources[0].start).toHaveBeenCalled()
      // First audio reported, clean end surfaced for reconnect.
      expect(onPlaying).toHaveBeenCalledTimes(1)
      expect(onEnded).toHaveBeenCalledTimes(1)
      expect(onError).not.toHaveBeenCalled()
    })

    it('sends cookies and resolves the URL against the document base', async () => {
      fetchMock.mockResolvedValue({
        ok: true,
        body: { getReader: () => makeReader([]) }
      })

      await stream.start('stream/source_0.mp3')

      const [url, opts] = fetchMock.mock.calls[0]
      expect(String(url)).toContain('stream/source_0.mp3')
      expect(opts.credentials).toBe('same-origin')
    })

    it('throws on a non-OK response so the caller can reconnect', async () => {
      fetchMock.mockResolvedValue({ ok: false, status: 404, body: null })
      await expect(stream.start('stream/source_0.mp3')).rejects.toThrow('HTTP 404')
      expect(stream.isActive.value).toBe(false)
    })

    it('surfaces a mid-stream read failure via onError', async () => {
      fetchMock.mockResolvedValue({
        ok: true,
        body: {
          getReader: () => ({
            read: vi.fn().mockRejectedValue(new Error('network dropped')),
            cancel: vi.fn()
          })
        }
      })

      await stream.start('stream/source_0.mp3')
      await tick()

      expect(onError).toHaveBeenCalledTimes(1)
      expect(onEnded).not.toHaveBeenCalled()
    })
  })

  describe('stop', () => {
    it('frees the decoder and stops scheduled sources', async () => {
      decoderState.decode = () => PCM()
      fetchMock.mockResolvedValue({
        ok: true,
        body: { getReader: () => makeReader([new Uint8Array([1])]) }
      })

      await stream.start('stream/source_0.mp3')
      await tick()
      const decoder = decoderState.instances.at(-1)
      const source = ctx.sources[0]

      stream.stop()

      expect(stream.isActive.value).toBe(false)
      expect(decoder.freed).toBe(true)
      expect(source.stop).toHaveBeenCalled()
      expect(source.disconnect).toHaveBeenCalled()
    })

    it('does not call onError when the abort comes from stop()', async () => {
      // Model the real abort path: a pending read() that rejects only after
      // stop() has flipped isActive false — the pump must swallow it silently.
      let rejectRead
      fetchMock.mockResolvedValue({
        ok: true,
        body: {
          getReader: () => ({
            read: vi.fn(() => new Promise((_resolve, reject) => { rejectRead = reject })),
            cancel: vi.fn()
          })
        }
      })

      await stream.start('stream/source_0.mp3')
      stream.stop()
      rejectRead(new Error('aborted')) // the in-flight read rejects due to abort
      await tick()

      expect(onError).not.toHaveBeenCalled()
    })
  })
})
