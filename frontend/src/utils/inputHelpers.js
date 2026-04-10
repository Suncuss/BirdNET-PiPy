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
