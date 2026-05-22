/**
 * Coalesces concurrent callers onto a single in-flight async load.
 *
 * The loader must resolve to a boolean; a falsy result is not retained, so
 * the next ensure() retries. A successful load is cached until reset().
 * Create one instance at module scope so the cached state is shared across
 * all callers of a composable.
 *
 * @returns {{
 *   ensure: (loader: () => Promise<boolean>) => Promise<boolean>,
 *   reset: () => void,
 *   markLoaded: () => void
 * }}
 */
export function createCoalescedLoader() {
  let promise = null

  return {
    /** Run `loader` once; concurrent and subsequent callers share the result. */
    ensure(loader) {
      if (!promise) {
        promise = loader().then((ok) => {
          if (!ok) promise = null
          return ok
        })
      }
      return promise
    },

    /** Discard the cached result so the next ensure() re-runs the loader. */
    reset() {
      promise = null
    },

    /** Mark as already loaded — a later ensure() will skip the loader. */
    markLoaded() {
      if (!promise) promise = Promise.resolve(true)
    }
  }
}
