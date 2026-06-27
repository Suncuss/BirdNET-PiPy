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
 * Root-relative path to a single-recording permalink — the BirdRecording route
 * `/bird/:name/recording/:id`. Single owner of that route shape; the species is
 * the English common name, matching every in-app link to BirdDetails.
 *
 * @param {string} commonName - Untranslated species common name
 * @param {number|string} id - Detection (recording) ID
 * @returns {string}
 */
export function recordingPath(commonName, id) {
  return `${BASE}bird/${encodeURIComponent(commonName)}/recording/${id}`
}

/**
 * Absolute, shareable URL for a single-recording permalink — what the "share"
 * buttons put on the clipboard.
 *
 * @param {string} commonName - Untranslated species common name
 * @param {number|string} id - Detection (recording) ID
 * @returns {string}
 */
export function recordingShareUrl(commonName, id) {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}${recordingPath(commonName, id)}`
}
