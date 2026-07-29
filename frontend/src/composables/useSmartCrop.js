import smartcrop from 'smartcrop'
import { ref, computed, watch, getCurrentScope, onScopeDispose } from 'vue'
import { isDefaultBirdImageUrl } from '@/services/media'
import { swapImageWithFade } from '@/utils/imageFade'

// Module-level so results survive component remounts (BirdDetails remounts per
// navigation) and are shared across all consumers. Holds raw focal data
// ({ focalX, focalY, imgAspect }): one detection per URL serves every box
// shape via mapFocalToObjectPosition.
const focalPointCache = new Map()

/**
 * Reset the module-level cache. Not part of the composable API — in production
 * the cache lives for the session; tests import this directly to isolate
 * cached results between cases.
 */
export function clearFocalPointCache() {
  focalPointCache.clear()
}

// Upper-center: better default than dead center for bird photos.
const DEFAULT_POSITION = '50% 35%'

const clampPercent = (value) => Math.max(0, Math.min(100, value))

// Map a focal coordinate (image %) to the object-position % that centers it,
// given the fraction of that axis object-cover leaves visible. A focal point
// whose centered window would run past the image edge snaps to that edge.
const centerFocal = (focal, visibleRatio) => {
  const halfVisible = visibleRatio * 50
  if (focal <= halfVisible) return 0
  if (focal >= 100 - halfVisible) return 100
  return ((focal - halfVisible) / (100 - 2 * halfVisible)) * 100
}

/**
 * Map raw focal data to a CSS object-position for an object-cover container
 * of the given aspect ratio (width/height).
 *
 * Without a usable container aspect, the raw focal percentages are used
 * directly: `object-position: X% Y%` aligns the image's X% point with the
 * container's X% point, which keeps the focal point visible in a box of any
 * shape — just not perfectly centered.
 *
 * @param {{ focalX: number, focalY: number, imgAspect: number }|null} focal
 * @param {number|null} containerAspect
 * @returns {string} CSS object-position value
 */
export function mapFocalToObjectPosition(focal, containerAspect = null) {
  if (!focal) return DEFAULT_POSITION
  let x = focal.focalX
  let y = focal.focalY
  if (containerAspect > 0 && focal.imgAspect > 0) {
    if (focal.imgAspect < containerAspect) {
      // Image is taller than the container — object-cover crops vertically.
      y = centerFocal(y, focal.imgAspect / containerAspect)
    } else if (focal.imgAspect > containerAspect) {
      x = centerFocal(x, containerAspect / focal.imgAspect)
    }
  }
  return `${clampPercent(x).toFixed(1)}% ${clampPercent(y).toFixed(1)}%`
}

const loadImage = (url) => {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`))
    img.src = url
  })
}

/**
 * Detect (or return the cached) raw focal point of an image using
 * smartcrop.js. Also serves as a preload — the browser caches the decoded
 * image. Returns null when the image can't be loaded or analyzed (callers
 * fall back to the default position); failures are not cached, so a transient
 * network error doesn't pin the fallback for the whole session.
 */
const getFocalData = async (imageUrl) => {
  if (focalPointCache.has(imageUrl)) {
    return focalPointCache.get(imageUrl)
  }

  try {
    const img = await loadImage(imageUrl)

    const imgAspect = img.naturalWidth / img.naturalHeight

    // Build boost regions for bird photos
    // Birds typically have heads in the upper portion of the image
    const boost = []

    // Boost upper portion - stronger for portrait images
    if (imgAspect < 1) {
      boost.push({
        x: 0,
        y: 0,
        width: img.naturalWidth,
        height: img.naturalHeight * 0.4,
        weight: 1.5
      })
    } else {
      boost.push({
        x: 0,
        y: 0,
        width: img.naturalWidth,
        height: img.naturalHeight * 0.5,
        weight: 0.3
      })
    }

    // Square detection window regardless of display shape — the display
    // mapping happens per-container in mapFocalToObjectPosition.
    const result = await smartcrop.crop(img, {
      width: 100,
      height: 100,
      minScale: 0.5,
      boost
    })

    const { topCrop } = result

    // Center of the detected crop area, as percentages of the image.
    const focal = {
      focalX: ((topCrop.x + topCrop.width / 2) / img.naturalWidth) * 100,
      focalY: ((topCrop.y + topCrop.height / 2) / img.naturalHeight) * 100,
      imgAspect
    }

    focalPointCache.set(imageUrl, focal)
    return focal
  } catch (error) {
    console.warn(`Smart crop failed for ${imageUrl}:`, error.message)
    return null
  }
}

/**
 * Calculate a static object-position for an image in a container of a known,
 * fixed aspect ratio (e.g. the gallery's aspect-square cards).
 * @param {string} imageUrl - URL of the image to analyze
 * @param {Object} options - Optional configuration
 * @param {number} options.targetAspect - Container aspect ratio (width/height), defaults to 1 (square)
 * @returns {Promise<string>} CSS object-position value (e.g., "45% 30%")
 */
const calculateFocalPoint = async (imageUrl, { targetAspect = 1 } = {}) =>
  mapFocalToObjectPosition(await getFocalData(imageUrl), targetAspect)

/**
 * Reactive focal point for a single image. With a container element ref, the
 * object-position tracks the container's measured aspect ratio across resizes
 * and breakpoints; without one — or before it mounts, or when ResizeObserver
 * is unavailable — it uses the raw-percentage fallback (see
 * mapFocalToObjectPosition).
 *
 * @param {Ref<HTMLElement>|null} containerRef - template ref of the element the image covers
 * @returns {{ focalPoint: Ref<string>, isReady: Ref<boolean>, updateFocalPoint: (url: string) => Promise<void> }}
 */
const useFocalPoint = (containerRef = null) => {
  const focalData = ref(null)
  const containerAspect = ref(null)
  const isReady = ref(true) // Start visible to show placeholder

  const focalPoint = computed(() =>
    mapFocalToObjectPosition(focalData.value, containerAspect.value)
  )

  if (containerRef && typeof ResizeObserver !== 'undefined') {
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (height <= 0) return
      // Quantized (nearest 0.05) so frame-by-frame drag resizes coalesce into
      // one write instead of re-rendering the consumer for sub-percent shifts.
      containerAspect.value = Math.round((width / height) * 20) / 20
    })
    // The container typically mounts late (behind a v-if on fetched data),
    // so follow the ref instead of observing once at setup.
    watch(containerRef, (el) => {
      observer.disconnect()
      if (el) observer.observe(el)
    }, { immediate: true, flush: 'post' })
    if (getCurrentScope()) onScopeDispose(() => observer.disconnect())
  }

  const updateFocalPoint = async (url) => {
    if (!url || isDefaultBirdImageUrl(url)) {
      focalData.value = null
      isReady.value = true
      return
    }

    // Detect first (also preloads the image into the browser cache), then
    // swap with a brief fade.
    const focal = await getFocalData(url)

    await swapImageWithFade(
      (visible) => { isReady.value = visible },
      () => { focalData.value = focal }
    )
  }

  return { focalPoint, isReady, updateFocalPoint }
}

/**
 * Composable for smart image cropping using focal point detection.
 * Uses smartcrop.js to find the best crop area for wildlife photos.
 */
export function useSmartCrop() {
  return {
    calculateFocalPoint,
    useFocalPoint
  }
}
