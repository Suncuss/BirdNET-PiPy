/**
 * Centralized color palette for bird activity charts.
 * Provides consistent nature-themed colors across all chart components.
 */
export function useChartColors() {
  const colorPalette = {
    primary: '#2D6A4F',      // Forest Green
    secondary: '#74C69D',    // Mint Green
    accent1: '#D9ED92',      // Light Yellow-Green
    accent2: '#B7E4C7',      // Pale Green
    text: '#1B4332',         // Dark Green
    background: '#F1FAEE',   // Off-White
    grid: 'rgba(45, 106, 79, 0.2)'  // Semi-transparent Forest Green
  }

  // RGB values for secondary color (used in heatmap alpha calculations)
  const secondaryRGB = [116, 198, 157]

  return { colorPalette, secondaryRGB }
}
