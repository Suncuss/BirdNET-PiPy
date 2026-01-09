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

    it('clamps values to 10-90% range', async () => {
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
      // Center would be at (50, 50) = 5%, 5% - should clamp to 10%, 10%
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 0, y: 0, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/corner.jpg')

      expect(result).toBe('10.0% 10.0%')

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

      expect(result).toBe('50% 50%')

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

      expect(result).toBe('50% 50%')

      global.Image = originalImage
    })
  })

  describe('useFocalPoint', () => {
    it('initializes with default center position', () => {
      const { focalPoint, isReady } = helpers.useFocalPoint()

      expect(focalPoint.value).toBe('50% 50%')
      expect(isReady.value).toBe(false)
    })

    it('sets isReady to true for default bird image', async () => {
      const { focalPoint, isReady, updateFocalPoint } = helpers.useFocalPoint()

      await updateFocalPoint('/default_bird.png')

      expect(focalPoint.value).toBe('50% 50%')
      expect(isReady.value).toBe(true)
    })

    it('sets isReady to true for null/empty URL', async () => {
      const { isReady, updateFocalPoint } = helpers.useFocalPoint()

      await updateFocalPoint(null)
      expect(isReady.value).toBe(true)

      await updateFocalPoint('')
      expect(isReady.value).toBe(true)
    })

    it('sets isReady to false while calculating', async () => {
      const mockImage = {
        naturalWidth: 800,
        naturalHeight: 600
      }

      const originalImage = global.Image
      let resolveLoad
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

      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 400, y: 300, width: 100, height: 100 }
      })

      const { isReady, updateFocalPoint } = helpers.useFocalPoint()

      const promise = updateFocalPoint('https://example.com/bird.jpg')

      // Should be false while loading
      expect(isReady.value).toBe(false)

      // Resolve the image load
      resolveLoad()
      await promise

      // Should be true after complete
      expect(isReady.value).toBe(true)

      global.Image = originalImage
    })
  })

  describe('processBirdImages', () => {
    it('sets focalPointReady flag on each bird', async () => {
      const birds = [
        { name: 'Sparrow', imageUrl: '/default_bird.png' },
        { name: 'Robin', imageUrl: '/default_bird.png' }
      ]

      await helpers.processBirdImages(birds)

      expect(birds[0].focalPointReady).toBe(true)
      expect(birds[1].focalPointReady).toBe(true)
    })

    it('sets default focal point for placeholder images', async () => {
      const birds = [
        { name: 'Sparrow', imageUrl: '/default_bird.png' }
      ]

      await helpers.processBirdImages(birds)

      expect(birds[0].focalPoint).toBe('50% 50%')
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
