// Deployment path prefix read once from <base href> in index.html.
// Standard mode: '/'. HA ingress: '/api/hassio_ingress/TOKEN/'.
const el = typeof document !== 'undefined' ? document.querySelector('base') : null
export const BASE = el?.getAttribute('href') || '/'
export const API_BASE = BASE + 'api'
export const SOCKET_PATH = BASE + 'socket.io'
