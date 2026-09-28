import api from './api'
import { ref } from 'vue'

// All settings writers share ordering and the server's content revision.
// A rejected write leaves the queue usable; conflicts require a fresh GET.
let queue = Promise.resolve()
let etag = null
// The revision this client held before it adopted the current one. A pushed
// status that still carries it describes a state this client has already
// moved past, not a save from elsewhere.
let superseded = null
let session = 0
let generation = 0
export const pendingSettingsWrites = ref(0)

export const settingsWriteGeneration = () => generation
export const currentSettingsRevision = () => etag
export const supersededSettingsRevision = () => superseded
export const acceptSettingsRevision = (response) => {
  // Our ETag is a hash of the saved settings document. nginx adds W/ when
  // compressing the response, but that does not change the content revision
  // carried by the socket's settings_status event or the API's If-Match
  // precondition.
  const next = response.headers?.etag?.replace(/^W\//, '') || null
  if (next !== etag) superseded = etag
  etag = next
}

export function writeSettings(endpoint, payload) {
  const body = JSON.parse(JSON.stringify(payload))
  const startedSession = session
  generation += 1
  pendingSettingsWrites.value += 1
  const result = queue.then(async () => {
    if (session !== startedSession) throw new Error('Settings session changed')
    const response = await (etag
      ? api.put(endpoint, body, { headers: { 'If-Match': etag } })
      : api.put(endpoint, body))
    if (session !== startedSession) throw new Error('Settings session changed')
    generation += 1
    acceptSettingsRevision(response)
    return response
  }).finally(() => { pendingSettingsWrites.value -= 1 })
  queue = result.catch(() => {})
  return result
}

export function resetSettingsWrites() {
  session += 1
  generation += 1
  etag = null
  superseded = null
}
