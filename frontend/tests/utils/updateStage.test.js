import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchUpdateStage, isStageFresh, UPDATE_PROGRESS_URL } from '@/utils/updateStage'

describe('updateStage', () => {
  describe('fetchUpdateStage', () => {
    let fetchMock

    beforeEach(() => {
      fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    const response = (body, ok = true) => ({
      ok,
      json: () => Promise.resolve(body)
    })

    it('returns message and timestamp from a valid stage file', async () => {
      fetchMock.mockResolvedValue(response({
        stage: 'pull',
        message: 'Downloading updated images (1 of 3)',
        timestamp: '2026-07-31T12:00:00Z'
      }))

      const stage = await fetchUpdateStage()

      expect(fetchMock).toHaveBeenCalledWith(UPDATE_PROGRESS_URL, { cache: 'no-store' })
      expect(stage).toEqual({
        message: 'Downloading updated images (1 of 3)',
        timestamp: '2026-07-31T12:00:00Z'
      })
    })

    it('returns a null timestamp when the file has none', async () => {
      fetchMock.mockResolvedValue(response({ message: 'Building images locally' }))
      expect(await fetchUpdateStage()).toEqual({
        message: 'Building images locally',
        timestamp: null
      })
    })

    it('returns null on a non-ok response (endpoint absent)', async () => {
      // The SPA's 404 fallback serves index.html with a 404 status
      fetchMock.mockResolvedValue(response({}, false))
      expect(await fetchUpdateStage()).toBeNull()
    })

    it('returns null when message is missing or not a string', async () => {
      fetchMock.mockResolvedValue(response({ stage: 'pull', message: 42 }))
      expect(await fetchUpdateStage()).toBeNull()
    })

    it('returns null when the fetch rejects (server down)', async () => {
      fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
      expect(await fetchUpdateStage()).toBeNull()
    })

    it('returns null when the body is not JSON', async () => {
      fetchMock.mockResolvedValue({ ok: true, json: () => Promise.reject(new SyntaxError()) })
      expect(await fetchUpdateStage()).toBeNull()
    })
  })

  describe('isStageFresh', () => {
    const HOUR = 60 * 60 * 1000

    it('accepts a recent timestamp', () => {
      const recent = new Date(Date.now() - 5 * 60 * 1000).toISOString()
      expect(isStageFresh(recent, HOUR)).toBe(true)
    })

    it('rejects a stale timestamp', () => {
      const old = new Date(Date.now() - 2 * HOUR).toISOString()
      expect(isStageFresh(old, HOUR)).toBe(false)
    })

    it('accepts a future timestamp (client clock skew)', () => {
      const future = new Date(Date.now() + 10 * 60 * 1000).toISOString()
      expect(isStageFresh(future, HOUR)).toBe(true)
    })

    it('rejects missing or unparseable timestamps', () => {
      expect(isStageFresh(null, HOUR)).toBe(false)
      expect(isStageFresh('', HOUR)).toBe(false)
      expect(isStageFresh('not-a-date', HOUR)).toBe(false)
    })
  })
})
