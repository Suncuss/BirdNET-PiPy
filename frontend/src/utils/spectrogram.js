// Lightweight client-side STFT spectrogram for the Detection Detail page.
//
// Unlike the server-rendered spectrogram image (which has axis chrome and covers
// only the detected window), this is computed straight from the decoded audio,
// so its x-axis IS the audio timeline — the playhead and click-to-seek line up
// exactly. No external dependency: a small radix-2 FFT does the work.

// Shared spectrogram vocabulary so the live AnalyserNode feed (LiveFeed.vue) and
// this offline STFT read as one instrument instead of drifting apart: both cap the
// display at the same top frequency and show the same dynamic-range window.
export const SPECTROGRAM_MAX_HZ = 12000
export const SPECTROGRAM_FLOOR_DB = 80

// In-place iterative radix-2 FFT. re/im are Float32Array of length n (power of 2).
function fft(re, im) {
  const n = re.length
  // Bit-reversal permutation.
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1
    for (; j & bit; bit >>= 1) j ^= bit
    j ^= bit
    if (i < j) {
      const tr = re[i]; re[i] = re[j]; re[j] = tr
      const ti = im[i]; im[i] = im[j]; im[j] = ti
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len
    const wRe = Math.cos(ang)
    const wIm = Math.sin(ang)
    const half = len >> 1
    for (let i = 0; i < n; i += len) {
      let curRe = 1
      let curIm = 0
      for (let k = 0; k < half; k++) {
        const ik = i + k
        const jk = ik + half
        const bRe = re[jk] * curRe - im[jk] * curIm
        const bIm = re[jk] * curIm + im[jk] * curRe
        re[jk] = re[ik] - bRe
        im[jk] = im[ik] - bIm
        re[ik] += bRe
        im[ik] += bIm
        const nRe = curRe * wRe - curIm * wIm
        curIm = curRe * wIm + curIm * wRe
        curRe = nRe
      }
    }
  }
}

/**
 * Compute a magnitude spectrogram from a mono sample buffer.
 *
 * @param {Float32Array} samples - mono PCM in [-1, 1]
 * @param {number} sampleRate
 * @param {Object} [opts]
 * @param {number} [opts.fftSize=1024] - power of 2
 * @param {number} [opts.hop=fftSize/4] - hop size in samples
 * @param {number} [opts.maxFreqHz] - top of the displayed frequency range
 * @returns {{ mags: Float32Array, frames: number, bins: number, binHz: number,
 *             maxFreqHz: number, max: number }} mags is row-major [frame][bin]
 */
export function computeSpectrogram(samples, sampleRate, opts = {}) {
  const fftSize = opts.fftSize || 1024
  const hop = opts.hop || fftSize >> 2
  const maxFreqHz = opts.maxFreqHz || Math.min(sampleRate / 2, SPECTROGRAM_MAX_HZ)

  const binHz = sampleRate / fftSize
  const bins = Math.max(1, Math.min(fftSize >> 1, Math.ceil(maxFreqHz / binHz)))
  const frames = Math.max(1, Math.floor((samples.length - fftSize) / hop) + 1)

  // Hann window to cut spectral leakage.
  const win = new Float32Array(fftSize)
  for (let i = 0; i < fftSize; i++) {
    win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (fftSize - 1))
  }

  const mags = new Float32Array(frames * bins)
  const re = new Float32Array(fftSize)
  const im = new Float32Array(fftSize)
  let max = 1e-9

  for (let f = 0; f < frames; f++) {
    const start = f * hop
    for (let i = 0; i < fftSize; i++) {
      re[i] = (samples[start + i] || 0) * win[i]
      im[i] = 0
    }
    fft(re, im)
    const base = f * bins
    for (let b = 0; b < bins; b++) {
      const m = Math.sqrt(re[b] * re[b] + im[b] * im[b])
      mags[base + b] = m
      if (m > max) max = m
    }
  }

  return { mags, frames, bins, binHz, maxFreqHz: bins * binHz, max }
}

// Green colormap for an intensity in [0, 1]: dark → green → bright, tuned to the
// app's palette.
export function spectrogramColor(v) {
  const t = Math.max(0, Math.min(1, v))
  const r = Math.round(255 * Math.pow(t, 1.7) * 0.55)
  const g = Math.round(255 * Math.pow(t, 0.75))
  const b = Math.round(255 * Math.pow(t, 1.7) * 0.4)
  return [r, g, b]
}

