/**
 * Tests for useDetectionInfo composable — day/night weather icon selection.
 *
 * The backend derives `extra.weather.is_day` (1/0) from the detection
 * timestamp; rows predating the flag simply lack it and must keep the
 * daytime icons. Descriptions never change — day/night is icon-only.
 */
import { describe, it, expect } from 'vitest'
import { useDetectionInfo } from '@/composables/useDetectionInfo'

const weather = (overrides = {}) => ({
  temp: 20, humidity: 50, precip: 0, wind: 5,
  code: 0, cloud_cover: 10, pressure: 1015,
  ...overrides
})

const describe_ = (w) => useDetectionInfo({ extra: { weather: w } }).weatherDescription.value

describe('useDetectionInfo weather icons', () => {
  describe('day/night variants', () => {
    it('clear sky shows sun during the day', () => {
      expect(describe_(weather({ code: 0, is_day: 1 }))).toEqual({ desc: 'Clear sky', icon: '☀️' })
    })

    it('clear sky shows moon at night', () => {
      expect(describe_(weather({ code: 0, is_day: 0 }))).toEqual({ desc: 'Clear sky', icon: '🌙' })
    })

    it.each([
      [1, '🌙'],  // mainly clear
      [2, '☁️']   // partly cloudy drops the sun
    ])('code %i uses its night icon after dark', (code, icon) => {
      expect(describe_(weather({ code, is_day: 0 })).icon).toBe(icon)
    })

    it.each([80, 81, 82])('rain showers (code %i) drop the sun at night', (code) => {
      expect(describe_(weather({ code, is_day: 0 })).icon).toBe('🌧️')
      expect(describe_(weather({ code, is_day: 1 })).icon).toBe('🌦️')
    })
  })

  describe('codes without a day/night distinction', () => {
    it.each([
      [3, '☁️'],   // overcast
      [61, '🌧️'],  // rain
      [95, '⛈️']   // thunderstorm
    ])('code %i keeps its icon at night', (code, icon) => {
      expect(describe_(weather({ code, is_day: 0 })).icon).toBe(icon)
    })
  })

  describe('missing flag (historical rows)', () => {
    it('keeps the daytime icon when is_day is absent', () => {
      expect(describe_(weather({ code: 0 }))).toEqual({ desc: 'Clear sky', icon: '☀️' })
    })

    it('unknown code stays unknown at night', () => {
      expect(describe_(weather({ code: 999, is_day: 0 }))).toEqual({ desc: 'Unknown', icon: '❓' })
    })
  })

  it('night flag works through the string-extra parse path', () => {
    const detection = { extra: JSON.stringify({ weather: weather({ code: 0, is_day: 0 }) }) }
    expect(useDetectionInfo(detection).weatherDescription.value.icon).toBe('🌙')
  })
})
