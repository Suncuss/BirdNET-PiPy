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
   * @returns {Promise<string>} CSS object-position value (e.g., "45% 30%")
   */
  const calculateFocalPoint = async (imageUrl) => {
    // Return cached value if available
    if (focalPointCache.has(imageUrl)) {
      return focalPointCache.get(imageUrl)
    }

    try {
      // Create an image element and wait for it to load
      const img = await loadImage(imageUrl)

      // Use smartcrop to find the best crop area
      // We use a small crop size just for detection - the actual display uses CSS
      const result = await smartcrop.crop(img, {
        width: 100,
        height: 100,
        // Boost settings to prefer faces/features
        minScale: 0.5
      })

      const { topCrop } = result

      // Calculate center of the detected crop area as percentages
      const x = ((topCrop.x + topCrop.width / 2) / img.naturalWidth) * 100
      const y = ((topCrop.y + topCrop.height / 2) / img.naturalHeight) * 100

      // Clamp values to reasonable range (10-90%) to avoid extreme positioning
      const clampedX = Math.max(10, Math.min(90, x))
      const clampedY = Math.max(10, Math.min(90, y))

      const position = `${clampedX.toFixed(1)}% ${clampedY.toFixed(1)}%`

      // Cache the result
      focalPointCache.set(imageUrl, position)

      return position
    } catch (error) {
      console.warn(`Smart crop failed for ${imageUrl}:`, error.message)
      // Fall back to center positioning
      return '50% 50%'
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
    const focalPoint = ref('50% 50%')
    const isReady = ref(false)

    const updateFocalPoint = async (url) => {
      isReady.value = false
      if (!url || url === '/default_bird.png') {
        focalPoint.value = '50% 50%'
        isReady.value = true
        return
      }
      focalPoint.value = await calculateFocalPoint(url)
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
        if (bird.imageUrl && bird.imageUrl !== '/default_bird.png') {
          bird.focalPoint = await calculateFocalPoint(bird.imageUrl)
        } else {
          bird.focalPoint = '50% 50%'
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
