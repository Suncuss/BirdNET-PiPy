import { API_BASE } from '@/services/baseUrl'

export const getDefaultBirdImageUrl = () => 'default_bird.webp'

export const isDefaultBirdImageUrl = (url) => url === 'default_bird.webp'

export const getAudioUrl = (filename) => {
  if (!filename) return ''
  return `${API_BASE}/audio/${encodeURIComponent(filename)}`
}

export const getSpectrogramUrl = (filename) => {
  if (!filename) return ''
  return `${API_BASE}/spectrogram/${encodeURIComponent(filename)}`
}

export const getBirdImageUrl = (speciesName) => {
  if (!speciesName) return ''
  return `${API_BASE}/bird/${encodeURIComponent(speciesName)}/image`
}
