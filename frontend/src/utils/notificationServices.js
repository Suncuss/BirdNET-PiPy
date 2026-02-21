/**
 * Notification service definitions for the AddNotificationModal.
 * Each service defines its form fields and a buildUrl() function
 * that constructs the Apprise-compatible URL from user input.
 */

const enc = encodeURIComponent

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
    parseError: 'Invalid email address format.',
    helpUrl: 'https://appriseit.com/services/email/'
  },
  {
    id: 'homeassistant',
    label: 'Home Assistant',
    fields: [
      { key: 'server', label: 'Server', placeholder: 'homeassistant.local:8123', required: true, type: 'text' },
      { key: 'token', label: 'Access Token', placeholder: 'Long-lived access token', required: true, type: 'password' }
    ],
    buildUrl(values) {
      const { scheme, host } = deriveScheme(values.server, {
        prefixMap: { 'http://': 'hassio' },
        defaultScheme: 'hassios'
      })
      return `${scheme}://${host}/${enc(values.token)}`
    },
    helpUrl: 'https://appriseit.com/services/homeassistant/'
  },
  {
    id: 'mqtt',
    label: 'MQTT',
    fields: [
      { key: 'server', label: 'Broker', placeholder: 'localhost', required: true, type: 'text' },
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

// Exported for testing
export { deriveScheme }