// 256-entry RGBA colormap LUT: maps a 0–255 brightness byte to its colour in a
// single lookup, so re-colouring the spectrogram (e.g. as the high-pass slider
// moves) costs an array read per pixel instead of three pow() calls. Same idea as
// LiveFeed's SPECTROGRAM_RGB_LUT, packed as RGBA bytes ready for ImageData.
export function buildSpectrogramRgbaLut() {
  const lut = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i++) {
    const [r, g, b] = spectrogramColor(i / 255)
    lut[i * 4] = r
    lut[i * 4 + 1] = g
    lut[i * 4 + 2] = b
    lut[i * 4 + 3] = 255
  }
  return lut
}

/**
 * Reduce a computeSpectrogram() result to per-pixel brightness bytes (0–255), laid
 * out row-major with row 0 = top = highest frequency (the canvas orientation).
 * This is the expensive log-domain pass (per-clip peak normalization over a
 * `floorDb` window); it runs once, then colorizeBrightness turns these bytes —
 * optionally dimmed by a filter — into pixels cheaply. Pure (no DOM).
 *
 * @param {{mags: Float32Array, frames: number, bins: number, max: number}} spec
 * @param {Object} [opts]
 * @param {number} [opts.floorDb=80] - dynamic range shown below the per-clip peak
 * @returns {{ baseBytes: Uint8Array, width: number, height: number }}
 *   width = frames (time), height = bins (frequency)
 */
export function computeBaseBrightness(spec, { floorDb = SPECTROGRAM_FLOOR_DB } = {}) {
  const { mags, frames, bins, max } = spec
  const baseBytes = new Uint8Array(frames * bins)
  const logMax = Math.log10(max)
  for (let f = 0; f < frames; f++) {
    const colBase = f * bins
    for (let r = 0; r < bins; r++) {
      const bin = bins - 1 - r // row 0 = top = high frequency
      const db = 20 * (Math.log10(mags[colBase + bin] + 1e-12) - logMax) // ≤ 0, 0 at peak
      const v = Math.max(0, Math.min(1, 1 + db / floorDb))
      baseBytes[r * frames + f] = Math.round(v * 255)
    }
  }
  return { baseBytes, width: frames, height: bins }
}

/**
 * Convert a biquad magnitude response (linear |H(f)|, indexed by FFT bin, bin 0 =
 * DC) into per-display-row brightness offsets for colorizeBrightness: each row's
 * attenuation in dB (20·log10|H|), mapped into the shared dB window and scaled to
 * 0–255 brightness units. Negative (a cut darkens the row); ~0 in the passband.
 * This is what makes the high-pass read as "the signal is quieter here", at the
 * same gentle ~15%-per-12 dB rate as LiveFeed's post-filter analyser, instead of
 * opaque black. Row 0 = top = highest frequency, so bins are read back-to-front.
 *
 * @param {ArrayLike<number>} filterMag - linear magnitude per bin, length = bins
 * @param {Int16Array} out - length = bins, written in place and returned
 * @param {number} [floorDb=80]
 */
export function spectrogramFilterRowOffsets(filterMag, out, floorDb = SPECTROGRAM_FLOOR_DB) {
  const bins = out.length
  for (let r = 0; r < bins; r++) {
    const mag = filterMag[bins - 1 - r] // row 0 = top = high frequency
    const db = 20 * Math.log10(mag > 1e-6 ? mag : 1e-6) // ≤ 0; floor avoids -Infinity
    out[r] = Math.round((db / floorDb) * 255)
  }
  return out
}

/**
 * Colour the base brightness into an RGBA buffer, dimming each frequency row by
 * `rowOffsets[row]` (≤ 0, in the same 0–255 brightness units). A high-pass filter
 * supplies negative offsets for the rows it attenuates, so the spectrogram walks
 * DOWN the green colormap exactly as far as the filter lowers the signal — the
 * truthful "it's quieter here" look the live AnalyserNode gets for free — rather
 * than having opaque black laid over it. All-zero offsets reproduce the raw clip.
 *
 * @param {{baseBytes: Uint8Array, width: number, height: number}} base
 * @param {ArrayLike<number>} rowOffsets - length = height, values ≤ 0
 * @param {Uint8ClampedArray} lut - from buildSpectrogramRgbaLut()
 * @param {Uint8ClampedArray} out - length = width*height*4, written in place
 */
export function colorizeBrightness(base, rowOffsets, lut, out) {
  const { baseBytes, width, height } = base
  for (let r = 0; r < height; r++) {
    const off = rowOffsets[r] // ≤ 0 for an attenuated row
    const rowStart = r * width
    for (let f = 0; f < width; f++) {
      let idx = baseBytes[rowStart + f] + off
      if (idx < 0) idx = 0
      else if (idx > 255) idx = 255
      const o = (rowStart + f) * 4
      const l = idx * 4
      out[o] = lut[l]
      out[o + 1] = lut[l + 1]
      out[o + 2] = lut[l + 2]
      out[o + 3] = 255
    }
  }
  return out
}
