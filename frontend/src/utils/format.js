/**
 * Formatting helpers shared across components.
 */

/**
 * Format a byte count as a human-readable string (B, KB, MB, GB).
 * Returns "0 B" for falsy / zero input.
 */
export const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`
}
