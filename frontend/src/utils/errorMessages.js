// User-facing message shown when an API request fails (network down,
// timeout, server unreachable).
export const ERR_UNREACHABLE = 'Hmm, cannot reach the server'

// Quiet placeholder shown when data is auth-gated (request returned 401);
// the login modal is already up via the api interceptor.
export const ERR_SIGN_IN = 'Sign in to view this data'

// Classify a failed request for display: a 401 means the server responded
// fine but the data needs login — it must never read as "server down". A
// response that names its error with a code is asserting the text is meant
// for the user (e.g. why the saved settings file could not be read).
export function fetchErrorMessage(error) {
  if (error?.response?.status === 401) return ERR_SIGN_IN
  const body = error?.response?.data
  return body?.code && body.error ? body.error : ERR_UNREACHABLE
}
