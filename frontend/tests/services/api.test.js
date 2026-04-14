/**
 * Tests for the api service — primarily guards the 401 interceptor's
 * narrowing behavior (only non-auth endpoints should trigger auth:required).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Capture the error handler when api.js registers the interceptor.
// axios.create() is called once per module load; we record each instance's
// response.use error handler so tests can call it directly.
// vi.hoisted() is required because vi.mock() factories run before top-level
// declarations are initialized.
const capturedErrorHandlers = vi.hoisted(() => [])

vi.mock('axios', () => {
  const makeInstance = () => ({
    defaults: { baseURL: '' },
    interceptors: {
      response: {
        use: vi.fn((_success, error) => {
          capturedErrorHandlers.push(error)
        })
      }
    }
  })

  return {
    default: {
      create: vi.fn(() => makeInstance())
    }
  }
})

// Importing the module triggers axios.create + interceptors.response.use,
// which populates capturedErrorHandlers[0] with the default instance's handler.
import '@/services/api'

describe('api service 401 interceptor', () => {
  let dispatchSpy

  beforeEach(() => {
    dispatchSpy = vi.spyOn(window, 'dispatchEvent')
  })

  afterEach(() => {
    dispatchSpy.mockRestore()
  })

  const errorHandler = () => capturedErrorHandlers[0]

  const error = (status, url) => ({
    response: { status },
    config: { url }
  })

  it('dispatches auth:required on 401 from non-auth endpoints', async () => {
    await expect(errorHandler()(error(401, '/settings'))).rejects.toBeDefined()

    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'auth:required' })
    )
  })

  it('does NOT dispatch auth:required on 401 from /auth/login', async () => {
    await expect(errorHandler()(error(401, '/auth/login'))).rejects.toBeDefined()

    const authRequiredCalls = dispatchSpy.mock.calls.filter(
      ([event]) => event?.type === 'auth:required'
    )
    expect(authRequiredCalls).toHaveLength(0)
  })

  it('does NOT dispatch auth:required on 401 from /auth/status', async () => {
    await expect(errorHandler()(error(401, '/auth/status'))).rejects.toBeDefined()

    const authRequiredCalls = dispatchSpy.mock.calls.filter(
      ([event]) => event?.type === 'auth:required'
    )
    expect(authRequiredCalls).toHaveLength(0)
  })

  it('does NOT dispatch auth:required on non-401 status codes', async () => {
    await expect(errorHandler()(error(500, '/settings'))).rejects.toBeDefined()

    const authRequiredCalls = dispatchSpy.mock.calls.filter(
      ([event]) => event?.type === 'auth:required'
    )
    expect(authRequiredCalls).toHaveLength(0)
  })

  it('re-throws the error so callers can handle it', async () => {
    const err = error(401, '/settings')
    await expect(errorHandler()(err)).rejects.toBe(err)
  })
})
