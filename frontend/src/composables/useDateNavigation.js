import { ref, computed } from 'vue'
import { useChartHelpers } from './useChartHelpers'

/**
 * Composable for period-based date navigation.
 * Provides view selection (day/week/month/6month/year), anchor date management,
 * and navigation controls with computed date displays.
 *
 * @param {Object} options - Configuration options
 * @param {string} options.initialView - Initial view type (default: 'month')
 * @param {Date} options.initialDate - Initial anchor date (default: today)
 * @returns {Object} Date navigation state and methods
 */
export function useDateNavigation(options = {}) {
  const { initialView = 'month', initialDate = new Date() } = options
  const { getLocalDateString } = useChartHelpers()

  const selectedView = ref(initialView)
  const anchorDate = ref(new Date(initialDate))
  const isUpdating = ref(false)

  /**
   * Human-readable date display based on current view.
   */
  const dateDisplay = computed(() => {
    const date = anchorDate.value
    switch (selectedView.value) {
      case 'day':
        return date.toLocaleDateString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric'
        })
      case 'week': {
        const weekStart = new Date(date)
        weekStart.setDate(date.getDate() - date.getDay())
        const weekEnd = new Date(weekStart)
        weekEnd.setDate(weekStart.getDate() + 6)
        return `${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
      }
      case 'month':
        return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
      case '6month': {
        const start = date.getMonth() < 6 ? 0 : 6
        const end = start + 5
        return `${new Date(date.getFullYear(), start).toLocaleDateString('en-US', { month: 'short' })} - ${new Date(date.getFullYear(), end).toLocaleDateString('en-US', { month: 'short' })}`
      }
      case 'year':
        return date.getFullYear().toString()
      default:
        return ''
    }
  })

  /**
   * Check if forward navigation is allowed (can't go past today).
   */
  const canGoForward = computed(() => {
    const now = new Date()
    const anchor = anchorDate.value

    switch (selectedView.value) {
      case 'day':
        return anchor.toDateString() !== now.toDateString()
      case 'week': {
        const thisWeekStart = new Date(now)
        thisWeekStart.setDate(now.getDate() - now.getDay())
        const anchorWeekStart = new Date(anchor)
        anchorWeekStart.setDate(anchor.getDate() - anchor.getDay())
        return anchorWeekStart < thisWeekStart
      }
      case 'month':
        return anchor.getFullYear() !== now.getFullYear() ||
               anchor.getMonth() !== now.getMonth()
      case '6month': {
        const currentHalf = Math.floor(now.getMonth() / 6)
        const anchorHalf = Math.floor(anchor.getMonth() / 6)
        return anchor.getFullYear() !== now.getFullYear() ||
               anchorHalf !== currentHalf
      }
      case 'year':
        return anchor.getFullYear() !== now.getFullYear()
      default:
        return false
    }
  })

  /**
   * Navigate to previous period.
   */
  const navigatePrevious = () => {
    if (isUpdating.value) return

    const anchor = new Date(anchorDate.value)
    switch (selectedView.value) {
      case 'day':
        anchor.setDate(anchor.getDate() - 1)
        break
      case 'week':
        anchor.setDate(anchor.getDate() - 7)
        break
      case 'month':
        anchor.setMonth(anchor.getMonth() - 1)
        break
      case '6month':
        anchor.setMonth(anchor.getMonth() - 6)
        break
      case 'year':
        anchor.setFullYear(anchor.getFullYear() - 1)
        break
    }
    anchorDate.value = anchor
  }

  /**
   * Navigate to next period (if not past today).
   */
  const navigateNext = () => {
    if (!canGoForward.value || isUpdating.value) return

    const anchor = new Date(anchorDate.value)
    switch (selectedView.value) {
      case 'day':
        anchor.setDate(anchor.getDate() + 1)
        break
      case 'week':
        anchor.setDate(anchor.getDate() + 7)
        break
      case 'month':
        anchor.setMonth(anchor.getMonth() + 1)
        break
      case '6month':
        anchor.setMonth(anchor.getMonth() + 6)
        break
      case 'year':
        anchor.setFullYear(anchor.getFullYear() + 1)
        break
    }
    anchorDate.value = anchor
  }

  /**
   * Get the best date within a period for zooming in.
   * If today falls within the period, use today. Otherwise use the last day of the period.
   * @param {Date} periodStart - Start of the period
   * @param {Date} periodEnd - End of the period
   * @returns {Date} Best date to use
   */
  const getBestDateInPeriod = (periodStart, periodEnd) => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    const start = new Date(periodStart)
    start.setHours(0, 0, 0, 0)

    const end = new Date(periodEnd)
    end.setHours(0, 0, 0, 0)

    if (today >= start && today <= end) {
      return new Date(today)
    }
    // If viewing past data, use the end of the period (most recent)
    // If viewing future data (shouldn't happen but handle it), use start
    return today > end ? new Date(end) : new Date(start)
  }

  /**
   * Change view and adjust anchor date appropriately.
   * When zooming in (larger to smaller view), tries to include today if possible,
   * otherwise uses the most recent date within the current view's range.
   * @param {string} newView - New view type
   */
  const changeView = (newView) => {
    if (isUpdating.value || selectedView.value === newView) return

    const anchor = new Date(anchorDate.value)
    const oldView = selectedView.value
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    // Determine the current view's date range for smart date selection
    let periodStart, periodEnd

    switch (oldView) {
      case 'year':
        periodStart = new Date(anchor.getFullYear(), 0, 1)
        periodEnd = new Date(anchor.getFullYear(), 11, 31)
        break
      case '6month': {
        const halfStart = anchor.getMonth() < 6 ? 0 : 6
        periodStart = new Date(anchor.getFullYear(), halfStart, 1)
        periodEnd = new Date(anchor.getFullYear(), halfStart + 5 + 1, 0) // Last day of 6th month
        break
      }
      case 'month':
        periodStart = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
        periodEnd = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0) // Last day of month
        break
      case 'week': {
        periodStart = new Date(anchor)
        periodStart.setDate(anchor.getDate() - anchor.getDay())
        periodEnd = new Date(periodStart)
        periodEnd.setDate(periodStart.getDate() + 6)
        break
      }
      case 'day':
      default:
        periodStart = new Date(anchor)
        periodEnd = new Date(anchor)
        break
    }

    // Get the best date to use based on the current period
    const bestDate = getBestDateInPeriod(periodStart, periodEnd)

    // Now set the anchor date based on the new view
    switch (newView) {
      case 'day':
        anchorDate.value = bestDate
        break
      case 'week': {
        // Adjust to start of week (Sunday) containing the best date
        const weekAnchor = new Date(bestDate)
        weekAnchor.setDate(bestDate.getDate() - bestDate.getDay())
        anchorDate.value = weekAnchor
        break
      }
      case 'month':
        anchorDate.value = new Date(bestDate.getFullYear(), bestDate.getMonth(), 1)
        break
      case '6month': {
        const halfYear = Math.floor(bestDate.getMonth() / 6) * 6
        anchorDate.value = new Date(bestDate.getFullYear(), halfYear, 1)
        break
      }
      case 'year':
        anchorDate.value = new Date(bestDate.getFullYear(), 0, 1)
        break
    }

    selectedView.value = newView
  }

  /**
   * Set anchor date directly.
   * @param {Date|string} date - New anchor date
   */
  const setAnchorDate = (date) => {
    if (typeof date === 'string') {
      anchorDate.value = new Date(date + 'T00:00:00')
    } else {
      anchorDate.value = new Date(date)
    }
  }

  /**
   * Get anchor date as YYYY-MM-DD string.
   */
  const anchorDateString = computed(() => {
    return getLocalDateString(anchorDate.value)
  })

  return {
    selectedView,
    anchorDate,
    anchorDateString,
    isUpdating,
    dateDisplay,
    canGoForward,
    navigatePrevious,
    navigateNext,
    changeView,
    setAnchorDate,
    getLocalDateString
  }
}
