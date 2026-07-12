import { BASE } from '@/services/baseUrl'

/**
 * Build a vue-router location for the Detections (Table) view with deep-link
 * filters. Emits the `date`/`hour`/`species` subset that the Table view reads
 * back (and round-trips along with page/sort) via seedStateFromQuery — keep
 * these key names in sync with that parser. `hour` 0 (midnight) is a valid
 * value and is preserved; `date` and `species` are omitted when absent.
 *
 * @param {Object} [filters]
 * @param {number} [filters.hour] - Hour of day, 0-23
 * @param {string} [filters.date] - Date as YYYY-MM-DD
 * @param {string} [filters.species] - Untranslated species common name
 * @returns {{ name: string, query: Object }} vue-router location
 */
export function tableDetectionsLink({ hour, date, species } = {}) {
  const query = {}
  if (hour !== undefined && hour !== null) query.hour = hour
  if (date) query.date = date
  if (species) query.species = species
  return { name: 'Table', query }
}

/**
 * Bare route segment for a single-recording permalink, with no leading slash
 * or base prefix — `bird/<name>/recording/<id>`. Single owner of that route
 * shape; composed by recordingPath (SPA links, BASE-prefixed) and the
 * Settings page's Site URL preview (appended to the user-entered origin,
 * which must not carry the SPA BASE).
 *
 * @param {string} commonName - Untranslated species common name
 * @param {number|string} id - Detection (recording) ID
 * @returns {string}
 */
export function recordingSegment(commonName, id) {
  return `bird/${encodeURIComponent(commonName)}/recording/${id}`
}

/**
 * Root-relative path to a single-recording permalink — the BirdRecording route
 * `/bird/:name/recording/:id`; the species is the English common name,
 * matching every in-app link to BirdDetails.
 *
 * @param {string} commonName - Untranslated species common name
 * @param {number|string} id - Detection (recording) ID
 * @returns {string}
 */
export function recordingPath(commonName, id) {
  return `${BASE}${recordingSegment(commonName, id)}`
}

/**
 * Absolute, shareable URL for a single-recording permalink — what the "share"
 * buttons put on the clipboard. An optional share token rides along as the
 * `?s=` query the backend's by-id gate reads, so the recipient stays
 * authorized even on a private station — built here so every share path
 * composes it identically.
 *
 * @param {string} commonName - Untranslated species common name
 * @param {number|string} id - Detection (recording) ID
 * @param {string} [shareToken] - Scoped share token authorizing this detection
 * @returns {string}
 */
export function recordingShareUrl(commonName, id, shareToken = '') {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const url = `${origin}${recordingPath(commonName, id)}`
  return shareToken ? `${url}?s=${encodeURIComponent(shareToken)}` : url
}
