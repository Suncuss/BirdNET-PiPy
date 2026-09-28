// An axios-style rejection carrying an HTTP status — what api-client mocks
// should reject with so error classification sees `error.response.status`.
// `data` is the optional response body (e.g. a 503's retry advice).
export const httpError = (status, data) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data }
  })
