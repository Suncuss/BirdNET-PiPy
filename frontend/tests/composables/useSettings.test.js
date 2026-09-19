/**
 * Tests for useSettings composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'

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
  it('uses the content revision when nginx weakens a compressed response ETag', async () => {
    const store = useSettings()
    mockApi.get.mockResolvedValue({ data: SETTINGS, headers: { etag: 'W/"one"' } })
    await store.ensureLoaded()
    expect(store.revision.value).toBe('"one"')
    mockApi.put.mockResolvedValueOnce({ data: { settings: SETTINGS }, headers: { etag: 'W/"two"' } })
    await store.save({ display: { station_name: 'Local' } })
    expect(mockApi.put).toHaveBeenLastCalledWith('/settings', { display: { station_name: 'Local' } }, {
      headers: { 'If-Match': '"one"' }
    })
    expect(store.revision.value).toBe('"two"')
    mockApi.put.mockResolvedValueOnce({ data: { settings: SETTINGS }, headers: { etag: 'W/"three"' } })
    await store.write('/settings/units', { use_metric_units: true })
    expect(mockApi.put.mock.calls[1][2]).toEqual({ headers: { 'If-Match': '"two"' } })
  })

  it('does not report an empty cache as loaded when a newer refresh supersedes bootstrap', async () => {
    const store = useSettings()
    const releases = []
    mockApi.get.mockImplementation(() => new Promise(resolve => releases.push(resolve)))
    const bootstrap = store.ensureLoaded()
    const refresh = store.refresh()
    releases[0]({ data: SETTINGS })
    expect(await bootstrap).toBe(false)
    expect(store.settings.value).toBeNull()
    expect(store.loading.value).toBe(true)
    const joined = store.ensureLoaded()
    expect(mockApi.get).toHaveBeenCalledTimes(2)
    releases[1]({ data: SETTINGS })
    expect(await refresh).toBe(true)
    expect(await joined).toBe(true)
    expect(store.settings.value).toEqual(SETTINGS)
    expect(store.loading.value).toBe(false)
  })

  it('a GET during a pending write cannot change its precondition revision', async () => {
    const store = useSettings()
    mockApi.get.mockResolvedValue({ data: SETTINGS, headers: { etag: '"one"' } })
    await store.refresh()
    let release
    mockApi.put.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const pending = store.save({ display: { station_name: 'Local' } })
    await flushPromises()
    mockApi.get.mockResolvedValue({ data: { ...SETTINGS, display: { station_name: 'Remote' } }, headers: { etag: '"remote"' } })
    await store.refresh()
    expect(store.revision.value).toBe('"one"')
    release({ data: { settings: SETTINGS }, headers: { etag: '"two"' } })
    await pending
    expect(store.revision.value).toBe('"two"')
  })
  it('serializes writes and sends the revision from the previous confirmation', async () => {
    const store = useSettings()
    mockApi.get.mockResolvedValue({ data: SETTINGS, headers: { etag: '"one"' } })
    await store.refresh()
    let release
    mockApi.put.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
      .mockResolvedValueOnce({ data: { settings: SETTINGS }, headers: { etag: '"three"' } })
    const first = store.save({ display: { station_name: 'First' } })
    const second = store.save({ display: { station_name: 'Second' } })
    await flushPromises()
    expect(mockApi.put).toHaveBeenCalledTimes(1)
    release({ data: { settings: SETTINGS }, headers: { etag: '"two"' } })
    await Promise.all([first, second])
    expect(mockApi.put.mock.calls[0][2]).toEqual({ headers: { 'If-Match': '"one"' } })
    expect(mockApi.put.mock.calls[1][2]).toEqual({ headers: { 'If-Match': '"two"' } })
  })

  it('rejects edits to a field changed by a background refresh', async () => {
    const store = useSettings()
    store.setSettings(SETTINGS)
    const base = structuredClone(SETTINGS)
    store.patchSettings({ display: { station_name: 'Another session' } })
    await expect(store.save({ display: { station_name: 'Stale draft' } }, { base })).rejects.toThrow('changed')
    expect(mockApi.put).not.toHaveBeenCalled()
  })

  it('does not revive private settings after logout while a GET is pending', async () => {
    const store = useSettings()
    let release
    mockApi.get.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const pending = store.refresh()
    store.resetState()
    release({ data: SETTINGS, headers: { etag: '"old-session"' } })
    await pending
    expect(store.settings.value).toBeNull()
    expect(store.revision.value).toBeNull()
  })
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

  it('keeps the server reason when the saved file is unreadable', async () => {
    const rejection = { response: { status: 503, data: {
      code: 'settings_unreadable', error: 'Saved settings could not be read: Expecting , delimiter: line 12' } } }
    mockApi.get.mockRejectedValueOnce(rejection)
    const s = useSettings()
    expect(await s.ensureLoaded()).toBe(false)
    expect(s.error.value).toContain('line 12')
    mockApi.get.mockResolvedValueOnce({ data: SETTINGS })
    await s.refresh()
    expect(s.error.value).toBe('')
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
