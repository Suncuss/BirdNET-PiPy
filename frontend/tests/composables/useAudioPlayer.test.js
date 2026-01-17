/**
 * Tests for useAudioPlayer composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAudioPlayer } from '@/composables/useAudioPlayer'

// Mock useLogger
vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  })
}))

// Track all created audio instances for testing
let audioInstances = []
let nextPlayBehavior = 'resolve' // 'resolve', 'reject', or 'pending'
let pendingPlayResolve = null

// Mock Audio element
class MockAudio {
  constructor(url) {
    this.src = url
    this.paused = true
    this.onended = null
    this.onerror = null
    audioInstances.push(this)
  }

  play() {
    if (nextPlayBehavior === 'reject') {
      return Promise.reject(new Error('Playback failed'))
    }
    if (nextPlayBehavior === 'pending') {
      return new Promise(resolve => {
        pendingPlayResolve = resolve
      })
    }
    this.paused = false
    return Promise.resolve()
  }

  pause() {
    this.paused = true
  }

  // Test helper to simulate audio ending
  _simulateEnded() {
    if (this.onended) {
      this.onended()
    }
  }

  // Test helper to simulate error
  _simulateError(errorCode = 2) {
    if (this.onerror) {
      this.onerror({
        target: {
          error: {
            code: errorCode
          }
        }
      })
    }
  }
}

describe('useAudioPlayer', () => {
  let originalAudio

  beforeEach(() => {
    // Save original Audio constructor
    originalAudio = globalThis.Audio
    // Replace with mock - use both global and globalThis for compatibility
    global.Audio = MockAudio
    globalThis.Audio = MockAudio
    // Reset test state
    audioInstances = []
    nextPlayBehavior = 'resolve'
    pendingPlayResolve = null
  })

  afterEach(() => {
    // Restore original Audio constructor
    global.Audio = originalAudio
    globalThis.Audio = originalAudio
    vi.restoreAllMocks()
  })

  describe('initialization', () => {
    it('returns audio player object with all expected properties', () => {
      const player = useAudioPlayer()

      expect(player).toHaveProperty('currentPlayingId')
      expect(player).toHaveProperty('isLoading')
      expect(player).toHaveProperty('error')
      expect(player).toHaveProperty('togglePlay')
      expect(player).toHaveProperty('stopAudio')
      expect(player).toHaveProperty('isPlaying')
      expect(player).toHaveProperty('clearError')
    })

    it('initializes with null currentPlayingId', () => {
      const player = useAudioPlayer()
      expect(player.currentPlayingId.value).toBe(null)
    })

    it('initializes with isLoading as false', () => {
      const player = useAudioPlayer()
      expect(player.isLoading.value).toBe(false)
    })

    it('initializes with null error', () => {
      const player = useAudioPlayer()
      expect(player.error.value).toBe(null)
    })
  })

  describe('togglePlay', () => {
    it('starts playback and sets currentPlayingId', async () => {
      const player = useAudioPlayer()

      const result = await player.togglePlay('test-id', 'http://example.com/audio.mp3')

      expect(result).toBe(true)
      expect(player.currentPlayingId.value).toBe('test-id')
      expect(player.isLoading.value).toBe(false)
    })

    it('stops playback when same id is toggled', async () => {
      const player = useAudioPlayer()

      // Start playback
      await player.togglePlay('test-id', 'http://example.com/audio.mp3')
      expect(player.currentPlayingId.value).toBe('test-id')

      // Toggle same id - should stop
      const result = await player.togglePlay('test-id', 'http://example.com/audio.mp3')

      expect(result).toBe(false)
      expect(player.currentPlayingId.value).toBe(null)
    })

    it('switches to new audio when different id is played', async () => {
      const player = useAudioPlayer()

      // Start first audio
      await player.togglePlay('id-1', 'http://example.com/audio1.mp3')
      expect(player.currentPlayingId.value).toBe('id-1')

      // Start different audio
      await player.togglePlay('id-2', 'http://example.com/audio2.mp3')
      expect(player.currentPlayingId.value).toBe('id-2')
    })

    it('returns false and does not play if id is missing', async () => {
      const player = useAudioPlayer()

      const result = await player.togglePlay(null, 'http://example.com/audio.mp3')

      expect(result).toBe(false)
      expect(player.currentPlayingId.value).toBe(null)
    })

    it('returns false and does not play if audioUrl is missing', async () => {
      const player = useAudioPlayer()

      const result = await player.togglePlay('test-id', null)

      expect(result).toBe(false)
      expect(player.currentPlayingId.value).toBe(null)
    })

    it('handles playback failure gracefully', async () => {
      const player = useAudioPlayer()

      // Make next play() call fail
      nextPlayBehavior = 'reject'

      const result = await player.togglePlay('test-id', 'http://example.com/audio.mp3')

      expect(result).toBe(false)
      expect(player.currentPlayingId.value).toBe(null)
      expect(player.error.value).toBe('Playback failed')
    })

    it('sets isLoading during playback initialization', async () => {
      const player = useAudioPlayer()

      // Make play() return a pending promise
      nextPlayBehavior = 'pending'

      const playPromise = player.togglePlay('test-id', 'http://example.com/audio.mp3')

      // Should be loading
      expect(player.isLoading.value).toBe(true)

      // Resolve playback
      pendingPlayResolve()
      await playPromise

      // Should no longer be loading
      expect(player.isLoading.value).toBe(false)
    })
  })

  describe('stopAudio', () => {
    it('stops current playback', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')
      expect(player.currentPlayingId.value).toBe('test-id')

      player.stopAudio()

      expect(player.currentPlayingId.value).toBe(null)
    })

    it('does nothing if no audio is playing', () => {
      const player = useAudioPlayer()

      // Should not throw
      player.stopAudio()

      expect(player.currentPlayingId.value).toBe(null)
    })
  })

  describe('isPlaying', () => {
    it('returns true when id matches currentPlayingId', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')

      expect(player.isPlaying('test-id')).toBe(true)
    })

    it('returns false when id does not match', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')

      expect(player.isPlaying('other-id')).toBe(false)
    })

    it('returns false when nothing is playing', () => {
      const player = useAudioPlayer()

      expect(player.isPlaying('any-id')).toBe(false)
    })
  })

  describe('clearError', () => {
    it('clears the error value', async () => {
      const player = useAudioPlayer()

      // Set up a failure to create an error
      nextPlayBehavior = 'reject'

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')
      expect(player.error.value).toBe('Playback failed')

      player.clearError()

      expect(player.error.value).toBe(null)
    })
  })

  describe('audio events', () => {
    it('resets state when audio ends', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')
      expect(player.currentPlayingId.value).toBe('test-id')

      // Get the audio instance that was created
      const audioInstance = audioInstances[0]

      // Simulate audio ending
      audioInstance._simulateEnded()

      expect(player.currentPlayingId.value).toBe(null)
    })

    it('resets state and sets error on audio error', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('test-id', 'http://example.com/audio.mp3')
      expect(player.currentPlayingId.value).toBe('test-id')

      // Get the audio instance that was created
      const audioInstance = audioInstances[0]

      // Simulate audio error (MEDIA_ERR_NETWORK = 2)
      audioInstance._simulateError(2)

      expect(player.currentPlayingId.value).toBe(null)
      expect(player.error.value).toBe('Network error loading audio')
    })

    it('ignores events from stale audio instances', async () => {
      const player = useAudioPlayer()

      // Start first audio
      await player.togglePlay('id-1', 'http://example.com/audio1.mp3')
      const firstAudio = audioInstances[0]

      // Switch to second audio
      await player.togglePlay('id-2', 'http://example.com/audio2.mp3')
      expect(player.currentPlayingId.value).toBe('id-2')

      // Simulate ended event from FIRST audio (stale)
      firstAudio._simulateEnded()

      // Should NOT have stopped the second audio
      expect(player.currentPlayingId.value).toBe('id-2')
    })

    it('ignores errors from stale audio instances', async () => {
      const player = useAudioPlayer()

      // Start first audio
      await player.togglePlay('id-1', 'http://example.com/audio1.mp3')
      const firstAudio = audioInstances[0]

      // Switch to second audio
      await player.togglePlay('id-2', 'http://example.com/audio2.mp3')
      expect(player.currentPlayingId.value).toBe('id-2')
      expect(player.error.value).toBe(null)

      // Simulate error from FIRST audio (stale)
      firstAudio._simulateError(2)

      // Should NOT have affected the second audio
      expect(player.currentPlayingId.value).toBe('id-2')
      expect(player.error.value).toBe(null)
    })
  })

  describe('numeric and string ids', () => {
    it('works with numeric ids', async () => {
      const player = useAudioPlayer()

      await player.togglePlay(123, 'http://example.com/audio.mp3')

      expect(player.currentPlayingId.value).toBe(123)
      expect(player.isPlaying(123)).toBe(true)
    })

    it('works with string ids', async () => {
      const player = useAudioPlayer()

      await player.togglePlay('abc-123', 'http://example.com/audio.mp3')

      expect(player.currentPlayingId.value).toBe('abc-123')
      expect(player.isPlaying('abc-123')).toBe(true)
    })
  })
})
