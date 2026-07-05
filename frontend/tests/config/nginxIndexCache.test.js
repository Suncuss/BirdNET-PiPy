/**
 * Contract test for how nginx caches the SPA entrypoint (frontend/nginx.conf).
 *
 * Hashed assets are immutable-cached for a year, which is only safe if
 * index.html itself is always revalidated — with no Cache-Control, browsers
 * heuristically cache it, and after an update a cached index.html points at
 * chunks that no longer exist ("Failed to fetch dynamically imported module").
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const conf = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '../../nginx.conf'), 'utf8'
)
const indexBlock = conf.match(/location = \/index\.html\s*\{([^}]*)\}/)?.[1]

describe('nginx index.html cache contract', () => {
  it('serves index.html with a negative expires (Cache-Control: no-cache)', () => {
    expect(indexBlock).toBeDefined()
    expect(indexBlock).toMatch(/expires\s+-1;/)
  })

  it('adds no headers in the block — a location-level add_header would drop the inherited server-level security headers (CSP etc.)', () => {
    expect(indexBlock).not.toMatch(/add_header/)
  })
})
