/**
 * Contract tests for the Content-Security-Policy nginx serves the SPA under
 * (frontend/nginx.conf). The policy is hand-written; these pin the allowances
 * known runtime consumers depend on, so a future tightening fails HERE with a
 * named consumer instead of silently breaking a browser-only code path.
 *
 * Why this exists: nothing in the JS test suite executes under nginx's
 * header, so CSP breakage is invisible to unit tests — 0.8.2 shipped
 * `script-src 'self'` and silently killed the Live Feed's Safari WASM
 * decoder (no live spectrogram on Safari/iOS, degraded fallback).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
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

  it('style-src allows inline styles — Vue :style bindings throughout the app', () => {
    expect(directives['style-src']).toContain("'unsafe-inline'")
  })

  it('media-src and worker-src allow blob: — generated audio/worker resources', () => {
    expect(directives['media-src']).toContain('blob:')
    expect(directives['worker-src']).toContain('blob:')
  })
})
