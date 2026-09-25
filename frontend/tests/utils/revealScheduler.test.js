import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createRevealScheduler } from '@/utils/revealScheduler'

describe('createRevealScheduler', () => {
  let revealed
  let scheduler

  beforeEach(() => {
    vi.useFakeTimers()
    revealed = []
    scheduler = createRevealScheduler({
      reveal: (item, result) => revealed.push(`${item}:${result}`),
      gapMs: 100,
      holdMs: 1000
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reveals in enqueue order even when results settle out of order', () => {
    const a = scheduler.add('a')
    const b = scheduler.add('b')
    const c = scheduler.add('c')

    scheduler.settle(c, 'C')
    scheduler.settle(b, 'B')
    expect(revealed).toEqual([])  // head 'a' not ready yet

    scheduler.settle(a, 'A')
    expect(revealed).toEqual(['a:A'])
    vi.advanceTimersByTime(100)
    expect(revealed).toEqual(['a:A', 'b:B'])
    vi.advanceTimersByTime(100)
    expect(revealed).toEqual(['a:A', 'b:B', 'c:C'])
  })

  it('spaces consecutive reveals by gapMs', () => {
    const a = scheduler.add('a')
    const b = scheduler.add('b')
    scheduler.settle(a, 'A')
    scheduler.settle(b, 'B')

    expect(revealed).toEqual(['a:A'])
    vi.advanceTimersByTime(99)
    expect(revealed).toEqual(['a:A'])
    vi.advanceTimersByTime(1)
    expect(revealed).toEqual(['a:A', 'b:B'])
  })

  it('skips a slow head after holdMs and reveals it when it lands', () => {
    const slow = scheduler.add('slow')
    const fast = scheduler.add('fast')
    scheduler.settle(fast, 'F')

    vi.advanceTimersByTime(999)
    expect(revealed).toEqual([])
    vi.advanceTimersByTime(1)
    expect(revealed).toEqual(['fast:F'])

    scheduler.settle(slow, 'S')
    expect(revealed).toEqual(['fast:F', 'slow:S'])
  })

  it('does not spend wave time on tickets with nothing to show', () => {
    const empty = scheduler.add('empty')
    const b = scheduler.add('b')
    scheduler.settle(b, 'B')
    scheduler.settle(empty, null)

    expect(revealed).toEqual(['b:B'])
  })

  it('restarts the hold for the new head when the held head settles empty', () => {
    const a = scheduler.add('a')
    const b = scheduler.add('b')
    const c = scheduler.add('c')
    scheduler.settle(c, 'C')  // starts the hold on 'a'

    vi.advanceTimersByTime(900)
    scheduler.settle(a, null)  // 'a' drops out; 'b' is the new, unsettled head
    vi.advanceTimersByTime(200)
    // The old hold must not skip 'b' early — only 200ms of its hold elapsed.
    expect(revealed).toEqual([])

    scheduler.settle(b, 'B')
    expect(revealed).toEqual(['b:B'])
    vi.advanceTimersByTime(100)
    expect(revealed).toEqual(['b:B', 'c:C'])
  })

  it('reset drops pending tickets and timers', () => {
    const a = scheduler.add('a')
    const b = scheduler.add('b')
    scheduler.settle(a, 'A')
    scheduler.settle(b, 'B')
    scheduler.reset()

    vi.advanceTimersByTime(5000)
    expect(revealed).toEqual(['a:A'])
  })
})
