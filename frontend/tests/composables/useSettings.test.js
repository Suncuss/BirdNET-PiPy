/**
 * Tests for useSettings composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi,
  api: mockApi
}))

vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  })
}))

const mockSetUseMetricUnits = vi.hoisted(() => vi.fn())
const mockSetTimeFormat = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useUnitSettings', () => ({
  useUnitSettings: () => ({ setUseMetricUnits: mockSetUseMetricUnits })
}))

vi.mock('@/composables/useTimeFormat', () => ({
  useTimeFormat: () => ({ setTimeFormat: mockSetTimeFormat })
}))

import { useSettings } from '@/composables/useSettings'

const SETTINGS = {
  display: { use_metric_units: false, time_format: '24h', station_name: 'Backyard' },
  location: { configured: true, lat: 1, lon: 2 }
}

describe('useSettings', () => {
  beforeEach(() => {
    mockApi.get.mockReset()
    mockApi.put.mockReset()
    mockApi.post.mockReset()
    mockSetUseMetricUnits.mockReset()
    mockSetTimeFormat.mockReset()
    useSettings().resetState()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('exposes the expected surface', () => {
    const s = useSettings()
    for (const key of ['settings', 'loading', 'error', 'ensureLoaded',
      'refresh', 'setSettings', 'patchSettings', 'resetState']) {
      expect(s).toHaveProperty(key)
    }
  })

  it('settings is null before the first load', () => {
    expect(useSettings().settings.value).toBeNull()
  })

  describe('ensureLoaded', () => {
    it('fetches /settings once and stores the payload', async () => {
      mockApi.get.mockResolvedValue({ data: SETTINGS })
      const s = useSettings()

      const ok = await s.ensureLoaded()

      expect(ok).toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(1)
      expect(mockApi.get).toHaveBeenCalledWith('/settings')
      expect(s.settings.value).toEqual(SETTINGS)
    })

    it('coalesces concurrent callers onto a single request', async () => {
      mockApi.get.mockResolvedValue({ data: SETTINGS })
      const s = useSettings()

      await Promise.all([s.ensureLoaded(), s.ensureLoaded(), s.ensureLoaded()])

      expect(mockApi.get).toHaveBeenCalledTimes(1)
    })

    it('does not refetch once loaded', async () => {
      mockApi.get.mockResolvedValue({ data: SETTINGS })
      const s = useSettings()

      await s.ensureLoaded()
      await s.ensureLoaded()

      expect(mockApi.get).toHaveBeenCalledTimes(1)
    })

    it('retries on the next call after a failed load', async () => {
      mockApi.get.mockRejectedValueOnce(new Error('network'))
      const s = useSettings()

      expect(await s.ensureLoaded()).toBe(false)

      mockApi.get.mockResolvedValueOnce({ data: SETTINGS })
      expect(await s.ensureLoaded()).toBe(true)
      expect(mockApi.get).toHaveBeenCalledTimes(2)
    })

    it('pushes display prefs into useUnitSettings/useTimeFormat', async () => {
      mockApi.get.mockResolvedValue({ data: SETTINGS })
      await useSettings().ensureLoaded()

      expect(mockSetUseMetricUnits).toHaveBeenCalledWith(false)
      expect(mockSetTimeFormat).toHaveBeenCalledWith('24h')
    })
  })

  it('keeps the last-good payload when a refresh fails', async () => {
    mockApi.get.mockResolvedValueOnce({ data: SETTINGS })
    const s = useSettings()
    await s.ensureLoaded()

    mockApi.get.mockRejectedValueOnce(new Error('network'))
    const ok = await s.refresh()

    expect(ok).toBe(false)
    expect(s.settings.value).toEqual(SETTINGS)
    expect(s.error.value).toBeTruthy()
  })

  it('refresh forces a re-fetch', async () => {
    mockApi.get.mockResolvedValue({ data: SETTINGS })
    const s = useSettings()
    await s.ensureLoaded()
    await s.refresh()
    expect(mockApi.get).toHaveBeenCalledTimes(2)
  })

  describe('setSettings', () => {
    it('adopts a payload without a fetch and marks as loaded', async () => {
      const s = useSettings()
      s.setSettings(SETTINGS)

      expect(s.settings.value).toEqual(SETTINGS)
      expect(mockSetUseMetricUnits).toHaveBeenCalledWith(false)

      await s.ensureLoaded()
      expect(mockApi.get).not.toHaveBeenCalled()
    })
  })

  describe('patchSettings', () => {
    it('merges a persisted field without importing unrelated draft state', () => {
      const s = useSettings()
      s.setSettings(SETTINGS)

      const patch = { display: { station_name: 'Front Porch' } }
      expect(s.patchSettings(patch)).toBe(true)

      expect(s.settings.value).toEqual({
        ...SETTINGS,
        display: { ...SETTINGS.display, station_name: 'Front Porch' }
      })

      patch.display.station_name = 'mutated by caller'
      expect(s.settings.value.display.station_name).toBe('Front Porch')
    })

    it('keeps a local persisted patch when an older refresh resolves later', async () => {
      const s = useSettings()
      s.setSettings(SETTINGS)

      let resolveRefresh
      mockApi.get.mockImplementationOnce(() => new Promise((resolve) => {
        resolveRefresh = resolve
      }))
      const refresh = s.refresh()

      s.patchSettings({ display: { station_name: 'Front Porch' } })
      resolveRefresh({ data: SETTINGS })

      expect(await refresh).toBe(true)
      expect(s.settings.value.display.station_name).toBe('Front Porch')
    })
  })
})
