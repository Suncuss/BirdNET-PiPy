// A promise we settle by hand, so we can assert on the in-flight UI before
// the request resolves (or rejects). Pre-attaches a noop catch so a manual
// reject() doesn't trigger unhandled-rejection warnings — awaiters still
// see the rejection.
export const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  promise.catch(() => {})
  return { promise, resolve, reject }
}
