/**
 * Tests for useSmartCrop composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useSmartCrop } from '@/composables/useSmartCrop'

// Mock smartcrop library
vi.mock('smartcrop', () => ({
  default: {
    crop: vi.fn()
  }
}))

describe('useSmartCrop', () => {
  let smartcrop
  let helpers

  beforeEach(async () => {
    smartcrop = (await import('smartcrop')).default
    vi.clearAllMocks()
    helpers = useSmartCrop()
  })

  afterEach(() => {
    helpers.clearCache()
    vi.restoreAllMocks()
  })

  describe('calculateFocalPoint', () => {
    it('returns cached value if available', async () => {
      // First call - setup mock
      const mockImage = {
        naturalWidth: 800,
        naturalHeight: 600
      }

      // Mock Image constructor
      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 200, y: 150, width: 100, height: 100 }
      })

      const url = 'https://example.com/bird.jpg'
      const result1 = await helpers.calculateFocalPoint(url)
      const result2 = await helpers.calculateFocalPoint(url)

      // Should only call smartcrop once due to caching
      expect(smartcrop.crop).toHaveBeenCalledTimes(1)
      expect(result1).toBe(result2)

      global.Image = originalImage
    })

    it('calculates focal point as percentage', async () => {
      const mockImage = {
        naturalWidth: 1000,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      // Crop centered at (300, 200) with size 100x100
      // Center would be at (350, 250)
      // As percentage of 1000x1000: 35%, 25%
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 300, y: 200, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/bird2.jpg')

      expect(result).toBe('35.0% 25.0%')

      global.Image = originalImage
    })

    it('clamps values to 0-100% range for square images', async () => {
      const mockImage = {
        naturalWidth: 1000,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      // Crop at extreme corner (0, 0)
      // Center would be at (50, 50) = 5%, 5% - clamps to 0% minimum
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 0, y: 0, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/corner.jpg')

      expect(result).toBe('5.0% 5.0%')

      global.Image = originalImage
    })

    it('maps focal point to correct object-position for portrait images', async () => {
      // Portrait image: 750x1000 (aspect 0.75)
      // In square container, visible height = 75% of image
      // halfVisible = 37.5%
      const mockImage = {
        naturalWidth: 750,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      // Focal point at top (5%) - should map to 0% to show top of image
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 325, y: 0, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/portrait.jpg')

      // Focal Y = 5%, which is < halfVisible (37.5%), so object-position Y = 0%
      expect(result).toBe('50.0% 0.0%')

      global.Image = originalImage
    })

    it('maps focal point to correct object-position for extreme portrait images', async () => {
      // Extreme portrait image: 600x1000 (aspect 0.6)
      // In square container, visible height = 60% of image
      // halfVisible = 30%
      const mockImage = {
        naturalWidth: 600,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      // Focal point at 20% from top - should map to 0% (within upper visible region)
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 250, y: 150, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/extreme-portrait.jpg')

      // Focal Y = 20%, which is < halfVisible (30%), so object-position Y = 0%
      expect(result).toBe('50.0% 0.0%')
      // smartcrop should still be called with new algorithm
      expect(smartcrop.crop).toHaveBeenCalled()

      global.Image = originalImage
    })

    it('returns fallback on error', async () => {
      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: ''
        }
        setTimeout(() => img.onerror?.(), 0)
        return img
      })

      const result = await helpers.calculateFocalPoint('https://example.com/broken.jpg')

      expect(result).toBe('50% 35%')

      global.Image = originalImage
    })

    it('returns fallback when smartcrop fails', async () => {
      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: 800,
          naturalHeight: 600
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      smartcrop.crop.mockRejectedValue(new Error('Analysis failed'))

      const result = await helpers.calculateFocalPoint('https://example.com/fail.jpg')

      expect(result).toBe('50% 35%')

      global.Image = originalImage
    })
  })

  describe('useFocalPoint', () => {
    it('initializes with default upper-center position for bird photos', () => {
      const { focalPoint, isReady } = helpers.useFocalPoint()

      expect(focalPoint.value).toBe('50% 35%')
      expect(isReady.value).toBe(true) // Starts visible to show placeholder
    })

    it('sets isReady to true for default bird image', async () => {
      const { focalPoint, isReady, updateFocalPoint } = helpers.useFocalPoint()

      await updateFocalPoint('/default_bird.webp')

      expect(focalPoint.value).toBe('50% 35%')
      expect(isReady.value).toBe(true)
    })

    it('sets isReady to true for null/empty URL', async () => {
      const { isReady, updateFocalPoint } = helpers.useFocalPoint()

      await updateFocalPoint(null)
      expect(isReady.value).toBe(true)

      await updateFocalPoint('')
      expect(isReady.value).toBe(true)
    })

    it('stays visible while calculating then triggers brief fade', async () => {
      const mockImage = {
        naturalWidth: 800,
        naturalHeight: 600
      }

      const originalImage = global.Image
      const originalRAF = global.requestAnimationFrame
      let resolveLoad
      let rafCallback

      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        // Don't auto-resolve, let us control timing
        resolveLoad = () => img.onload?.()
        return img
      })

      // Mock requestAnimationFrame to control timing
      global.requestAnimationFrame = vi.fn((cb) => {
        rafCallback = cb
        return 1
      })

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 400, y: 300, width: 100, height: 100 }
      })

      const { isReady, updateFocalPoint } = helpers.useFocalPoint()

      // Should start visible (to show placeholder)
      expect(isReady.value).toBe(true)

      const promise = updateFocalPoint('https://example.com/bird.jpg')

      // Should stay visible while loading/calculating
      expect(isReady.value).toBe(true)

      // Resolve the image load and smartcrop calculation
      resolveLoad()

      // Wait for the calculation to complete and isReady to be set to false
      await vi.waitFor(() => {
        expect(isReady.value).toBe(false)
      })

      // Now trigger the requestAnimationFrame callback
      rafCallback()
      await promise

      // Should be true after fade-in
      expect(isReady.value).toBe(true)

      global.Image = originalImage
      global.requestAnimationFrame = originalRAF
    })
  })

  describe('processBirdImages', () => {
    it('sets focalPointReady flag on each bird', async () => {
      const birds = [
        { name: 'Sparrow', imageUrl: '/default_bird.webp' },
        { name: 'Robin', imageUrl: '/default_bird.webp' }
      ]

      await helpers.processBirdImages(birds)

      expect(birds[0].focalPointReady).toBe(true)
      expect(birds[1].focalPointReady).toBe(true)
    })

    it('sets default focal point for placeholder images', async () => {
      const birds = [
        { name: 'Sparrow', imageUrl: '/default_bird.webp' }
      ]

      await helpers.processBirdImages(birds)

      expect(birds[0].focalPoint).toBe('50% 35%')
    })

    it('calculates focal point for real images', async () => {
      const mockImage = {
        naturalWidth: 1000,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 400, y: 300, width: 200, height: 200 }
      })

      const birds = [
        { name: 'Sparrow', imageUrl: 'https://example.com/sparrow.jpg' }
      ]

      await helpers.processBirdImages(birds)

      expect(birds[0].focalPoint).toBe('50.0% 40.0%')
      expect(birds[0].focalPointReady).toBe(true)

      global.Image = originalImage
    })

    it('processes birds in parallel', async () => {
      const mockImage = {
        naturalWidth: 1000,
        naturalHeight: 1000
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 450, y: 450, width: 100, height: 100 }
      })

      const birds = [
        { name: 'Bird1', imageUrl: 'https://example.com/bird1.jpg' },
        { name: 'Bird2', imageUrl: 'https://example.com/bird2.jpg' },
        { name: 'Bird3', imageUrl: 'https://example.com/bird3.jpg' }
      ]

      await helpers.processBirdImages(birds)

      // All should be processed
      expect(birds.every(b => b.focalPointReady)).toBe(true)
      expect(birds.every(b => b.focalPoint)).toBe(true)

      global.Image = originalImage
    })
  })

  describe('clearCache', () => {
    it('clears the focal point cache', async () => {
      const mockImage = {
        naturalWidth: 800,
        naturalHeight: 600
      }

      const originalImage = global.Image
      global.Image = vi.fn().mockImplementation(() => {
        const img = {
          crossOrigin: '',
          onload: null,
          onerror: null,
          src: '',
          naturalWidth: mockImage.naturalWidth,
          naturalHeight: mockImage.naturalHeight
        }
        setTimeout(() => img.onload?.(), 0)
        return img
      })

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 400, y: 300, width: 100, height: 100 }
      })

      const url = 'https://example.com/cached.jpg'

      // First call
      await helpers.calculateFocalPoint(url)
      expect(smartcrop.crop).toHaveBeenCalledTimes(1)

      // Second call - should use cache
      await helpers.calculateFocalPoint(url)
      expect(smartcrop.crop).toHaveBeenCalledTimes(1)

      // Clear cache
      helpers.clearCache()

      // Third call - should recalculate
      await helpers.calculateFocalPoint(url)
      expect(smartcrop.crop).toHaveBeenCalledTimes(2)

      global.Image = originalImage
    })
  })
})
