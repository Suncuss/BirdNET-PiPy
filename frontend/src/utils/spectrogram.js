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

/**
 * Paint a computeSpectrogram() result to RGBA pixels (row 0 = top = highest
 * frequency). Pure (no DOM): the heavy per-pixel pass runs once and stays
 * unit-testable; the view caches the result and only rescales / overlays it.
 *
 * @param {{mags: Float32Array, frames: number, bins: number, max: number}} spec
 * @param {Object} [opts]
 * @param {number} [opts.floorDb=80] - dynamic range shown below the per-clip peak
 * @returns {{ data: Uint8ClampedArray, width: number, height: number }}
 */
export function renderSpectrogramPixels(spec, { floorDb = SPECTROGRAM_FLOOR_DB } = {}) {
  const { mags, frames, bins, max } = spec
  const data = new Uint8ClampedArray(frames * bins * 4)
  const logMax = Math.log10(max)
  for (let f = 0; f < frames; f++) {
    const base = f * bins
    for (let r = 0; r < bins; r++) {
      const bin = bins - 1 - r // row 0 = top = high frequency
      const db = 20 * (Math.log10(mags[base + bin] + 1e-12) - logMax) // ≤ 0, 0 at peak
      const v = Math.max(0, 1 + db / floorDb)
      const [cr, cg, cb] = spectrogramColor(v)
      const idx = (r * frames + f) * 4
      data[idx] = cr
      data[idx + 1] = cg
      data[idx + 2] = cb
      data[idx + 3] = 255
    }
  }
  return { data, width: frames, height: bins }
}
