/**
 * Notification service definitions for the AddNotificationModal.
 * Each service defines its form fields and a buildUrl() function
 * that constructs the Apprise-compatible URL from user input.
 */

const enc = encodeURIComponent
const dec = decodeURIComponent

/**
 * Derive Apprise scheme from a server URL input.
 * Checks each entry in prefixMap (ordered { prefix → scheme }) to find a match,
 * then falls back to the defaultScheme.
 * Returns { scheme, host } where host has the matched protocol stripped.
 */
function deriveScheme(serverInput, { prefixMap, defaultScheme }) {
  const trimmed = serverInput.trim()
  for (const [prefix, scheme] of Object.entries(prefixMap)) {
    if (trimmed.startsWith(prefix)) {
      return { scheme, host: trimmed.slice(prefix.length) }
    }
  }
  // No known prefix matched — strip any leftover https:// and use default
  const host = trimmed.replace(/^https?:\/\//, '')
  return { scheme: defaultScheme, host }
}

export const SERVICES = [
  {
    id: 'telegram',
    label: 'Telegram',
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: '123456789:ABCdef...', required: true, type: 'text' },
      { key: 'chat_id', label: 'Chat ID', placeholder: '12345678', required: true, type: 'text' }
    ],
    buildUrl(values) {
      return `tgram://${enc(values.bot_token)}/${enc(values.chat_id)}`
    },
    parseUrl(url) {
      const rest = url.replace(/^tgram:\/\//, '')
      const parts = rest.split('/')
      return { bot_token: dec(parts[0] || ''), chat_id: dec(parts[1] || '') }
    },
    helpUrl: 'https://appriseit.com/services/telegram/'
  },
  {
    id: 'ntfy',
    label: 'ntfy',
    fields: [
      { key: 'topic', label: 'Topic', placeholder: 'my-bird-alerts', required: true, type: 'text' },
      { key: 'server', label: 'Server (optional)', placeholder: 'https://ntfy.sh', required: false, type: 'text' }
    ],
    buildUrl(values) {
      const topic = enc(values.topic)
      if (!values.server?.trim()) {
        return `ntfys://${topic}`
      }
      const { scheme, host } = deriveScheme(values.server, {
        prefixMap: { 'http://': 'ntfy' },
        defaultScheme: 'ntfys'
      })
      return `${scheme}://${host}/${topic}`
    },
    parseUrl(url) {
      const match = url.match(/^(ntfys?):\/\/(.+)$/)
      if (!match) return null
      const [, scheme, rest] = match
      const slashIdx = rest.indexOf('/')
      if (slashIdx === -1) return { topic: dec(rest), server: '' }
      const host = rest.slice(0, slashIdx)
      const topic = rest.slice(slashIdx + 1)
      return { topic: dec(topic), server: `${scheme === 'ntfys' ? 'https' : 'http'}://${host}` }
    },
    helpUrl: 'https://appriseit.com/services/ntfy/'
  },
  {
    id: 'email',
    label: 'Email',
    fields: [
      { key: 'email', label: 'Email', placeholder: 'you@gmail.com', required: true, type: 'email' },
      { key: 'password', label: 'App Password', placeholder: 'App-specific password', required: true, type: 'password' },
      { key: 'smtp', label: 'SMTP (optional)', placeholder: 'smtp.gmail.com', required: false, type: 'text' }
    ],
    buildUrl(values) {
      const parts = values.email.split('@')
      if (parts.length !== 2) return null
      const user = enc(parts[0])
      const domain = parts[1]
      let url = `mailtos://${user}:${enc(values.password)}@${domain}`
      if (values.smtp?.trim()) {
        url += `?smtp=${enc(values.smtp.trim())}`
      }
      return url
    },
    parseUrl(url) {
      const match = url.match(/^mailtos?:\/\/([^:]+):([^@]+)@([^?]+)(\?.*)?$/)
      if (!match) return null
      const [, user, password, domain, query] = match
      const smtp = query ? new URLSearchParams(query.slice(1)).get('smtp') : ''
      return { email: `${dec(user)}@${domain}`, password: dec(password), smtp: smtp ? dec(smtp) : '' }
    },
    parseError: 'Invalid email address format.',
    helpUrl: 'https://appriseit.com/services/email/'
  },
  {
    id: 'homeassistant',
    label: 'Home Assistant',
    fields: [
      { key: 'server', label: 'Server', placeholder: 'http://192.168.1.60:8123', required: true, type: 'text' },
      { key: 'token', label: 'Access Token', placeholder: 'Long-lived access token', required: true, type: 'password' }
    ],
    buildUrl(values) {
      const { scheme, host } = deriveScheme(values.server, {
        prefixMap: { 'https://': 'hassios' },
        defaultScheme: 'hassio'
      })
      return `${scheme}://${host}/${enc(values.token)}`
    },
    parseUrl(url) {
      const match = url.match(/^(hassios?):\/\/(.+)\/([^/]+)$/)
      if (!match) return null
      const [, scheme, host, token] = match
      return { server: `${scheme === 'hassios' ? 'https' : 'http'}://${host}`, token: dec(token) }
    },
    helpUrl: 'https://appriseit.com/services/homeassistant/'
  },
  {
    id: 'mqtt',
    label: 'MQTT',
    fields: [
      { key: 'server', label: 'Broker', placeholder: '192.168.1.60:1883', required: true, type: 'text' },
      { key: 'topic', label: 'Topic', placeholder: 'birdnet/detections', required: true, type: 'text' },
      { key: 'user', label: 'Username (optional)', placeholder: '', required: false, type: 'text' },
      { key: 'password', label: 'Password (optional)', placeholder: '', required: false, type: 'password' }
    ],
    buildUrl(values) {
      const { scheme, host } = deriveScheme(values.server, {
        prefixMap: { 'mqtts://': 'mqtts', 'mqtt://': 'mqtt' },
        defaultScheme: 'mqtt'
      })
      let auth = ''
      if (values.user?.trim()) {
        auth = values.password?.trim()
          ? `${enc(values.user)}:${enc(values.password)}@`
          : `${enc(values.user)}@`
      }
      return `${scheme}://${auth}${host}/${enc(values.topic)}`
    },
    parseUrl(url) {
      const match = url.match(/^(mqtts?):\/\/(?:([^:@]+)(?::([^@]+))?@)?(.+?)\/([^/]+)$/)
      if (!match) return null
      const [, scheme, user, password, host, topic] = match
      return {
        server: `${scheme}://${host}`,
        topic: dec(topic),
        user: user ? dec(user) : '',
        password: password ? dec(password) : ''
      }
    },
    helpUrl: 'https://appriseit.com/services/mqtt/'
  },
  {
    id: 'custom',
    label: 'Custom URL',
    fields: [
      { key: 'url', label: 'Apprise URL', placeholder: 'scheme://...', required: true, type: 'text' }
    ],
    buildUrl(values) {
      return values.url.trim()
    },
    parseUrl(url) {
      return { url }
    },
    helpUrl: 'https://appriseit.com/'
  }
]

