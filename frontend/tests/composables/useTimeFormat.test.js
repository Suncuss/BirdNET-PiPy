import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useTimeFormat } from '@/composables/useTimeFormat'

const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

describe('useTimeFormat', () => {
  beforeEach(() => {
    mockApi.get.mockReset()
    mockApi.put.mockReset()
    // Reset shared singleton state between tests, then force a known starting point
    // for the browser-detected format so the tests are deterministic.
    const { resetState, detectedFormat } = useTimeFormat()
    resetState()
    detectedFormat.value = '24h'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('effective format resolution', () => {
    it('falls back to detected format when no explicit choice is set', () => {
      const { timeFormat, isExplicit, hour12, detectedFormat } = useTimeFormat()
      detectedFormat.value = '12h'
      expect(isExplicit.value).toBe(false)
      expect(timeFormat.value).toBe('12h')
      expect(hour12.value).toBe(true)
    })

    it('uses explicit choice when set', () => {
      const { timeFormat, isExplicit, hour12, setTimeFormat, detectedFormat } = useTimeFormat()
      detectedFormat.value = '12h' // browser says 12h
      setTimeFormat('24h')          // user overrides to 24h
      expect(isExplicit.value).toBe(true)
      expect(timeFormat.value).toBe('24h')
      expect(hour12.value).toBe(false)
    })
  })

  describe('formatTime', () => {
    it('returns empty string for null/undefined input', () => {
      const { formatTime } = useTimeFormat()
      expect(formatTime(null)).toBe('')
      expect(formatTime(undefined)).toBe('')
    })

    it('forces 24h when explicit choice is 24h', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      const result = formatTime('2024-01-01T14:30:00Z')
      expect(result.toUpperCase()).not.toMatch(/AM|PM/)
    })

    it('forces 12h when explicit choice is 12h', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('12h')
      const result = formatTime('2024-01-01T14:30:00Z')
      expect(result.toUpperCase()).toMatch(/AM|PM/)
    })

    it('accepts a Date instance', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      expect(formatTime(new Date('2024-01-01T14:30:00Z'))).not.toMatch(/AM|PM/i)
    })

    it('respects custom format options (e.g. seconds)', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      const result = formatTime('2024-01-01T14:30:45Z', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      })
      expect(result.match(/\d+/g)?.length ?? 0).toBeGreaterThanOrEqual(3)
    })

    it('renders midnight as 00:xx in 24h mode (not 24:xx — en-US h24 quirk)', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      // Force UTC so the assertion is timezone-independent
      const result = formatTime('2024-01-01T00:30:00Z', { timeZone: 'UTC' })
      expect(result).toMatch(/^00:30/)
      expect(result).not.toMatch(/^24/)
    })

    it('renders midnight as 12 AM in 12h mode (not 0 AM)', () => {
      const { formatTime, setTimeFormat } = useTimeFormat()
      setTimeFormat('12h')
      const result = formatTime('2024-01-01T00:30:00Z', { timeZone: 'UTC' })
      expect(result).toMatch(/^12:30/)
      expect(result.toUpperCase()).toContain('AM')
    })
  })

  describe('formatHour', () => {
    it('returns empty string for non-numeric or null input', () => {
      const { formatHour } = useTimeFormat()
      expect(formatHour('abc')).toBe('')
      expect(formatHour(null)).toBe('')
      expect(formatHour(undefined)).toBe('')
    })

    it('returns padded HH:00 string when 24h', () => {
      const { formatHour, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      expect(formatHour(0)).toBe('00:00')
      expect(formatHour(9)).toBe('09:00')
      expect(formatHour(13)).toBe('13:00')
      expect(formatHour(23)).toBe('23:00')
    })

    it('returns AM/PM string when 12h', () => {
      const { formatHour, setTimeFormat } = useTimeFormat()
      setTimeFormat('12h')
      expect(formatHour(0)).toBe('12 AM')
      expect(formatHour(1)).toBe('1 AM')
      expect(formatHour(11)).toBe('11 AM')
      expect(formatHour(12)).toBe('12 PM')
      expect(formatHour(13)).toBe('1 PM')
      expect(formatHour(23)).toBe('11 PM')
    })
  })

  describe('formatHourLabel', () => {
    it('parses "HH:00" labels and reformats per preference', () => {
      const { formatHourLabel, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      expect(formatHourLabel('14:00')).toBe('14:00')
      expect(formatHourLabel('9:00')).toBe('09:00')
      setTimeFormat('12h')
      expect(formatHourLabel('14:00')).toBe('2 PM')
      expect(formatHourLabel('0:00')).toBe('12 AM')
    })

    it('returns the label unchanged when it does not parse', () => {
      const { formatHourLabel } = useTimeFormat()
      expect(formatHourLabel('garbage')).toBe('garbage')
    })

    it('returns empty string for non-string input', () => {
      const { formatHourLabel } = useTimeFormat()
      expect(formatHourLabel(null)).toBe('')
      expect(formatHourLabel(undefined)).toBe('')
      expect(formatHourLabel(14)).toBe('')
    })
  })

  describe('setTimeFormat', () => {
    it('clears explicit choice for invalid/null/legacy values', () => {
      const { explicitFormat, isExplicit, setTimeFormat } = useTimeFormat()
      setTimeFormat('24h')
      expect(isExplicit.value).toBe(true)
      setTimeFormat('auto')      // legacy value — should clear
      expect(explicitFormat.value).toBeNull()
      expect(isExplicit.value).toBe(false)
      setTimeFormat('garbage')
      expect(explicitFormat.value).toBeNull()
      setTimeFormat(null)
      expect(explicitFormat.value).toBeNull()
      setTimeFormat(undefined)
      expect(explicitFormat.value).toBeNull()
    })

    it('accepts valid values', () => {
      const { explicitFormat, setTimeFormat } = useTimeFormat()
      setTimeFormat('12h')
      expect(explicitFormat.value).toBe('12h')
      setTimeFormat('24h')
      expect(explicitFormat.value).toBe('24h')
    })
  })

  describe('loadTimeFormat', () => {
    it('updates state from API response', async () => {
      mockApi.get.mockResolvedValueOnce({ data: { display: { time_format: '12h' } } })
      const { explicitFormat, loadTimeFormat } = useTimeFormat()
      await loadTimeFormat()
      expect(explicitFormat.value).toBe('12h')
    })

    it('treats missing field as no explicit choice', async () => {
      mockApi.get.mockResolvedValueOnce({ data: { display: {} } })
      const { explicitFormat, loadTimeFormat } = useTimeFormat()
      await loadTimeFormat()
      expect(explicitFormat.value).toBeNull()
    })

    it('tolerates legacy "auto" value (treats as no explicit choice)', async () => {
      mockApi.get.mockResolvedValueOnce({ data: { display: { time_format: 'auto' } } })
      const { explicitFormat, loadTimeFormat } = useTimeFormat()
      await loadTimeFormat()
      expect(explicitFormat.value).toBeNull()
    })

    it('ignores invalid values from the API', async () => {
      mockApi.get.mockResolvedValueOnce({ data: { display: { time_format: 'bogus' } } })
      const { explicitFormat, loadTimeFormat } = useTimeFormat()
      await loadTimeFormat()
      expect(explicitFormat.value).toBeNull()
    })

    it('does not throw when the API call fails', async () => {
      mockApi.get.mockRejectedValueOnce(new Error('boom'))
      const { explicitFormat, loadTimeFormat } = useTimeFormat()
      await expect(loadTimeFormat()).resolves.toBeUndefined()
      expect(explicitFormat.value).toBeNull()
    })
  })

  describe('saveTimeFormat', () => {
    it('PUTs to /settings/time-format and updates state on success', async () => {
      mockApi.put.mockResolvedValueOnce({ data: { success: true, time_format: '24h' } })
      const { explicitFormat, saveTimeFormat } = useTimeFormat()
      const ok = await saveTimeFormat('24h')
      expect(ok).toBe(true)
      expect(mockApi.put).toHaveBeenCalledWith('/settings/time-format', { time_format: '24h' })
      expect(explicitFormat.value).toBe('24h')
    })

    it('returns false and does not call API for invalid values (incl. "auto")', async () => {
      const { saveTimeFormat } = useTimeFormat()
      expect(await saveTimeFormat('bogus')).toBe(false)
      expect(await saveTimeFormat('auto')).toBe(false)
      expect(await saveTimeFormat(null)).toBe(false)
      expect(mockApi.put).not.toHaveBeenCalled()
    })

    it('returns false and surfaces error on API failure', async () => {
      mockApi.put.mockRejectedValueOnce(new Error('network'))
      const { saveTimeFormat, error, explicitFormat } = useTimeFormat()
      const ok = await saveTimeFormat('12h')
      expect(ok).toBe(false)
      expect(error.value).toMatch(/Failed to save/)
      expect(explicitFormat.value).toBeNull()
    })
  })
})
