import { describe, it, expect } from 'vitest'
import { PAUSE_REASONS, pausedLabel, pausedTitle } from '@/utils/recorderStates'
import { clock24 } from '../helpers/clock'

describe('pausedLabel', () => {
  it('shows the station-local resume clock from resumes_at', () => {
    expect(pausedLabel({ reason: PAUSE_REASONS.QUIET_HOURS, resumes_at: '2026-08-25T06:00' }, clock24))
      .toBe('Paused until 06:00')
  })

  it('reads as a plain audio pause when there is no resume time', () => {
    expect(pausedLabel({ reason: PAUSE_REASONS.NO_SOURCES, resumes_at: null }, clock24))
      .toBe('Audio Paused')
    expect(pausedLabel(null, clock24)).toBe('Audio Paused')
    expect(pausedLabel({ reason: PAUSE_REASONS.QUIET_HOURS, resumes_at: null }, clock24))
      .toBe('Audio Paused')
  })
})

describe('pausedTitle', () => {
  it('spells out the reason the short label omits', () => {
    expect(pausedTitle({ reason: PAUSE_REASONS.NO_SOURCES }))
      .toBe('Recording is paused — no audio source is active')
    expect(pausedTitle({ reason: PAUSE_REASONS.QUIET_HOURS }))
      .toBe('Recording is paused by quiet hours')
  })

  it('falls back without a reason', () => {
    expect(pausedTitle(null)).toBe('Recording is paused')
  })
})
