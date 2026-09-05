import { describe, it, expect } from 'vitest'
import {
  QUIET_HOURS_DEFAULTS,
  describeQuietHours,
  formatClock,
  formatDuration,
  parseHHMM,
  quietHoursDuration
} from '@/utils/quietHours'
import { clock24 } from '../helpers/clock'

describe('quietHours utils', () => {
  it('ships the backend defaults', () => {
    expect(QUIET_HOURS_DEFAULTS).toEqual({ enabled: false, start: '22:00', end: '06:00' })
  })

  describe('parseHHMM', () => {
    it.each([['00:00', 0], ['06:00', 360], ['07:05', 425], ['23:59', 1439]])('parses %s', (value, expected) => {
      expect(parseHHMM(value)).toBe(expected)
    })

    it.each(['24:00', '7:05', '07:5', '07:60', '07:30:00', '', null, undefined, 730])('rejects %s', (value) => {
      expect(parseHHMM(value)).toBeNull()
    })
  })

  describe('quietHoursDuration', () => {
    it('measures a same-day window', () => {
      expect(quietHoursDuration('09:00', '17:00')).toBe(480)
    })

    it('wraps an overnight window past midnight', () => {
      expect(quietHoursDuration('22:00', '06:00')).toBe(480)
      expect(quietHoursDuration('23:30', '00:15')).toBe(45)
    })

    it('returns null for unparseable times', () => {
      expect(quietHoursDuration('22:00', 'six')).toBeNull()
    })
  })

  it('formats durations', () => {
    expect(formatDuration(480)).toBe('8 h')
    expect(formatDuration(450)).toBe('7 h 30 min')
    expect(formatDuration(45)).toBe('45 min')
  })

  it('formats a clock time through the supplied formatter', () => {
    expect(formatClock('06:05', clock24)).toBe('06:05')
    expect(formatClock('nope', clock24)).toBe('')
  })

  describe('describeQuietHours', () => {
    it('says recording is continuous when disabled', () => {
      expect(describeQuietHours({ enabled: false, start: '22:00', end: '06:00' }, clock24))
        .toBe('Recording runs around the clock.')
    })

    it('describes an overnight window and its wrap', () => {
      expect(describeQuietHours({ enabled: true, start: '22:00', end: '06:00' }, clock24))
        .toBe('Pauses 22:00 – 06:00 every day (8 h). Overnight ranges wrap past midnight.')
    })

    it('describes a same-day window without the wrap note', () => {
      expect(describeQuietHours({ enabled: true, start: '09:00', end: '17:30' }, clock24))
        .toBe('Pauses 09:00 – 17:30 every day (8 h 30 min).')
    })

    it('returns nothing for an unusable window', () => {
      expect(describeQuietHours({ enabled: true, start: '', end: '06:00' }, clock24)).toBe('')
    })
  })
})
