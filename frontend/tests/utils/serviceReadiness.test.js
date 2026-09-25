import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  READINESS_URL,
  describeReadiness,
  fetchServiceStates,
  waitForServicesReady
} from '@/utils/serviceReadiness'

const jsonResponse = (body, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) })

const STARTING = { ready: false, services: { model: 'starting', recorder: 'starting' } }
const MODEL_UP = { ready: false, services: { model: 'ready', recorder: 'starting' } }
const READY = { ready: true, services: { model: 'ready', recorder: 'ready' } }
const MODEL_FAILED = { ready: false, services: { model: 'failed', recorder: 'ready' } }

describe('serviceReadiness', () => {
  let fetchMock

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  describe('fetchServiceStates', () => {
    it('returns the per-service states from a valid answer', async () => {
      fetchMock.mockResolvedValue(jsonResponse(MODEL_UP))
      await expect(fetchServiceStates()).resolves.toEqual(MODEL_UP.services)
      expect(fetchMock).toHaveBeenCalledWith(READINESS_URL, expect.objectContaining({ cache: 'no-store' }))
    })

    it.each([404, 401])('reports an older backend (%i) as unsupported', async (status) => {
      fetchMock.mockResolvedValue(jsonResponse({ error: 'x' }, status))
      await expect(fetchServiceStates()).resolves.toBe('unsupported')
    })

    it.each([
      ['a network failure', () => Promise.reject(new TypeError('Failed to fetch'))],
      ['an upstream 502', () => Promise.resolve(jsonResponse({}, 502))],
      ['a rate limit', () => Promise.resolve(jsonResponse({}, 429))],
      ['a malformed body', () => Promise.resolve(jsonResponse({ status: 'ok' }))]
    ])('returns null (retry) on %s', async (_label, respond) => {
      fetchMock.mockImplementation(respond)
      await expect(fetchServiceStates()).resolves.toBeNull()
    })

    it('gives up on a hung request', async () => {
      fetchMock.mockImplementation((_url, { signal }) => new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }))
      const result = fetchServiceStates()
      await vi.advanceTimersByTimeAsync(5000)
      await expect(result).resolves.toBeNull()
    })
  })

  describe('describeReadiness', () => {
    it('names the model first, then the recorder', () => {
      expect(describeReadiness(STARTING.services)).toBe('Loading the detection model')
      expect(describeReadiness(MODEL_UP.services)).toBe('Starting the audio recorder')
    })
  })

  describe('waitForServicesReady', () => {
    it('proceeds without waiting when services are already up', async () => {
      fetchMock.mockResolvedValue(jsonResponse(READY))
      await expect(waitForServicesReady()).resolves.toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('polls until ready, reporting what is still starting', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse(STARTING))
        .mockResolvedValueOnce(jsonResponse(MODEL_UP))
        .mockResolvedValueOnce(jsonResponse(READY))
      const onProgress = vi.fn()
      let outcome
      waitForServicesReady({ onProgress }).then(o => { outcome = o })

      await vi.advanceTimersByTimeAsync(0)
      expect(onProgress).toHaveBeenLastCalledWith('Loading the detection model')
      await vi.advanceTimersByTimeAsync(2000)
      expect(onProgress).toHaveBeenLastCalledWith('Starting the audio recorder')
      expect(outcome).toBeUndefined()
      await vi.advanceTimersByTimeAsync(2000)
      expect(outcome).toBe(true)
    })

    it('keeps polling through failed fetches', async () => {
      fetchMock
        .mockRejectedValueOnce(new TypeError('Failed to fetch'))
        .mockResolvedValueOnce(jsonResponse({}, 502))
        .mockResolvedValueOnce(jsonResponse(READY))
      const result = waitForServicesReady({ pollIntervalMs: 1000 })
      await vi.advanceTimersByTimeAsync(2000)
      await expect(result).resolves.toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(3)
    })

    it('proceeds once nothing is starting, even with a failed model', async () => {
      fetchMock.mockResolvedValue(jsonResponse(MODEL_FAILED))
      await expect(waitForServicesReady()).resolves.toBe(true)
    })

    it('waits for the recorder even when the model has failed', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ ready: false, services: { model: 'failed', recorder: 'starting' } }))
        .mockResolvedValueOnce(jsonResponse(MODEL_FAILED))
      const result = waitForServicesReady({ pollIntervalMs: 1000 })
      await vi.advanceTimersByTimeAsync(1000)
      await expect(result).resolves.toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('proceeds after maxWaitMs when services never settle', async () => {
      fetchMock.mockResolvedValue(jsonResponse(STARTING))
      let outcome
      waitForServicesReady({ maxWaitMs: 10000 }).then(o => { outcome = o })

      await vi.advanceTimersByTimeAsync(9999)
      expect(outcome).toBeUndefined()
      await vi.advanceTimersByTimeAsync(1)
      expect(outcome).toBe(true)
    })

    it('proceeds straight away on a backend without the endpoint', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ error: 'Not found' }, 404))
      await expect(waitForServicesReady()).resolves.toBe(true)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('resolves false when aborted mid-wait, and stops polling', async () => {
      fetchMock.mockResolvedValue(jsonResponse(STARTING))
      const controller = new AbortController()
      const result = waitForServicesReady({ signal: controller.signal })

      await vi.advanceTimersByTimeAsync(0)
      controller.abort()
      await expect(result).resolves.toBe(false)
      await vi.advanceTimersByTimeAsync(10000)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('resolves false when aborted while a fetch is in flight', async () => {
      let answer
      fetchMock.mockImplementation(() => new Promise(resolve => { answer = resolve }))
      const controller = new AbortController()
      const result = waitForServicesReady({ signal: controller.signal })

      controller.abort()
      answer(jsonResponse(READY))
      await expect(result).resolves.toBe(false)
    })
  })
})
