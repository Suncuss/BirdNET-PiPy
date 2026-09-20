import { vi } from 'vitest'

// Controllable matchMedia stub for useTallViewport, which reads .matches at
// setup and listens for 'change' — dispatch() drives a tier flip. Undo with
// vi.unstubAllGlobals().
export const stubViewportTier = (matches) => {
  const listeners = new Set()
  const mql = {
    matches,
    addEventListener: (_, fn) => listeners.add(fn),
    removeEventListener: (_, fn) => listeners.delete(fn),
    dispatch (next) {
      this.matches = next
      listeners.forEach(fn => fn({ matches: next }))
    },
    get listenerCount () { return listeners.size }
  }
  vi.stubGlobal('matchMedia', vi.fn(() => mql))
  return mql
}
