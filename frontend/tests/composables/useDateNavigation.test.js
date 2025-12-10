/**
 * Tests for useDateNavigation composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useDateNavigation } from '@/composables/useDateNavigation'

describe('useDateNavigation', () => {
  // Fixed date for consistent testing: June 15, 2024 (Saturday)
  const fixedDate = new Date(2024, 5, 15, 12, 0, 0)

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(fixedDate)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('initialization', () => {
    it('returns expected properties and methods', () => {
      const nav = useDateNavigation()

      expect(nav).toHaveProperty('selectedView')
      expect(nav).toHaveProperty('anchorDate')
      expect(nav).toHaveProperty('anchorDateString')
      expect(nav).toHaveProperty('isUpdating')
      expect(nav).toHaveProperty('dateDisplay')
      expect(nav).toHaveProperty('canGoForward')
      expect(nav).toHaveProperty('navigatePrevious')
      expect(nav).toHaveProperty('navigateNext')
      expect(nav).toHaveProperty('changeView')
      expect(nav).toHaveProperty('setAnchorDate')
      expect(nav).toHaveProperty('getLocalDateString')
    })

    it('defaults to month view', () => {
      const nav = useDateNavigation()
      expect(nav.selectedView.value).toBe('month')
    })

    it('defaults anchor date to today', () => {
      const nav = useDateNavigation()
      expect(nav.anchorDate.value.toDateString()).toBe(fixedDate.toDateString())
    })

    it('accepts initialView option', () => {
      const nav = useDateNavigation({ initialView: 'week' })
      expect(nav.selectedView.value).toBe('week')
    })

    it('accepts initialDate option', () => {
      const customDate = new Date(2023, 0, 1)
      const nav = useDateNavigation({ initialDate: customDate })
      expect(nav.anchorDate.value.toDateString()).toBe(customDate.toDateString())
    })
  })

  describe('dateDisplay', () => {
    it('formats day view correctly', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      expect(nav.dateDisplay.value).toBe('Jun 15, 2024')
    })

    it('formats week view correctly', () => {
      const nav = useDateNavigation({ initialView: 'week' })
      // June 15 is Saturday, week starts Sunday June 9
      expect(nav.dateDisplay.value).toBe('Jun 9 - Jun 15')
    })

    it('formats month view correctly', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      expect(nav.dateDisplay.value).toBe('June 2024')
    })

    it('formats 6month view correctly for first half', () => {
      const nav = useDateNavigation({
        initialView: '6month',
        initialDate: new Date(2024, 2, 15) // March
      })
      expect(nav.dateDisplay.value).toBe('Jan - Jun')
    })

    it('formats 6month view correctly for second half', () => {
      const nav = useDateNavigation({
        initialView: '6month',
        initialDate: new Date(2024, 8, 15) // September
      })
      expect(nav.dateDisplay.value).toBe('Jul - Dec')
    })

    it('formats year view correctly', () => {
      const nav = useDateNavigation({ initialView: 'year' })
      expect(nav.dateDisplay.value).toBe('2024')
    })
  })

  describe('canGoForward', () => {
    it('returns false for day view when on today', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      expect(nav.canGoForward.value).toBe(false)
    })

    it('returns true for day view when in past', () => {
      const pastDate = new Date(2024, 5, 10)
      const nav = useDateNavigation({ initialView: 'day', initialDate: pastDate })
      expect(nav.canGoForward.value).toBe(true)
    })

    it('returns false for month view when in current month', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      expect(nav.canGoForward.value).toBe(false)
    })

    it('returns true for month view when in past month', () => {
      const pastDate = new Date(2024, 4, 15) // May
      const nav = useDateNavigation({ initialView: 'month', initialDate: pastDate })
      expect(nav.canGoForward.value).toBe(true)
    })

    it('returns false for year view when in current year', () => {
      const nav = useDateNavigation({ initialView: 'year' })
      expect(nav.canGoForward.value).toBe(false)
    })

    it('returns true for year view when in past year', () => {
      const pastDate = new Date(2023, 5, 15)
      const nav = useDateNavigation({ initialView: 'year', initialDate: pastDate })
      expect(nav.canGoForward.value).toBe(true)
    })
  })

  describe('navigatePrevious', () => {
    it('moves back one day in day view', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.navigatePrevious()
      expect(nav.anchorDate.value.getDate()).toBe(14)
    })

    it('moves back one week in week view', () => {
      const nav = useDateNavigation({ initialView: 'week' })
      const originalDate = nav.anchorDate.value.getDate()
      nav.navigatePrevious()
      expect(nav.anchorDate.value.getDate()).toBe(originalDate - 7)
    })

    it('moves back one month in month view', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      nav.navigatePrevious()
      expect(nav.anchorDate.value.getMonth()).toBe(4) // May
    })

    it('moves back 6 months in 6month view', () => {
      const nav = useDateNavigation({ initialView: '6month' })
      nav.navigatePrevious()
      // Starting from June, going back 6 months lands in December (month 11) of prev year
      expect(nav.anchorDate.value.getMonth()).toBe(11)
      expect(nav.anchorDate.value.getFullYear()).toBe(2023)
    })

    it('moves back one year in year view', () => {
      const nav = useDateNavigation({ initialView: 'year' })
      nav.navigatePrevious()
      expect(nav.anchorDate.value.getFullYear()).toBe(2023)
    })

    it('does not navigate when isUpdating is true', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.isUpdating.value = true
      nav.navigatePrevious()
      expect(nav.anchorDate.value.getDate()).toBe(15)
    })
  })

  describe('navigateNext', () => {
    it('does not navigate past today in day view', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.navigateNext()
      expect(nav.anchorDate.value.getDate()).toBe(15) // Still today
    })

    it('moves forward when in past', () => {
      const pastDate = new Date(2024, 5, 10)
      const nav = useDateNavigation({ initialView: 'day', initialDate: pastDate })
      nav.navigateNext()
      expect(nav.anchorDate.value.getDate()).toBe(11)
    })

    it('does not navigate when isUpdating is true', () => {
      const pastDate = new Date(2024, 5, 10)
      const nav = useDateNavigation({ initialView: 'day', initialDate: pastDate })
      nav.isUpdating.value = true
      nav.navigateNext()
      expect(nav.anchorDate.value.getDate()).toBe(10)
    })
  })

  describe('changeView', () => {
    it('changes selectedView', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      nav.changeView('week')
      expect(nav.selectedView.value).toBe('week')
    })

    it('does not change when same view', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      const originalAnchor = new Date(nav.anchorDate.value)
      nav.changeView('month')
      expect(nav.anchorDate.value.getTime()).toBe(originalAnchor.getTime())
    })

    it('adjusts anchor to start of week when switching to week view', () => {
      // June 15 is Saturday (day 6)
      const nav = useDateNavigation({ initialView: 'day' })
      nav.changeView('week')
      expect(nav.anchorDate.value.getDay()).toBe(0) // Sunday
      expect(nav.anchorDate.value.getDate()).toBe(9) // June 9
    })

    it('adjusts anchor to first of month when switching to month view', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.changeView('month')
      expect(nav.anchorDate.value.getDate()).toBe(1)
    })

    it('adjusts anchor to start of 6-month period when switching to 6month view', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.changeView('6month')
      expect(nav.anchorDate.value.getMonth()).toBe(0) // January (first half)
    })

    it('adjusts anchor to January 1st when switching to year view', () => {
      const nav = useDateNavigation({ initialView: 'day' })
      nav.changeView('year')
      expect(nav.anchorDate.value.getMonth()).toBe(0)
      expect(nav.anchorDate.value.getDate()).toBe(1)
    })

    it('does not change when isUpdating is true', () => {
      const nav = useDateNavigation({ initialView: 'month' })
      nav.isUpdating.value = true
      nav.changeView('week')
      expect(nav.selectedView.value).toBe('month')
    })
  })

  describe('setAnchorDate', () => {
    it('accepts Date object', () => {
      const nav = useDateNavigation()
      const newDate = new Date(2023, 11, 25)
      nav.setAnchorDate(newDate)
      expect(nav.anchorDate.value.toDateString()).toBe(newDate.toDateString())
    })

    it('accepts string date', () => {
      const nav = useDateNavigation()
      nav.setAnchorDate('2023-12-25')
      expect(nav.anchorDate.value.getFullYear()).toBe(2023)
      expect(nav.anchorDate.value.getMonth()).toBe(11)
      expect(nav.anchorDate.value.getDate()).toBe(25)
    })
  })

  describe('anchorDateString', () => {
    it('returns date in YYYY-MM-DD format', () => {
      const nav = useDateNavigation()
      expect(nav.anchorDateString.value).toBe('2024-06-15')
    })

    it('updates when anchor date changes', () => {
      const nav = useDateNavigation()
      nav.setAnchorDate(new Date(2024, 0, 5))
      expect(nav.anchorDateString.value).toBe('2024-01-05')
    })
  })

  describe('getLocalDateString', () => {
    it('is exposed from composable', () => {
      const nav = useDateNavigation()
      expect(typeof nav.getLocalDateString).toBe('function')
    })

    it('formats dates correctly', () => {
      const nav = useDateNavigation()
      const result = nav.getLocalDateString(new Date(2024, 5, 15))
      expect(result).toBe('2024-06-15')
    })
  })
})
