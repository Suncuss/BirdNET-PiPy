/**
 * Contract tests for the Content-Security-Policy nginx serves the SPA under
 * (frontend/nginx.conf). The policy is hand-written; these pin the allowances
 * known runtime consumers depend on, so a future tightening fails HERE with a
 * named consumer instead of silently breaking a browser-only code path.
 *
 * Why this exists: nothing in the JS test suite executes under nginx's
 * header, so CSP breakage is invisible to unit tests — 0.8.2 shipped
 * `script-src 'self'` and silently killed the Live Feed's Safari WASM
 * decoder (no live spectrogram on Safari/iOS, degraded fallback), and its
 * `connect-src` blocked the setup wizard's Nominatim address search.
 *
 * Pins alone only protect consumers someone remembered to catalogue, so the
 * scan suite below also extracts every external origin literal from
 * frontend/src and forces it to be classified against the CSP — a new
 * external integration fails here until it's either allowed or marked as a
 * non-fetching reference (plain link, placeholder text, XML namespace).
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const conf = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '../../nginx.conf'), 'utf8'
)
const cspLine = conf.split('\n').find((l) => l.includes('add_header Content-Security-Policy'))
const directives = Object.fromEntries(
  cspLine.match(/"([^"]+)"/)[1].split(';').map((d) => {
    const [name, ...values] = d.trim().split(/\s+/)
    return [name, values]
  })
)

describe('nginx CSP contract', () => {
  it('defines exactly one CSP header to reason about', () => {
    expect(conf.match(/add_header Content-Security-Policy/g)).toHaveLength(1)
  })

  it("script-src allows WASM compilation — the Live Feed's Safari stream decoder (mpg123-decoder in useIcecastStream) is WebAssembly", () => {
    expect(directives['script-src']).toContain("'wasm-unsafe-eval'")
  })

  it('img-src allows Wikimedia — gallery bird images load straight from *.wikimedia.org', () => {
    expect(directives['img-src']).toContain('https://*.wikimedia.org')
  })

  it('connect-src allows websockets — Socket.IO live detections/status', () => {
    expect(directives['connect-src']).toEqual(expect.arrayContaining(['ws:', 'wss:']))
  })

  it("connect-src allows Nominatim — the setup wizard's address search (SetupWizard.vue) geocodes with a direct browser fetch", () => {
    expect(directives['connect-src']).toContain('https://nominatim.openstreetmap.org')
  })

  it('style-src allows inline styles — Vue :style bindings throughout the app', () => {
    expect(directives['style-src']).toContain("'unsafe-inline'")
  })

  it('media-src and worker-src allow blob: — generated audio/worker resources', () => {
    expect(directives['media-src']).toContain('blob:')
    expect(directives['worker-src']).toContain('blob:')
  })
})

// Every external origin that appears as a literal in frontend/src, classified
// by how the browser uses it: a CSP directive name means the page itself
// connects there (and the origin must be allowed by that directive); 'exempt'
// means the origin is never fetched by the page — an <a href> navigation,
// form placeholder text, a doc string, or an XML namespace identifier.
// An origin missing from this map fails the scan test below.
const EXTERNAL_ORIGIN_USAGE = {
  'https://nominatim.openstreetmap.org': 'connect-src', // SetupWizard address search fetch

  'https://appriseit.com': 'exempt', // notification-service help links
  'https://open-meteo.com': 'exempt', // weather attribution links (data comes via our API)
  'https://ebird.org': 'exempt', // species-page links
  'https://app.birdweather.com': 'exempt', // station-management link (uploads are backend-side)
  'https://ntfy.sh': 'exempt', // form placeholder text
  'https://birdnet.example.com': 'exempt', // Site URL form placeholder text
  'https://github.com': 'exempt', // repo links / UA string
  'http://www.w3.org': 'exempt', // SVG xmlns namespace identifiers
  'http://192.168.1.60': 'exempt', // form placeholder text
}

const srcDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../src')
const foundOrigins = new Set(
  readdirSync(srcDir, { recursive: true })
    .filter((f) => /\.(vue|js)$/.test(f))
    .flatMap((f) => readFileSync(resolve(srcDir, f), 'utf8').match(/https?:\/\/[A-Za-z0-9.-]+/g) || [])
)

// Does a CSP source list allow this origin? Exact match or *.host wildcard.
const allowedBy = (origin, sources) =>
  sources.some((s) => {
    if (s === origin) return true
    const wild = s.match(/^(https?:\/\/)\*\.(.+)$/)
    return wild !== null && origin.startsWith(wild[1]) && origin.endsWith(`.${wild[2]}`)
  })

describe('external origin scan', () => {
  it('every external origin literal in frontend/src is classified in EXTERNAL_ORIGIN_USAGE', () => {
    const unclassified = [...foundOrigins].filter((o) => !(o in EXTERNAL_ORIGIN_USAGE))
    expect(
      unclassified,
      `New external origin(s) in frontend/src: ${unclassified.join(', ')}. ` +
        'Classify each in EXTERNAL_ORIGIN_USAGE: the CSP directive it needs ' +
        "(then allow it in nginx.conf and pin it above), or 'exempt' if the page never fetches it."
    ).toEqual([])
  })

  it('EXTERNAL_ORIGIN_USAGE has no stale entries', () => {
    const stale = Object.keys(EXTERNAL_ORIGIN_USAGE).filter((o) => !foundOrigins.has(o))
    expect(stale, `Origin(s) no longer referenced in frontend/src: ${stale.join(', ')}`).toEqual([])
  })

  it('every origin the page connects to is allowed by its CSP directive', () => {
    for (const [origin, directive] of Object.entries(EXTERNAL_ORIGIN_USAGE)) {
      if (directive === 'exempt') continue
      expect(
        allowedBy(origin, directives[directive] ?? []),
        `${origin} is used from the page but missing from ${directive} in nginx.conf`
      ).toBe(true)
    }
  })
})
