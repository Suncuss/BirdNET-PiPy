/**
 * Tests for the spectrogram colour pipeline that backs the detection-detail
 * player. The key behaviour under test is that the high-pass filter dims the
 * spectrogram by the filter's REAL attenuation mapped into the dB brightness
 * window — i.e. it walks DOWN the green colormap the same gentle amount the
 * Live Feed's post-filter analyser shows (~15% per 12 dB), rather than laying
 * opaque black over the image.
 */
import { describe, it, expect } from 'vitest'
import {
  computeBaseBrightness,
  buildSpectrogramRgbaLut,
  spectrogramFilterRowOffsets,
  colorizeBrightness,
  spectrogramColor,
  SPECTROGRAM_FLOOR_DB
} from '@/utils/spectrogram'

describe('computeBaseBrightness', () => {
  it('maps the per-clip peak to full brightness and the floor to zero', () => {
    // frames=2, bins=3, peak = 1. Layout is row-major [frame*bins + bin].
    // frame 0: bin0 peak, bin1 -20 dB, bin2 -80 dB; frame 1: all peak.
    const mags = Float32Array.from([1, 0.1, 1e-4, 1, 1, 1])
    const spec = { mags, frames: 2, bins: 3, max: 1 }

    const { baseBytes, width, height } = computeBaseBrightness(spec)
    expect(width).toBe(2)
    expect(height).toBe(3)

    // Output is laid out [row*frames + f] with row 0 = top = highest frequency
    // (bin = bins-1-row). -20 dB sits a quarter down the 80 dB window → ~191.
    const at = (row, f) => baseBytes[row * width + f]
    expect(at(0, 0)).toBe(0) // top row, bin2, -80 dB → floor
    expect(at(0, 1)).toBe(255) // top row, frame1, peak
    expect(at(1, 0)).toBe(191) // bin1, -20 dB → 1 - 20/80 = 0.75
    expect(at(2, 0)).toBe(255) // bottom row, bin0, peak
  })
})

describe('spectrogramFilterRowOffsets', () => {
  it('is zero in the passband (|H| = 1)', () => {
    const out = new Int16Array(3)
    spectrogramFilterRowOffsets(Float32Array.from([1, 1, 1]), out)
    expect(Array.from(out)).toEqual([0, 0, 0])
  })

  it('maps the real dB attenuation into 0–255 brightness units (back-to-front)', () => {
    // filterMag indexed by bin (bin0 = DC). High-pass: low bins cut, high pass.
    // bin0 = -12 dB, bin1 = -3 dB, bin2 = 0 dB.
    const filterMag = Float32Array.from([0.25119, 0.70795, 1.0])
    const out = new Int16Array(3)
    spectrogramFilterRowOffsets(filterMag, out)

    // row 0 = top = high freq = bin2 (passband), row 2 = bin0 (most cut).
    expect(out[0]).toBe(0)
    expect(out[1]).toBe(Math.round((-3 / SPECTROGRAM_FLOOR_DB) * 255)) // -10
    expect(out[2]).toBe(Math.round((-12 / SPECTROGRAM_FLOOR_DB) * 255)) // -38

    // The truthful subtlety: a 12 dB cut is only ~15% of the 80 dB window.
    expect(Math.abs(out[2]) / 255).toBeCloseTo(0.15, 2)
  })

  it('floors a near-zero magnitude instead of returning -Infinity', () => {
    const out = new Int16Array(1)
    spectrogramFilterRowOffsets(Float32Array.from([0]), out)
    expect(Number.isFinite(out[0])).toBe(true)
    expect(out[0]).toBeLessThan(-300) // deep cut, but finite
  })
})

describe('colorizeBrightness', () => {
  const lut = buildSpectrogramRgbaLut()
  const base = { baseBytes: Uint8Array.from([100, 200, 50, 250]), width: 2, height: 2 }

  it('reproduces the colormap at the base brightness when offsets are zero', () => {
    const out = new Uint8ClampedArray(2 * 2 * 4)
    colorizeBrightness(base, new Int16Array([0, 0]), lut, out)
    const [r, g, b] = spectrogramColor(100 / 255)
    expect([out[0], out[1], out[2], out[3]]).toEqual([r, g, b, 255])
  })

  it('walks DOWN the green colormap (not toward black) for an attenuated row', () => {
    const out = new Uint8ClampedArray(2 * 2 * 4)
    // -38 ≈ a 12 dB cut applied to the top row only.
    colorizeBrightness(base, new Int16Array([-38, 0]), lut, out)

    const greenBefore = spectrogramColor(200 / 255)[1] // top row, col 1, base 200
    const greenAfter = out[1 * 4 + 1] // same pixel after the cut
    expect(greenAfter).toBeLessThan(greenBefore) // dimmer
    expect(greenAfter).toBeGreaterThan(0.75 * greenBefore) // but only ~15%, not blacked out

    // Untouched bottom row is unchanged.
    const [r] = spectrogramColor(50 / 255)
    expect(out[2 * 4]).toBe(r)
  })

  it('clamps a cut below the colormap floor to index 0 (no out-of-range read)', () => {
    const out = new Uint8ClampedArray(2 * 2 * 4)
    colorizeBrightness(base, new Int16Array([-400, 0]), lut, out)
    expect([out[0], out[1], out[2]]).toEqual([lut[0], lut[1], lut[2]])
  })
})
