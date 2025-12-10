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
   * Change view and adjust anchor date appropriately.
   * @param {string} newView - New view type
   */
  const changeView = (newView) => {
    if (isUpdating.value || selectedView.value === newView) return

    const anchor = anchorDate.value

    switch (newView) {
      case 'day':
        // Keep the same date
        break
      case 'week':
        // Adjust to start of week (Sunday)
        anchorDate.value = new Date(anchor)
        anchorDate.value.setDate(anchor.getDate() - anchor.getDay())
        break
      case 'month':
        // Adjust to first of month
        anchorDate.value = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
        break
      case '6month': {
        // Adjust to start of 6-month period
        const halfYear = Math.floor(anchor.getMonth() / 6) * 6
        anchorDate.value = new Date(anchor.getFullYear(), halfYear, 1)
        break
      }
      case 'year':
        // Adjust to January 1st
        anchorDate.value = new Date(anchor.getFullYear(), 0, 1)
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
