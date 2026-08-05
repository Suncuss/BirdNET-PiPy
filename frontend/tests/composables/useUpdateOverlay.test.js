import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useUpdateOverlay } from '@/composables/useUpdateOverlay'
import { managedWaitActive } from '@/composables/useServiceRestart'
import { UPDATE_PROGRESS_URL } from '@/utils/updateStage'

// useServiceRestart (imported for managedWaitActive) pulls in the api service
vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  createLongRequest: vi.fn()
}))

vi.mock('@/composables/useLogger', () => ({
  useLogger: () => ({
    info: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn()
  })
}))

const FRESH_STAGE = {
  stage: 'pull',
  message: 'Downloading updated images (2 of 3)',
  timestamp: new Date().toISOString()
}

describe('useUpdateOverlay', () => {
  let fetchMock
  let originalLocation
  let overlay

  // Route fetches by URL: stageResponse for /update-progress, versionResponse
  // for the API probe. Defaults: fresh stage file, API still down.
  let stageResponse
  let versionResponse

  const jsonResponse = (body, ok = true) => ({ ok, json: () => Promise.resolve(body) })

  beforeEach(() => {
    vi.useFakeTimers()
    stageResponse = () => Promise.resolve(jsonResponse(FRESH_STAGE))
    versionResponse = () => Promise.reject(new TypeError('Failed to fetch'))
    fetchMock = vi.fn((url) =>
      url === UPDATE_PROGRESS_URL ? stageResponse() : versionResponse()
    )
    vi.stubGlobal('fetch', fetchMock)

    originalLocation = window.location
    delete window.location
    window.location = { reload: vi.fn() }

    overlay = useUpdateOverlay()
  })

  afterEach(() => {
    overlay.deactivateUpdateOverlay()
    managedWaitActive.value = false
    vi.unstubAllGlobals()
    vi.useRealTimers()
    window.location = originalLocation
  })

  it('activates on a fresh stage file and shows its message', async () => {
    await overlay.checkForActiveUpdate()

    expect(overlay.visible.value).toBe(true)
    expect(overlay.stageMessage.value).toBe('Downloading updated images (2 of 3)')
  })

  it('stays hidden when the stage file is absent (ordinary outage)', async () => {
    stageResponse = () => Promise.resolve(jsonResponse({}, false))

    await overlay.checkForActiveUpdate()

    expect(overlay.visible.value).toBe(false)
  })

  it('stays hidden when the stage is stale (leftover from a failed update)', async () => {
    stageResponse = () => Promise.resolve(jsonResponse({
      ...FRESH_STAGE,
      timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
    }))

    await overlay.checkForActiveUpdate()

    expect(overlay.visible.value).toBe(false)
  })

  it('stays hidden while a managed wait owns the UX (initiating tab)', async () => {
    managedWaitActive.value = true

    await overlay.checkForActiveUpdate()

    expect(overlay.visible.value).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps the stage message current while polling', async () => {
    await overlay.checkForActiveUpdate()

    stageResponse = () => Promise.resolve(jsonResponse({
      ...FRESH_STAGE,
      message: 'Restarting services with the new version'
    }))
    await vi.advanceTimersByTimeAsync(5000)

    expect(overlay.stageMessage.value).toBe('Restarting services with the new version')
  })

  it('reloads once the API answers again', async () => {
    await overlay.checkForActiveUpdate()
    expect(overlay.visible.value).toBe(true)

    // Still down on the first poll
    await vi.advanceTimersByTimeAsync(5000)
    expect(overlay.reloading.value).toBe(false)
    expect(window.location.reload).not.toHaveBeenCalled()

    // API back: reloading state, then the actual reload after the settle delay
    versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(overlay.reloading.value).toBe(true)
    expect(window.location.reload).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(3000)
    expect(window.location.reload).toHaveBeenCalled()
  })
})
