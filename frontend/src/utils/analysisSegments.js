// The model analyzes recordings in fixed 3-second windows (both BirdNET V2.4
// and V3.1 — model_service CHUNK_LENGTH_SECONDS); the saved clip is the
// detected window plus neighboring context chunks (backend
// select_audio_chunks). This is the derivation's assumption about historical
// rows, not a synced setting: a future model with a different window would
// need a per-row signal from the backend instead.
const ANALYSIS_CHUNK_SECONDS = 3

// Ignore sub-50ms slivers at region edges — mp3 encoder padding and float
// rounding, not real audio regions.
const EDGE_EPS = 0.05

// How far past the decoded duration a derived window may extend before we
// conclude the clip wasn't produced by the extractor layout we model
// (mp3 encoder padding / end-of-file trims run tens of ms, not seconds).
const FIT_SLACK = 0.6

/**
 * Locate the model's 3-second detection windows inside a saved clip and tile
 * the rest of the clip around them, so the player can show WHICH parts of the
 * audio the model actually flagged.
 *
 * Derivation (mirrors backend extract_detection_audio/select_audio_chunks):
 * `timestamp - groupTimestamp` is the detected chunk's offset into the source
 * recording, and the extractor always prepends exactly one context chunk —
 * `step = 3 - overlap` seconds — unless the detection was the recording's
 * first chunk. So within the clip this row's window starts at 0 (first chunk)
 * or at `step` (any other chunk). Independent of recording length: a 15s
 * recording still yields a 6-9s clip with the same layout.
 *
 * The detection being viewed is only ONE 3s window; the same species often
 * fired in neighboring chunks of the same source recording too (the display
 * dedup collapses those rows). Pass those siblings as `groupDetections` and
 * every window that falls inside this clip is labeled: this row's window as
 * role 'primary', the others as 'sibling'. Overlapping windows (overlap>0)
 * are cut at their edges, so covered spans merge instead of double-painting.
 *
 * Returns [] whenever the layout can't be derived (missing/unparseable
 * timestamps, or a derived window that doesn't fit the actual clip duration
 * — e.g. legacy audio extracted by other tools) so callers hide the bar
 * instead of mislabeling audio.
 *
 * @param {Object} params
 * @param {string} params.timestamp - Detection timestamp (ISO, local time)
 * @param {string} params.groupTimestamp - Source recording start (ISO, local time)
 * @param {number} [params.overlap] - Analysis overlap in seconds (detection row's value)
 * @param {number} params.duration - Actual decoded clip duration in seconds
 * @param {{ timestamp: string, confidence?: number }[]} [params.groupDetections] -
 *   Same-species detections from the same source recording (may include this
 *   row itself); windows outside the clip are ignored
 * @returns {{ start: number, end: number, role: 'primary'|'sibling'|'context',
 *   confidence?: number }[]} contiguous segments covering [0, duration];
 *   `confidence` rides on sibling segments for tooltips
 */
export function computeAnalysisSegments({ timestamp, groupTimestamp, overlap, duration, groupDetections }) {
  if (!timestamp || !groupTimestamp || !Number.isFinite(duration) || duration <= 0) return []

  const ts = Date.parse(timestamp)
  const groupTs = Date.parse(groupTimestamp)
  if (!Number.isFinite(ts) || !Number.isFinite(groupTs)) return []

  // Offset of the detected chunk within the source recording (not the clip).
  const recordingOffset = (ts - groupTs) / 1000
  if (recordingOffset < -EDGE_EPS) return []

  const step = ANALYSIS_CHUNK_SECONDS - (overlap > 0 ? overlap : 0)
  if (step <= EDGE_EPS) return []

  const detStart = recordingOffset < EDGE_EPS ? 0 : step
  // This row's window must actually fit the clip we decoded; if not, the clip
  // wasn't produced by the extractor layout we model.
  if (detStart + ANALYSIS_CHUNK_SECONDS > duration + FIT_SLACK) return []
  const detEnd = Math.min(detStart + ANALYSIS_CHUNK_SECONDS, duration)

  // Where the clip starts inside the source recording — the anchor that maps
  // sibling recording-offsets into clip coordinates.
  const clipStart = recordingOffset - detStart

  // This row's window, plus every sibling window that fits inside the clip.
  // The payload includes the viewed row itself — skip it by identity (both
  // timestamps are verbatim strings from the same DB rows).
  const windows = [{ start: detStart, end: detEnd, primary: true }]
  for (const sibling of groupDetections || []) {
    if (!sibling || sibling.timestamp === timestamp) continue
    const siblingTs = Date.parse(sibling.timestamp)
    if (!Number.isFinite(siblingTs)) continue
    const rel = (siblingTs - groupTs) / 1000 - clipStart
    if (rel < -EDGE_EPS || rel + ANALYSIS_CHUNK_SECONDS > duration + FIT_SLACK) continue
    windows.push({
      start: Math.max(0, rel),
      end: Math.min(rel + ANALYSIS_CHUNK_SECONDS, duration),
      primary: false,
      confidence: sibling.confidence
    })
  }

  // Cut the clip at every window edge (near-equal cuts collapse) and classify
  // each piece by the windows covering its midpoint.
  const cuts = [...windows.flatMap(w => [w.start, w.end]), duration].sort((a, b) => a - b)
  const segments = []
  let start = 0
  for (const cut of cuts) {
    if (cut - start <= EDGE_EPS) continue
    const mid = (start + cut) / 2
    const covering = windows.filter(w => w.start - EDGE_EPS <= mid && mid <= w.end + EDGE_EPS)
    const segment = {
      start,
      end: cut,
      role: covering.some(w => w.primary) ? 'primary' : covering.length ? 'sibling' : 'context'
    }
    if (segment.role === 'sibling') {
      const confs = covering.map(w => w.confidence).filter(Number.isFinite)
      if (confs.length) segment.confidence = Math.max(...confs)
    }
    segments.push(segment)
    start = cut
  }
  // Run the last piece out to the true duration, absorbing any sub-eps
  // trailing sliver (mp3 encoder padding) so the bar spans the full
  // spectrogram width. The walk always pushes at least one segment: the fit
  // check above guarantees duration > EDGE_EPS and cuts ends with duration.
  segments[segments.length - 1].end = duration
  return segments
}
