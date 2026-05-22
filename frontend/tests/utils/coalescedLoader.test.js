/**
 * Tests for createCoalescedLoader
 */
import { describe, it, expect, vi } from 'vitest'
import { createCoalescedLoader } from '@/utils/coalescedLoader'

describe('createCoalescedLoader', () => {
  it('runs the loader once and caches the result', async () => {
    const loader = vi.fn().mockResolvedValue(true)
    const cl = createCoalescedLoader()

    expect(await cl.ensure(loader)).toBe(true)
    expect(await cl.ensure(loader)).toBe(true)

    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('coalesces concurrent callers onto one load', async () => {
    const loader = vi.fn().mockResolvedValue(true)
    const cl = createCoalescedLoader()

    await Promise.all([cl.ensure(loader), cl.ensure(loader), cl.ensure(loader)])

    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('does not cache a falsy result — the next ensure retries', async () => {
    const loader = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true)
    const cl = createCoalescedLoader()

    expect(await cl.ensure(loader)).toBe(false)
    expect(await cl.ensure(loader)).toBe(true)
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('reset() forces the next ensure to re-run the loader', async () => {
    const loader = vi.fn().mockResolvedValue(true)
    const cl = createCoalescedLoader()

    await cl.ensure(loader)
    cl.reset()
    await cl.ensure(loader)

    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('markLoaded() makes a later ensure skip the loader', async () => {
    const loader = vi.fn().mockResolvedValue(true)
    const cl = createCoalescedLoader()

    cl.markLoaded()
    expect(await cl.ensure(loader)).toBe(true)

    expect(loader).not.toHaveBeenCalled()
  })

  it('markLoaded() does not clobber an in-flight load', async () => {
    let resolve
    const loader = vi.fn(() => new Promise((r) => { resolve = r }))
    const cl = createCoalescedLoader()

    const p = cl.ensure(loader)
    cl.markLoaded()
    resolve(true)

    expect(await p).toBe(true)
    expect(loader).toHaveBeenCalledTimes(1)
  })
})
