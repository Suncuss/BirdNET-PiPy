import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useUpdateOverlay } from '@/composables/useUpdateOverlay'
import { managedWaitActive } from '@/composables/useServiceRestart'
import { UPDATE_PROGRESS_URL } from '@/utils/updateStage'
import { READINESS_URL } from '@/utils/serviceReadiness'

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

  // Route fetches by URL: stageResponse for /update-progress,
  // readinessResponse for /api/system/readiness, versionResponse for the API
  // probe. Defaults: fresh stage file, API still down, services already up
  // once it is back.
  let stageResponse
  let readinessResponse
  let versionResponse

  const jsonResponse = (body, ok = true, status = ok ? 200 : 404) =>
    ({ ok, status, json: () => Promise.resolve(body) })

  beforeEach(() => {
    vi.useFakeTimers()
    stageResponse = () => Promise.resolve(jsonResponse(FRESH_STAGE))
    readinessResponse = () => Promise.resolve(jsonResponse({
      ready: true, services: { model: 'ready', recorder: 'ready' }
    }))
    versionResponse = () => Promise.reject(new TypeError('Failed to fetch'))
    fetchMock = vi.fn((url, options) => {
      if (url === UPDATE_PROGRESS_URL) return stageResponse()
      if (url === READINESS_URL) return readinessResponse()
      return versionResponse(url, options)
    })
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

    // API back with its services up: reload straight away
    versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(overlay.reloading.value).toBe(true)
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('reloads straight away on a backend without the readiness endpoint', async () => {
    readinessResponse = () => Promise.resolve(jsonResponse({ error: 'Not found' }, false, 404))
    await overlay.checkForActiveUpdate()

    versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('waits for the services to report ready before reloading', async () => {
    const states = [
      { ready: false, services: { model: 'starting', recorder: 'starting' } },
      { ready: false, services: { model: 'ready', recorder: 'starting' } },
      { ready: true, services: { model: 'ready', recorder: 'ready' } }
    ]
    readinessResponse = () => Promise.resolve(jsonResponse(states.shift() || states[0]))
    await overlay.checkForActiveUpdate()

    versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(overlay.reloading.value).toBe(true)
    expect(overlay.readinessMessage.value).toBe('Loading the detection model')
    expect(window.location.reload).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(2000)
    expect(overlay.readinessMessage.value).toBe('Starting the audio recorder')
    expect(window.location.reload).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(2000)
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('never reloads after being dismissed during the readiness wait', async () => {
    readinessResponse = () => Promise.resolve(jsonResponse({
      ready: false, services: { model: 'starting', recorder: 'ready' }
    }))
    await overlay.checkForActiveUpdate()

    versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(overlay.reloading.value).toBe(true)

    overlay.deactivateUpdateOverlay()
    expect(overlay.readinessMessage.value).toBe('')
    await vi.advanceTimersByTimeAsync(120000)
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('keeps polling while nginx reports the upstream down (502/503/504)', async () => {
    await overlay.checkForActiveUpdate()

    for (const status of [502, 503, 504]) {
      versionResponse = () => Promise.resolve(jsonResponse({}, false, status))
      await vi.advanceTimersByTimeAsync(5000)
      expect(overlay.reloading.value).toBe(false)
    }
  })

  it('reloads when the API answers 401 (private station, signed-out visitor)', async () => {
    await overlay.checkForActiveUpdate()

    versionResponse = () => Promise.resolve(jsonResponse({ error: 'Authentication required' }, false, 401))
    await vi.advanceTimersByTimeAsync(5000)

    expect(overlay.reloading.value).toBe(true)
  })

  describe('checkForUpdateAtBoot', () => {
    // A connect to a removed container neither answers nor fails promptly:
    // the probe hangs until its own abort fires.
    const hangUntilAborted = (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })

    it('shows the overlay straight from the stage file, before any API call has failed', async () => {
      versionResponse = hangUntilAborted

      const boot = overlay.checkForUpdateAtBoot()
      await vi.advanceTimersByTimeAsync(0)

      // Visible while the probe is still hanging — no waiting on a failure
      expect(overlay.visible.value).toBe(true)
      expect(overlay.stageMessage.value).toBe('Downloading updated images (2 of 3)')

      // The unanswered probe is abandoned and the overlay stays up
      await vi.advanceTimersByTimeAsync(4000)
      await boot
      expect(overlay.visible.value).toBe(true)
    })

    it('stays up when the API probe fails', async () => {
      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(true)
    })

    it('dismisses without reloading when the API answers (stage fresh, stack still up)', async () => {
      versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'a' }))

      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(false)
      // A reload would find the same fresh stage and loop
      await vi.advanceTimersByTimeAsync(30000)
      expect(window.location.reload).not.toHaveBeenCalled()
    })

    it('dismisses on a 401 — a login-walled API is up, and the overlay would cover the login dialog', async () => {
      versionResponse = () => Promise.resolve(jsonResponse({ error: 'Authentication required' }, false, 401))

      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(false)
    })

    it('does not dismiss when a page request fails while the probe is pending', async () => {
      let answerProbe
      versionResponse = () => new Promise(resolve => { answerProbe = resolve })

      const boot = overlay.checkForUpdateAtBoot()
      await vi.advanceTimersByTimeAsync(0)
      expect(overlay.visible.value).toBe(true)

      // A page request hits the dead upstream; the reactive check is a no-op
      await overlay.checkForActiveUpdate()
      // ...and the API comes back before the probe settles
      answerProbe(jsonResponse({ boot_id: 'b' }))
      await boot

      expect(overlay.visible.value).toBe(true)
      // The poll owns recovery: it reloads, re-running the failed requests
      versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))
      await vi.advanceTimersByTimeAsync(5000)
      expect(window.location.reload).toHaveBeenCalled()
    })

    it('does not dismiss when a page request fails while the stage fetch is in flight', async () => {
      let answerStage
      stageResponse = () => new Promise(resolve => { answerStage = resolve })
      versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'b' }))

      const boot = overlay.checkForUpdateAtBoot()
      await vi.advanceTimersByTimeAsync(0)
      await overlay.checkForActiveUpdate()
      answerStage(jsonResponse(FRESH_STAGE))
      await boot

      expect(overlay.visible.value).toBe(true)
    })

    it('leaves the reactive path armed after a dismissal', async () => {
      versionResponse = () => Promise.resolve(jsonResponse({ boot_id: 'a' }))
      await overlay.checkForUpdateAtBoot()
      expect(overlay.visible.value).toBe(false)

      // The stack then goes down and an API call fails
      versionResponse = () => Promise.reject(new TypeError('Failed to fetch'))
      await overlay.checkForActiveUpdate()

      expect(overlay.visible.value).toBe(true)
    })

    it('ignores a failed stage — it lingers on a healthy station', async () => {
      stageResponse = () => Promise.resolve(jsonResponse({
        ...FRESH_STAGE,
        stage: 'failed',
        message: 'Update failed, restarting the previous version'
      }))

      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(false)
      // ...while the reactive path, backed by a real API failure, still shows it
      await overlay.checkForActiveUpdate()
      expect(overlay.visible.value).toBe(true)
    })

    it('stays hidden when there is no stage file, without probing the API', async () => {
      stageResponse = () => Promise.resolve(jsonResponse({}, false))

      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(false)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('stays hidden while a managed wait owns the UX', async () => {
      managedWaitActive.value = true

      await overlay.checkForUpdateAtBoot()

      expect(overlay.visible.value).toBe(false)
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })
})
