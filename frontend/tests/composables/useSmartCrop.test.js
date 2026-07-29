/**
 * Tests for useSmartCrop composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { useSmartCrop, clearFocalPointCache, mapFocalToObjectPosition } from '@/composables/useSmartCrop'

// Mock smartcrop library
vi.mock('smartcrop', () => ({
  default: {
    crop: vi.fn()
  }
}))

describe('useSmartCrop', () => {
  let smartcrop
  let helpers
  let currentImg

  // Stub the global Image constructor with a synthetic element that fires
  // onload (or onerror) on a macrotask, like a real browser load. Undone for
  // every test by afterEach's unstubAllGlobals, so a failing assertion can't
  // leak the stub into later tests. `manual: true` fires nothing — the
  // returned load() hands the test control of the timing.
  const stubImage = ({ width = 800, height = 600, fail = false, manual = false } = {}) => {
    vi.stubGlobal('Image', vi.fn(() => {
      currentImg = {
        crossOrigin: '',
        onload: null,
        onerror: null,
        src: '',
        naturalWidth: width,
        naturalHeight: height
      }
      if (!manual) {
        setTimeout(() => (fail ? currentImg.onerror?.() : currentImg.onload?.()), 0)
      }
      return currentImg
    }))
    return { load: () => currentImg.onload?.() }
  }

  beforeEach(async () => {
    smartcrop = (await import('smartcrop')).default
    vi.clearAllMocks()
    helpers = useSmartCrop()
  })

  afterEach(() => {
    clearFocalPointCache()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  describe('calculateFocalPoint', () => {
    it('returns cached value if available', async () => {
      stubImage()
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 200, y: 150, width: 100, height: 100 }
      })

      const url = 'https://example.com/bird.jpg'
      const result1 = await helpers.calculateFocalPoint(url)
      const result2 = await helpers.calculateFocalPoint(url)

      // Should only call smartcrop once due to caching
      expect(smartcrop.crop).toHaveBeenCalledTimes(1)
      expect(result1).toBe(result2)
    })

    it('calculates focal point as percentage', async () => {
      stubImage({ width: 1000, height: 1000 })

      // Crop centered at (300, 200) with size 100x100
      // Center would be at (350, 250)
      // As percentage of 1000x1000: 35%, 25%
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 300, y: 200, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/bird2.jpg')

      expect(result).toBe('35.0% 25.0%')
    })

    it('clamps values to 0-100% range for square images', async () => {
      stubImage({ width: 1000, height: 1000 })

      // Crop at extreme corner (0, 0)
      // Center would be at (50, 50) = 5%, 5% - clamps to 0% minimum
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 0, y: 0, width: 100, height: 100 }
      })

      const result = await helpers.calculateFocalPoint('https://example.com/corner.jpg')

      expect(result).toBe('5.0% 5.0%')
    })

    it('runs detection once per URL even across different target aspects', async () => {
      stubImage()
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 300, y: 190, width: 100, height: 100 }
      })

      const url = 'https://example.com/multi-aspect.jpg'
      const square = await helpers.calculateFocalPoint(url)
      const wide = await helpers.calculateFocalPoint(url, { targetAspect: 2 })

      // One cached detection, two different mappings (the mapping arithmetic
      // itself is pinned by the mapFocalToObjectPosition tests).
      expect(smartcrop.crop).toHaveBeenCalledTimes(1)
      expect(square).not.toBe(wide)
    })

    it('returns fallback on error', async () => {
      stubImage({ fail: true })

      const result = await helpers.calculateFocalPoint('https://example.com/broken.jpg')

      expect(result).toBe('50% 35%')
    })

    it('returns fallback when smartcrop fails', async () => {
      stubImage()
      smartcrop.crop.mockRejectedValue(new Error('Analysis failed'))

      const result = await helpers.calculateFocalPoint('https://example.com/fail.jpg')

      expect(result).toBe('50% 35%')
    })
  })

  describe('mapFocalToObjectPosition', () => {
    it('returns the default position for missing focal data', () => {
      expect(mapFocalToObjectPosition(null)).toBe('50% 35%')
    })

    it('falls back to raw focal percentages without a container aspect', () => {
      // Aspect-agnostic fallback: X%/Y% object-position keeps the focal point
      // visible in a box of any shape, so no remap is needed or possible.
      const focal = { focalX: 20, focalY: 80, imgAspect: 1.5 }
      expect(mapFocalToObjectPosition(focal)).toBe('20.0% 80.0%')
      expect(mapFocalToObjectPosition(focal, null)).toBe('20.0% 80.0%')
      expect(mapFocalToObjectPosition(focal, 0)).toBe('20.0% 80.0%')
      expect(mapFocalToObjectPosition(focal, NaN)).toBe('20.0% 80.0%')
    })

    it('snaps a high focal point to the top in a wide container', () => {
      // Square image in a 2:1 box: visible height 50%, so a focal point in
      // the top quarter aligns to the top edge instead of "centering" past it.
      expect(mapFocalToObjectPosition({ focalX: 50, focalY: 10, imgAspect: 1 }, 2))
        .toBe('50.0% 0.0%')
    })

    it('snaps an edge focal point horizontally in a taller container', () => {
      expect(mapFocalToObjectPosition({ focalX: 90, focalY: 50, imgAspect: 2 }, 1))
        .toBe('100.0% 50.0%')
    })

    it('leaves both axes raw when image and container aspects match', () => {
      expect(mapFocalToObjectPosition({ focalX: 33, focalY: 66, imgAspect: 1.5 }, 1.5))
        .toBe('33.0% 66.0%')
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

      await updateFocalPoint('default_bird.webp')

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
      const { load } = stubImage({ manual: true })
      let rafCallback
      vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => {
        rafCallback = cb
        return 1
      }))
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
      load()

      // Wait for the calculation to complete and isReady to be set to false
      await vi.waitFor(() => {
        expect(isReady.value).toBe(false)
      })

      // Now trigger the requestAnimationFrame callback
      rafCallback()
      await promise

      // Should be true after fade-in
      expect(isReady.value).toBe(true)
    })

    it('remaps the focal point to the tracked container aspect and follows resizes', async () => {
      stubImage()
      // Focal center (350, 240) of 800x600 → 43.75%, 40%
      smartcrop.crop.mockResolvedValue({
        topCrop: { x: 300, y: 190, width: 100, height: 100 }
      })

      let roCallback
      const observedElements = []
      vi.stubGlobal('ResizeObserver', class {
        constructor(cb) { roCallback = cb }
        observe(el) { observedElements.push(el) }
        disconnect() {}
      })

      const containerRef = ref(null)
      const focal = helpers.useFocalPoint(containerRef)

      await focal.updateFocalPoint('https://example.com/tracked.jpg')

      // No container measured yet → raw focal percentages (the aspect-agnostic fallback)
      expect(focal.focalPoint.value).toBe('43.8% 40.0%')

      // Container element appears (v-if resolves) → gets observed
      const el = document.createElement('div')
      containerRef.value = el
      await nextTick()
      expect(observedElements).toContain(el)

      // Container reports 2:1 → vertical crop, focal Y recentered to 20%
      roCallback([{ contentRect: { width: 600, height: 300 } }])
      await nextTick()
      expect(focal.focalPoint.value).toBe('43.8% 20.0%')

      // Resize to square → horizontal crop, focal X recentered to 25%
      roCallback([{ contentRect: { width: 300, height: 300 } }])
      await nextTick()
      expect(focal.focalPoint.value).toBe('25.0% 40.0%')
    })
  })

  describe('clearFocalPointCache', () => {
    it('clears the focal point cache', async () => {
      stubImage()
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
      clearFocalPointCache()

      // Third call - should recalculate
      await helpers.calculateFocalPoint(url)
      expect(smartcrop.crop).toHaveBeenCalledTimes(2)
    })
  })
})
