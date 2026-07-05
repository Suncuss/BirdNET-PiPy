// An axios-style rejection carrying an HTTP status — what api-client mocks
// should reject with so error classification sees `error.response.status`.
export const httpError = (status) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status }
  })
