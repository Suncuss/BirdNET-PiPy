/**
 * Contract test for how fast nginx gives up on a missing upstream
 * (frontend/nginx.conf).
 *
 * A native update removes the api container while nginx keeps running. For
 * the first ~45s nginx still holds an ARP entry for the old address, so
 * connects are black-holed and hang for the full proxy_connect_timeout — 60s
 * by default, which outlasts the SPA's 15s request timeout and leaves the
 * page on "Fetching data…" instead of the update overlay.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const conf = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '../../nginx.conf'), 'utf8'
)
const directives = [...conf.matchAll(/^([ \t]*)proxy_connect_timeout\s+(\d+)s;/gm)]

describe('nginx upstream connect timeout contract', () => {
  it('bounds the connect to a few seconds', () => {
    expect(directives).toHaveLength(1)
    expect(Number(directives[0][2])).toBeLessThanOrEqual(5)
  })

  it('sets it once at server level — covers every proxied location, and the HA add-on ingress clone (everything from "server {" down) keeps it', () => {
    const [match] = directives
    expect(match.index).toBeGreaterThan(conf.indexOf('\nserver {'))
    // Server-level directives sit one indent in; location-level sit two
    expect(match[1]).toBe('    ')
  })
})
