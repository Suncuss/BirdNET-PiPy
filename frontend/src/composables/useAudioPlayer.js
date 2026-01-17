import { ref, onUnmounted } from 'vue'
import { useLogger } from './useLogger'

/**
 * Composable for single-shot audio playback with play/stop toggle.
 * Handles cleanup on unmount and error handling.
 *
 * Note: This is for simple audio playback (like bird call samples).
 * For live streaming audio with visualization, see LiveFeed.vue which has
 * specialized requirements (AudioContext, continuous streaming, spectrogram).
 */
export function useAudioPlayer() {
  const logger = useLogger('useAudioPlayer')

  // State
  const currentPlayingId = ref(null)
  const audioElement = ref(null)
  const audioInstanceId = ref(null) // Unique ID per audio instance for race condition detection
  const isLoading = ref(false)
  const error = ref(null)
  let instanceCounter = 0

  /**
   * Stop current audio playback and clean up resources.
   */
  const stopAudio = () => {
    if (!audioElement.value) return

    try {
      audioElement.value.pause()
      audioElement.value.onended = null
      audioElement.value.onerror = null
      audioElement.value.src = ''
    } catch (err) {
      logger.warn('Error stopping audio:', err)
    }

    audioElement.value = null
    audioInstanceId.value = null
    currentPlayingId.value = null
    isLoading.value = false
  }

  /**
   * Toggle audio playback for an item.
   *
   * @param {string|number} id - Unique identifier for the audio item
   * @param {string} audioUrl - URL of the audio file to play
   * @returns {Promise<boolean>} - True if playback started, false otherwise
   */
  const togglePlay = async (id, audioUrl) => {
    if (!id || !audioUrl) {
      logger.warn('togglePlay called without id or audioUrl')
      return false
    }

    // If same item is playing, stop it
    if (currentPlayingId.value === id) {
      stopAudio()
      return false
    }

    // Stop any currently playing audio
    stopAudio()

    // Create new audio element with unique instance ID
    const audio = new Audio(audioUrl)
    const thisInstanceId = ++instanceCounter
    audioElement.value = audio
    audioInstanceId.value = thisInstanceId
    currentPlayingId.value = id
    isLoading.value = true
    error.value = null

    // Helper to check if this audio instance is still the current one
    const isCurrentAudio = () => currentPlayingId.value === id && audioInstanceId.value === thisInstanceId

    // Set up event handlers
    audio.onended = () => {
      logger.debug('Audio playback ended', { id })
      if (isCurrentAudio()) {
        stopAudio()
      }
    }

    audio.onerror = (event) => {
      // Only update error state if this audio is still the current one
      if (!isCurrentAudio()) return

      const errorMessage = getAudioErrorMessage(event.target?.error)
      logger.warn('Audio playback error:', { id, error: errorMessage })
      error.value = errorMessage
      stopAudio()
    }

    // Start playback
    try {
      await audio.play()
      // Only update loading state if this audio is still the current one
      if (isCurrentAudio()) {
        isLoading.value = false
      }
      logger.debug('Audio playback started', { id })
      return true
    } catch (err) {
      // Only update state if this audio is still the current one
      if (!isCurrentAudio()) return false

      logger.warn('Failed to play audio:', err)
      error.value = err.message || 'Failed to play audio'
      stopAudio()
      return false
    }
  }

  /**
   * Check if a specific item is currently playing.
   *
   * @param {string|number} id - The item ID to check
   * @returns {boolean} - True if the item is currently playing
   */
  const isPlaying = (id) => {
    return currentPlayingId.value === id
  }

  /**
   * Get human-readable error message from MediaError.
   * Uses numeric codes directly to avoid dependency on MediaError global.
   */
  const getAudioErrorMessage = (mediaError) => {
    if (!mediaError) return 'Unknown audio error'

    // MediaError codes (1=ABORTED, 2=NETWORK, 3=DECODE, 4=SRC_NOT_SUPPORTED)
    switch (mediaError.code) {
      case 1: // MEDIA_ERR_ABORTED
        return 'Audio playback aborted'
      case 2: // MEDIA_ERR_NETWORK
        return 'Network error loading audio'
      case 3: // MEDIA_ERR_DECODE
        return 'Audio decode error'
      case 4: // MEDIA_ERR_SRC_NOT_SUPPORTED
        return 'Audio format not supported'
      default:
        return 'Audio playback error'
    }
  }

  /**
   * Clear any error state.
   */
  const clearError = () => {
    error.value = null
  }

  // Clean up on component unmount
  onUnmounted(() => {
    stopAudio()
  })

  return {
    // State
    currentPlayingId,
    isLoading,
    error,

    // Methods
    togglePlay,
    stopAudio,
    isPlaying,
    clearError
  }
}
