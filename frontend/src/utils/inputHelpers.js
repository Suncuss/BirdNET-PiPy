/**
 * Limit numeric input to specified decimal places (truncates as user types)
 * @param {Event} e - Input event
 * @param {number} decimals - Maximum decimal places (default: 2)
 */
export function limitDecimals(e, decimals = 2) {
  const value = e.target.value
  const pattern = new RegExp(`^-?\\d*\\.?\\d{0,${decimals}}`)
  const match = value.match(pattern)
  if (match && match[0] !== value) {
    e.target.value = match[0]
  }
}

/**
 * Sanitize a label string to only allow alphanumeric, spaces, hyphens, underscores.
 * @param {string} value - The raw label string
 * @param {number} maxLength - Maximum length (default: 30)
 * @returns {string} Sanitized label
 */
export function sanitizeLabel(value, maxLength = 30) {
  return value.replace(/[^A-Za-z0-9 _-]/g, '').slice(0, maxLength)
}

/**
 * Normalize an hour-of-day input to an integer 0-23, or null.
 * Empty string / null / undefined / non-integer / out-of-range all map to null.
 * 0 is preserved (it is a valid hour, not "empty").
 * @param {*} value - Raw input (number, route-query string, etc.)
 * @returns {number|null}
 */
export function normalizeHour(value) {
  if (value === null || value === undefined || value === '') return null
  const h = Number(value)
  return Number.isInteger(h) && h >= 0 && h <= 23 ? h : null
}