/**
 * Map from Apprise URL scheme to friendly service name.
 * Derived from SERVICES definitions, plus common extra schemes.
 */
export const SCHEME_TO_SERVICE_NAME = {
  tgram: 'Telegram',
  ntfy: 'ntfy', ntfys: 'ntfy',
  mailto: 'Email', mailtos: 'Email',
  hassio: 'Home Assistant', hassios: 'Home Assistant',
  mqtt: 'MQTT', mqtts: 'MQTT',
  // Additional Apprise services not in our picker
  discord: 'Discord', slack: 'Slack',
  json: 'JSON', jsons: 'JSON',
  gotify: 'Gotify', gotifys: 'Gotify',
  pbul: 'Pushbullet', pover: 'Pushover',
  matrix: 'Matrix', matrixs: 'Matrix', mmost: 'Mattermost',
  signal: 'Signal', rockets: 'Rocket.Chat', rocket: 'Rocket.Chat',
  teams: 'Teams', dingtalk: 'DingTalk', bark: 'Bark',
  notica: 'Notica', simplepush: 'SimplePush', wp: 'WordPress',
}

const SCHEME_TO_ID = {
  tgram: 'telegram',
  ntfy: 'ntfy', ntfys: 'ntfy',
  mailto: 'email', mailtos: 'email',
  hassio: 'homeassistant', hassios: 'homeassistant',
  mqtt: 'mqtt', mqtts: 'mqtt',
}

/**
 * Given an Apprise URL, find the matching SERVICES entry and parse it.
 * Returns { service, values } or falls back to 'custom'.
 */
export function parseAppriseUrl(url) {
  const scheme = url.split('://')[0]?.toLowerCase() || ''
  const serviceId = SCHEME_TO_ID[scheme] || 'custom'
  const custom = SERVICES.find(s => s.id === 'custom')
  if (serviceId !== 'custom') {
    const service = SERVICES.find(s => s.id === serviceId)
    try {
      const values = service?.parseUrl(url)
      // Verify round-trip: if buildUrl produces a different URL, the parser
      // missed something (extra query params, scheme change) — use custom editor
      if (values && service.buildUrl(values) === url) {
        return { service, values }
      }
    } catch { /* fall through to custom */ }
  }
  return { service: custom, values: custom.parseUrl(url) }
}

// Exported for testing
export { deriveScheme }
