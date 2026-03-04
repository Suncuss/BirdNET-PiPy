import api, { getAppBaseUrl } from '@/services/api'

const resolveApiBaseUrl = () => {
  const base = api?.defaults?.baseURL || '/api'
  return base.endsWith('/') ? base.slice(0, -1) : base
}

export const getDefaultBirdImageUrl = () => {
  const appBase = getAppBaseUrl()
  return `${appBase}/default_bird.webp`
}

export const isDefaultBirdImageUrl = (url) => {
  if (!url) return false
  const normalized = String(url).split('?')[0].split('#')[0]
  return normalized === '/default_bird.webp' || normalized.endsWith('/default_bird.webp')
}

export const getAudioUrl = (filename) => {
  if (!filename) return ''
  return `${resolveApiBaseUrl()}/audio/${encodeURIComponent(filename)}`
}

export const getSpectrogramUrl = (filename) => {
  if (!filename) return ''
  return `${resolveApiBaseUrl()}/spectrogram/${encodeURIComponent(filename)}`
}

export const getBirdImageUrl = (speciesName) => {
  if (!speciesName) return ''
  return `${resolveApiBaseUrl()}/bird/${encodeURIComponent(speciesName)}/image`
}
