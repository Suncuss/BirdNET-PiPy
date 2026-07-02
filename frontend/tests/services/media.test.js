import { describe, it, expect } from 'vitest'
import { getAudioUrl, getSpectrogramUrl } from '@/services/media'
import { API_BASE } from '@/services/baseUrl'

describe('media URL helpers', () => {
  describe('getAudioUrl', () => {
    it('builds a bare URL when no signature is given', () => {
      expect(getAudioUrl('clip.mp3')).toBe(`${API_BASE}/audio/clip.mp3`)
    })

    it('appends the signed query when provided', () => {
      expect(getAudioUrl('clip.mp3', 'exp=123&sig=abc'))
        .toBe(`${API_BASE}/audio/clip.mp3?exp=123&sig=abc`)
    })

    it('encodes the filename', () => {
      expect(getAudioUrl('a b.mp3')).toBe(`${API_BASE}/audio/a%20b.mp3`)
    })

    it('returns empty string when there is no filename (even with a sig)', () => {
      expect(getAudioUrl('')).toBe('')
      expect(getAudioUrl(undefined, 'exp=1&sig=x')).toBe('')
    })
  })

  describe('getSpectrogramUrl', () => {
    it('builds a bare URL when no signature is given', () => {
      expect(getSpectrogramUrl('s.webp')).toBe(`${API_BASE}/spectrogram/s.webp`)
    })

    it('appends the signed query when provided', () => {
      expect(getSpectrogramUrl('s.webp', 'exp=9&sig=z'))
        .toBe(`${API_BASE}/spectrogram/s.webp?exp=9&sig=z`)
    })

    it('returns empty string when there is no filename', () => {
      expect(getSpectrogramUrl('')).toBe('')
    })
  })
})
