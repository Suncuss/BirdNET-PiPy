import { API_BASE } from '@/services/baseUrl'

export const getDefaultBirdImageUrl = () => 'default_bird.webp'

export const isDefaultBirdImageUrl = (url) => url === 'default_bird.webp'

// `sig` is the server-provided signed query (`exp=..&sig=..`) that authorizes an
// anonymous request when authentication is enabled (see backend media_access).
// Owners/auth-off don't need it (the session cookie suffices), so it's optional.
export const getAudioUrl = (filename, sig = '') => {
  if (!filename) return ''
  const url = `${API_BASE}/audio/${encodeURIComponent(filename)}`
  return sig ? `${url}?${sig}` : url
}

export const getSpectrogramUrl = (filename, sig = '') => {
  if (!filename) return ''
  const url = `${API_BASE}/spectrogram/${encodeURIComponent(filename)}`
  return sig ? `${url}?${sig}` : url
}

export const getBirdImageUrl = (speciesName) => {
  if (!speciesName) return ''
  return `${API_BASE}/bird/${encodeURIComponent(speciesName)}/image`
}
