import { describe, it, expect } from 'vitest'
import { ERR_UNREACHABLE, ERR_SIGN_IN, fetchErrorMessage } from '@/utils/errorMessages'
import { httpError } from '../helpers/httpError'

describe('fetchErrorMessage', () => {
  it('maps a 401 response to the sign-in message, never "unreachable"', () => {
    expect(fetchErrorMessage(httpError(401))).toBe(ERR_SIGN_IN)
  })

  it('maps a network failure (no response) to unreachable', () => {
    expect(fetchErrorMessage(new Error('Network Error'))).toBe(ERR_UNREACHABLE)
  })

  it('maps a non-auth server error (500) to unreachable', () => {
    expect(fetchErrorMessage(httpError(500))).toBe(ERR_UNREACHABLE)
  })

  it('surfaces a server reason that comes with an error code', () => {
    const coded = { response: { status: 503, data: { code: 'settings_unreadable', error: 'Saved settings could not be read: line 12' } } }
    expect(fetchErrorMessage(coded)).toBe('Saved settings could not be read: line 12')
    const uncoded = { response: { status: 503, data: { error: 'Service Unavailable' } } }
    expect(fetchErrorMessage(uncoded)).toBe(ERR_UNREACHABLE)
  })

  it('tolerates a missing error object', () => {
    expect(fetchErrorMessage(undefined)).toBe(ERR_UNREACHABLE)
  })
})
