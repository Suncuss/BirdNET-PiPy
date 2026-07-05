import { describe, it, expect, afterEach } from 'vitest'
import { declarePlaybackAudioSession } from '@/utils/audioSession'

// iOS silences pure Web Audio ('ambient' session) with the hardware mute
// switch; views that play through a Web Audio graph must declare 'playback'.
describe('declarePlaybackAudioSession', () => {
  afterEach(() => {
    delete navigator.audioSession
  })

  it("sets the session type to 'playback' when the Audio Session API exists", () => {
    Object.defineProperty(navigator, 'audioSession', {
      value: { type: 'auto' }, configurable: true, writable: true
    })
    declarePlaybackAudioSession()
    expect(navigator.audioSession.type).toBe('playback')
  })

  it('is a no-op on browsers without navigator.audioSession', () => {
    expect(navigator.audioSession).toBeUndefined()
    expect(() => declarePlaybackAudioSession()).not.toThrow()
  })

  it('swallows a throwing setter (partial/older implementations)', () => {
    Object.defineProperty(navigator, 'audioSession', {
      configurable: true,
      get() { return { set type(_) { throw new Error('unsupported') } } }
    })
    expect(() => declarePlaybackAudioSession()).not.toThrow()
  })
})
