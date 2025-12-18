import api from '@/services/api'

const getApiBaseUrl = () => {
  const base = api?.defaults?.baseURL || '/api'
  return base.endsWith('/') ? base.slice(0, -1) : base
}

export const getAudioUrl = (filename) => {
  if (!filename) return ''
  return `${getApiBaseUrl()}/audio/${encodeURIComponent(filename)}`
}

export const getSpectrogramUrl = (filename) => {
  if (!filename) return ''
  return `${getApiBaseUrl()}/spectrogram/${encodeURIComponent(filename)}`
}
