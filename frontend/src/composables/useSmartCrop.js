import smartcrop from 'smartcrop'
import { ref } from 'vue'

/**
 * Composable for smart image cropping using focal point detection.
 * Uses smartcrop.js to find the best crop area for wildlife photos.
 */
export function useSmartCrop() {
  // Cache focal points to avoid recalculating
  const focalPointCache = new Map()

  /**
   * Calculate the focal point of an image using smartcrop.js
   * @param {string} imageUrl - URL of the image to analyze
   * @param {Object} options - Optional configuration
   * @param {number} options.targetAspect - Target aspect ratio (width/height), defaults to 1 (square)
   * @returns {Promise<string>} CSS object-position value (e.g., "45% 30%")
   */
  const calculateFocalPoint = async (imageUrl, { targetAspect = 1 } = {}) => {
    // Return cached value if available
    if (focalPointCache.has(imageUrl)) {
      return focalPointCache.get(imageUrl)
    }

    try {
      // Create an image element and wait for it to load
      const img = await loadImage(imageUrl)

      const imgAspect = img.naturalWidth / img.naturalHeight

      // Use target aspect ratio for detection (matches display container)
      const cropWidth = 100
      const cropHeight = Math.round(cropWidth / targetAspect)

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

      // Use smartcrop to find the best crop area
      const result = await smartcrop.crop(img, {
        width: cropWidth,
        height: cropHeight,
        minScale: 0.5,
        boost
      })

      const { topCrop } = result

      // Calculate center of the detected crop area as percentages
      const focalX = ((topCrop.x + topCrop.width / 2) / img.naturalWidth) * 100
      const focalY = ((topCrop.y + topCrop.height / 2) / img.naturalHeight) * 100

      // Calculate the correct object-position based on aspect ratio differences
      // This ensures the focal point is actually visible in the cropped view
      let objectPositionX = focalX
      let objectPositionY = focalY

      if (imgAspect < targetAspect) {
        // Portrait image in square/landscape container
        // Only a portion of the height is visible with object-cover
        const visibleHeightRatio = imgAspect / targetAspect
        const halfVisible = visibleHeightRatio * 50

        // Map focal point to object-position that actually shows it
        if (focalY <= halfVisible) {
          // Focal point is in upper region - align to top
          objectPositionY = 0
        } else if (focalY >= 100 - halfVisible) {
          // Focal point is in lower region - align to bottom
          objectPositionY = 100
        } else {
          // Focal point is in middle - map linearly to center it
          objectPositionY = (focalY - halfVisible) / (100 - 2 * halfVisible) * 100
        }
      } else if (imgAspect > targetAspect) {
        // Landscape image in square/portrait container
        // Only a portion of the width is visible with object-cover
        const visibleWidthRatio = targetAspect / imgAspect
        const halfVisible = visibleWidthRatio * 50

        if (focalX <= halfVisible) {
          objectPositionX = 0
        } else if (focalX >= 100 - halfVisible) {
          objectPositionX = 100
        } else {
          objectPositionX = (focalX - halfVisible) / (100 - 2 * halfVisible) * 100
        }
      }

      // Clamp to reasonable range
      const clampedX = Math.max(0, Math.min(100, objectPositionX))
      const clampedY = Math.max(0, Math.min(100, objectPositionY))

      const position = `${clampedX.toFixed(1)}% ${clampedY.toFixed(1)}%`

      // Cache the result
      focalPointCache.set(imageUrl, position)

      return position
    } catch (error) {
      console.warn(`Smart crop failed for ${imageUrl}:`, error.message)
      // Fall back to upper-center for bird photos (better default than center)
      return '50% 35%'
    }
  }

  /**
   * Load an image and return a promise that resolves when loaded
   * @param {string} url - Image URL
   * @returns {Promise<HTMLImageElement>}
   */
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
   * Create a reactive focal point for an image.
   * Automatically calculates when the URL changes.
   * @param {string} initialUrl - Initial image URL (optional)
   * @returns {{ focalPoint: Ref<string>, isReady: Ref<boolean>, updateFocalPoint: (url: string) => Promise<void> }}
   */
  const useFocalPoint = (initialUrl = null) => {
    const focalPoint = ref('50% 35%') // Default slightly above center for bird photos
    const isReady = ref(true) // Start visible to show placeholder

    const updateFocalPoint = async (url) => {
      if (!url || url === '/default_bird.webp') {
        focalPoint.value = '50% 35%'
        isReady.value = true
        return
      }

      // Calculate focal point first (preloads image into browser cache)
      const newFocalPoint = await calculateFocalPoint(url)

      // Brief hide to trigger fade transition
      isReady.value = false

      // Update focal point
      focalPoint.value = newFocalPoint

      // Small delay to ensure opacity-0 is applied before fading in
      await new Promise(r => requestAnimationFrame(r))

      // Fade in
      isReady.value = true
    }

    if (initialUrl) {
      updateFocalPoint(initialUrl)
    }

    return { focalPoint, isReady, updateFocalPoint }
  }

  /**
   * Process an array of bird objects and add focalPoint property to each.
   * Processes in parallel for better performance.
   * Sets focalPointReady flag when each image is processed.
   * @param {Array<{imageUrl: string}>} birds - Array of bird objects with imageUrl
   * @returns {Promise<void>} Modifies birds in place
   */
  const processBirdImages = async (birds) => {
    await Promise.all(
      birds.map(async (bird) => {
        bird.focalPointReady = false
        if (bird.imageUrl && bird.imageUrl !== '/default_bird.webp') {
          bird.focalPoint = await calculateFocalPoint(bird.imageUrl)
        } else {
          bird.focalPoint = '50% 35%'
        }
        bird.focalPointReady = true
      })
    )
  }

  /**
   * Clear the focal point cache (useful for memory management)
   */
  const clearCache = () => {
    focalPointCache.clear()
  }

  return {
    calculateFocalPoint,
    useFocalPoint,
    processBirdImages,
    clearCache
  }
}
