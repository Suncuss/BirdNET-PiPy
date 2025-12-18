/**
 * Tests for useChartColors composable
 */
import { describe, it, expect } from 'vitest'
import { useChartColors } from '@/composables/useChartColors'

describe('useChartColors', () => {
  describe('colorPalette', () => {
    it('returns colorPalette object with all expected colors', () => {
      const { colorPalette } = useChartColors()

      expect(colorPalette).toHaveProperty('primary')
      expect(colorPalette).toHaveProperty('secondary')
      expect(colorPalette).toHaveProperty('accent1')
      expect(colorPalette).toHaveProperty('accent2')
      expect(colorPalette).toHaveProperty('text')
      expect(colorPalette).toHaveProperty('background')
      expect(colorPalette).toHaveProperty('grid')
    })

    it('primary color is forest green', () => {
      const { colorPalette } = useChartColors()
      expect(colorPalette.primary).toBe('#2D6A4F')
    })

    it('secondary color is mint green', () => {
      const { colorPalette } = useChartColors()
      expect(colorPalette.secondary).toBe('#74C69D')
    })

    it('text color is dark green', () => {
      const { colorPalette } = useChartColors()
      expect(colorPalette.text).toBe('#1B4332')
    })

    it('grid color is semi-transparent', () => {
      const { colorPalette } = useChartColors()
      expect(colorPalette.grid).toMatch(/^rgba\(/)
    })
  })

  describe('secondaryRGB', () => {
    it('returns RGB array for secondary color', () => {
      const { secondaryRGB } = useChartColors()

      expect(Array.isArray(secondaryRGB)).toBe(true)
      expect(secondaryRGB).toHaveLength(3)
    })

    it('RGB values match secondary hex color #74C69D', () => {
      const { secondaryRGB } = useChartColors()

      // #74C69D = rgb(116, 198, 157)
      expect(secondaryRGB[0]).toBe(116)
      expect(secondaryRGB[1]).toBe(198)
      expect(secondaryRGB[2]).toBe(157)
    })
  })

  describe('consistency', () => {
    it('returns same values on multiple calls', () => {
      const result1 = useChartColors()
      const result2 = useChartColors()

      expect(result1.colorPalette).toEqual(result2.colorPalette)
      expect(result1.secondaryRGB).toEqual(result2.secondaryRGB)
    })
  })
})
