/**
 * Tests for tableDetectionsLink — the single source of truth for the
 * Table-view deep-link query contract (written by Dashboard heatmap-cell
 * clicks and the TimeAxisLinks hour labels, read by Table.seedFiltersFromQuery).
 */
import { describe, it, expect } from 'vitest'
import { tableDetectionsLink, recordingShareUrl } from '@/utils/detectionLinks'

describe('tableDetectionsLink', () => {
  it('targets the Table route', () => {
    expect(tableDetectionsLink({ hour: 5 }).name).toBe('Table')
  })

  it('preserves hour 0 (midnight is valid, not "absent")', () => {
    expect(tableDetectionsLink({ hour: 0 }).query).toEqual({ hour: 0 })
  })

  it('omits date and species when absent (hour-only, like TimeAxisLinks)', () => {
    expect(tableDetectionsLink({ hour: 14 }).query).toEqual({ hour: 14 })
  })

  it('includes date and species when provided (heatmap cell drill-down)', () => {
    expect(
      tableDetectionsLink({ hour: 14, date: '2024-01-15', species: 'American Robin' }).query
    ).toEqual({ hour: 14, date: '2024-01-15', species: 'American Robin' })
  })

  it('omits hour when not provided (defensive; real callers always pass it)', () => {
    expect(tableDetectionsLink({ date: '2024-01-15' }).query).toEqual({ date: '2024-01-15' })
    expect(tableDetectionsLink().query).toEqual({})
  })
})

describe('recordingShareUrl', () => {
  it('builds an absolute, BASE-prefixed permalink for clipboard sharing', () => {
    // happy-dom has no <base href>, so BASE resolves to '/'.
    expect(recordingShareUrl('American Robin', 42)).toBe(
      `${window.location.origin}/bird/American%20Robin/recording/42`
    )
  })

  it('URL-encodes species names with special characters', () => {
    expect(recordingShareUrl("Wilson's Warbler", 7)).toBe(
      `${window.location.origin}/bird/Wilson's%20Warbler/recording/7`
    )
  })
})
