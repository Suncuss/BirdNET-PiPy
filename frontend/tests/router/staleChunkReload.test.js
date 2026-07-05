/**
 * Tests for the router's stale-chunk recovery (recoverFromStaleChunk).
 *
 * A deploy replaces every hashed chunk, so a tab loaded before an update
 * fails its next lazy route import and the navigation dies silently. The
 * onError handler must recover with a one-time full page load of the
 * intended route — and must NOT loop reloads when a fresh page fails the
 * same import (a genuinely broken build), or react to unrelated errors.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { recoverFromStaleChunk } from '@/router/index.js'

const to = { fullPath: '/bird/Northern%20Cardinal' }

describe('recoverFromStaleChunk', () => {
  let assignSpy

  beforeEach(() => {
    sessionStorage.clear()
    assignSpy = vi.spyOn(window.location, 'assign').mockImplementation(() => {})
  })

  afterEach(() => {
    assignSpy.mockRestore()
  })

  it.each([
    ['Chrome', 'Failed to fetch dynamically imported module: http://x/assets/BirdDetails-DWgrBbY0.js'],
    ['Firefox', 'error loading dynamically imported module: http://x/assets/BirdDetails-DWgrBbY0.js'],
    ['Safari', 'Importing a module script failed.'],
    ['Vite CSS preload', 'Unable to preload CSS for /assets/BirdDetails-BkMbG3yO.css']
  ])('does a full load of the intended route on a %s chunk-load error', (_browser, message) => {
    const handled = recoverFromStaleChunk(new TypeError(message), to)

    expect(handled).toBe(true)
    expect(assignSpy).toHaveBeenCalledWith('/bird/Northern%20Cardinal')
  })

  it('ignores unrelated navigation errors', () => {
    const handled = recoverFromStaleChunk(new Error('Cannot read properties of undefined'), to)

    expect(handled).toBe(false)
    expect(assignSpy).not.toHaveBeenCalled()
  })

  it('tolerates errors without a message', () => {
    expect(recoverFromStaleChunk({}, to)).toBe(false)
    expect(recoverFromStaleChunk(null, to)).toBe(false)
    expect(assignSpy).not.toHaveBeenCalled()
  })

  it('does not reload again within the guard window (broken build, not a stale tab)', () => {
    const error = new TypeError('Failed to fetch dynamically imported module: http://x/a.js')

    expect(recoverFromStaleChunk(error, to)).toBe(true)
    expect(recoverFromStaleChunk(error, to)).toBe(false)
    expect(assignSpy).toHaveBeenCalledTimes(1)
  })

  it('reloads again once the guard window has passed', () => {
    const error = new TypeError('Failed to fetch dynamically imported module: http://x/a.js')
    sessionStorage.setItem('staleChunkReloadAt', String(Date.now() - 60000))

    expect(recoverFromStaleChunk(error, to)).toBe(true)
    expect(assignSpy).toHaveBeenCalledTimes(1)
  })
})
