import { describe, it, expect } from 'vitest'
import { computeAnalysisSegments } from '@/utils/analysisSegments'

// Default pipeline: 9s recordings, 3s analysis chunks, no overlap. The saved
// clip is 6s (edge detection) or 9s (middle detection, one context chunk each
// side) — see backend select_audio_chunks.
const at = (seconds) => {
  const d = new Date(2026, 6, 2, 6, 15, 0)
  d.setMilliseconds(seconds * 1000)
  // Local ISO without timezone, matching the backend's isoformat() strings
  const pad = (n, w = 2) => String(n).padStart(w, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    (d.getMilliseconds() ? `.${pad(d.getMilliseconds(), 3)}` : '')
}
const REC_START = at(0)

describe('computeAnalysisSegments', () => {
  it('marks the first 3s when the detection was the recording opening chunk (6s clip)', () => {
    const segs = computeAnalysisSegments({
      timestamp: REC_START, groupTimestamp: REC_START, overlap: 0, duration: 6
    })
    expect(segs).toEqual([
      { start: 0, end: 3, role: 'primary' },
      { start: 3, end: 6, role: 'context' }
    ])
  })

  it('marks the middle 3s of a 9s clip for a mid-recording detection', () => {
    const segs = computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9
    })
    expect(segs).toEqual([
      { start: 0, end: 3, role: 'context' },
      { start: 3, end: 6, role: 'primary' },
      { start: 6, end: 9, role: 'context' }
    ])
  })

  it('marks the trailing 3s of a 6s clip for a recording-final detection', () => {
    const segs = computeAnalysisSegments({
      timestamp: at(6), groupTimestamp: REC_START, overlap: 0, duration: 6
    })
    expect(segs).toEqual([
      { start: 0, end: 3, role: 'context' },
      { start: 3, end: 6, role: 'primary' }
    ])
  })

  it('is independent of recording length (15s recording still yields the same clip layout)', () => {
    // Detection in chunk 3 of a 15s recording: clip = chunks 2-4, window centered
    const segs = computeAnalysisSegments({
      timestamp: at(9), groupTimestamp: REC_START, overlap: 0, duration: 9
    })
    expect(segs.find(s => s.role === 'primary')).toEqual({ start: 3, end: 6, role: 'primary' })
  })

  it('uses step = 3 − overlap for the context chunk before the window', () => {
    // overlap 1 → step 2: middle clip is 2+3+2 = 7s, window at 2–5
    const segs = computeAnalysisSegments({
      timestamp: at(2), groupTimestamp: REC_START, overlap: 1, duration: 7
    })
    expect(segs).toEqual([
      { start: 0, end: 2, role: 'context' },
      { start: 2, end: 5, role: 'primary' },
      { start: 5, end: 7, role: 'context' }
    ])
  })

  it('tolerates mp3 encoder padding without emitting a sliver segment', () => {
    const segs = computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9.04
    })
    expect(segs).toHaveLength(3)
    expect(segs[2].end).toBeCloseTo(9.04)
  })

  it('clamps the window to a clip that decodes slightly short', () => {
    const segs = computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 5.7
    })
    expect(segs).toEqual([
      { start: 0, end: 3, role: 'context' },
      { start: 3, end: 5.7, role: 'primary' }
    ])
  })

  it('returns [] when the derived window cannot fit the actual clip', () => {
    // Claims a non-first chunk (window 3–6) but the audio is only 3.2s long:
    // this clip was not produced by the extractor layout we model.
    expect(computeAnalysisSegments({
      timestamp: at(6), groupTimestamp: REC_START, overlap: 0, duration: 3.2
    })).toEqual([])
  })

  it('returns [] on missing or unparseable inputs', () => {
    expect(computeAnalysisSegments({
      timestamp: '', groupTimestamp: REC_START, overlap: 0, duration: 6
    })).toEqual([])
    expect(computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: null, overlap: 0, duration: 9
    })).toEqual([])
    expect(computeAnalysisSegments({
      timestamp: 'not-a-date', groupTimestamp: REC_START, overlap: 0, duration: 9
    })).toEqual([])
    expect(computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 0
    })).toEqual([])
  })

  it('returns [] when the timestamp precedes the recording start (corrupt data)', () => {
    expect(computeAnalysisSegments({
      timestamp: REC_START, groupTimestamp: at(3), overlap: 0, duration: 9
    })).toEqual([])
  })

  it('treats a null overlap as 0 (legacy rows)', () => {
    const segs = computeAnalysisSegments({
      timestamp: at(3), groupTimestamp: REC_START, overlap: null, duration: 9
    })
    expect(segs.find(s => s.role === 'primary')).toEqual({ start: 3, end: 6, role: 'primary' })
  })

  it('handles fractional steps at high overlap (sub-chunk context tiles)', () => {
    // overlap 2.5 → step 0.5: middle clip is 0.5+3+0.5 = 4s, window at 0.5–3.5
    const segs = computeAnalysisSegments({
      timestamp: at(0.5), groupTimestamp: REC_START, overlap: 2.5, duration: 4
    })
    expect(segs).toEqual([
      { start: 0, end: 0.5, role: 'context' },
      { start: 0.5, end: 3.5, role: 'primary' },
      { start: 3.5, end: 4, role: 'context' }
    ])
  })

  describe('group siblings (same species, same source recording)', () => {
    it('labels a sibling window alongside the primary (chunks 0+1, viewing chunk 0)', () => {
      const segs = computeAnalysisSegments({
        timestamp: REC_START, groupTimestamp: REC_START, overlap: 0, duration: 6,
        groupDetections: [
          { timestamp: REC_START, confidence: 0.93 }, // this row — must not duplicate
          { timestamp: at(3), confidence: 0.72 }
        ]
      })
      expect(segs).toEqual([
        { start: 0, end: 3, role: 'primary' },
        { start: 3, end: 6, role: 'sibling', confidence: 0.72 }
      ])
    })

    it('labels siblings on both sides of a middle-chunk clip', () => {
      const segs = computeAnalysisSegments({
        timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9,
        groupDetections: [
          { timestamp: REC_START, confidence: 0.9 },
          { timestamp: at(3), confidence: 0.95 },
          { timestamp: at(6), confidence: 0.8 }
        ]
      })
      expect(segs).toEqual([
        { start: 0, end: 3, role: 'sibling', confidence: 0.9 },
        { start: 3, end: 6, role: 'primary' },
        { start: 6, end: 9, role: 'sibling', confidence: 0.8 }
      ])
    })

    it('ignores sibling windows that fall outside the clip', () => {
      // Viewing chunk 0 (clip = chunks 0-1); the chunk-2 sibling is not in this clip
      const segs = computeAnalysisSegments({
        timestamp: REC_START, groupTimestamp: REC_START, overlap: 0, duration: 6,
        groupDetections: [{ timestamp: at(6), confidence: 0.8 }]
      })
      expect(segs).toEqual([
        { start: 0, end: 3, role: 'primary' },
        { start: 3, end: 6, role: 'context' }
      ])
    })

    it('is unchanged when groupDetections only contains the row itself', () => {
      const withSelf = computeAnalysisSegments({
        timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9,
        groupDetections: [{ timestamp: at(3), confidence: 0.95 }]
      })
      const without = computeAnalysisSegments({
        timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9
      })
      expect(withSelf).toEqual(without)
    })

    it('skips malformed sibling entries', () => {
      const segs = computeAnalysisSegments({
        timestamp: at(3), groupTimestamp: REC_START, overlap: 0, duration: 9,
        groupDetections: [null, { timestamp: 'garbage' }, {}]
      })
      expect(segs.filter(s => s.role !== 'context')).toHaveLength(1)
    })

    it('splits overlapping windows at their edges instead of double-painting', () => {
      // overlap 1 → step 2: clip = 7s with primary window 2–5; the next-chunk
      // sibling covers 4–7, so 4–5 is covered by both (stays primary) and 5–7
      // is sibling-only.
      const segs = computeAnalysisSegments({
        timestamp: at(2), groupTimestamp: REC_START, overlap: 1, duration: 7,
        groupDetections: [{ timestamp: at(4), confidence: 0.66 }]
      })
      expect(segs).toEqual([
        { start: 0, end: 2, role: 'context' },
        { start: 2, end: 4, role: 'primary' },
        { start: 4, end: 5, role: 'primary' },
        { start: 5, end: 7, role: 'sibling', confidence: 0.66 }
      ])
    })
  })
})
