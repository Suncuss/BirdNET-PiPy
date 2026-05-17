/**
 * Build a vue-router location for the Detections (Table) view with deep-link
 * filters. Single source of truth for the query-key contract that the Table
 * view reads back via seedFiltersFromQuery — keep these key names in sync
 * with that parser. `hour` 0 (midnight) is a valid value and is preserved;
 * `date` and `species` are omitted when absent.
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
