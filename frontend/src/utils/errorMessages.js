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

// User-facing message for a recording that won't play: pass the element's
// MediaError (from its 'error' event, or audio.error), and the reason play()
// rejected when that is how it failed.
export function playbackErrorMessage(mediaError, playRejection) {
  if (playRejection?.name === 'NotAllowedError') {
    return 'Your browser blocked playback. Try again.'
  }
  // MediaError codes (1=ABORTED, 2=NETWORK, 3=DECODE, 4=SRC_NOT_SUPPORTED),
  // numeric so this does not depend on the MediaError global
  switch (mediaError?.code) {
    case 1:
      return 'Playback of this recording was interrupted.'
    case 2:
      return 'This recording could not be loaded. Check your connection.'
    case 3:
      return 'This recording could not be decoded.'
    case 4:
      // Browsers also report a missing file this way (404, e.g. removed by
      // storage cleanup) or an expired media link
      return 'This recording is missing or can no longer be opened.'
    default:
      return 'This recording could not be played.'
  }
}
