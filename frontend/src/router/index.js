import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import { BASE } from '@/services/baseUrl'
import { useAuth } from '@/composables/useAuth'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/gallery',
    name: 'BirdGallery',
    component: () => import('../views/BirdGallery.vue')
  },
  {
    path: '/live',
    name: 'LiveFeed',
    component: () => import('../views/LiveFeed.vue'),
    meta: { requiresAuth: true, feature: 'live_feed' }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/charts',
    name: 'Charts',
    component: () => import('../views/Charts.vue'),
    meta: { requiresAuth: true, feature: 'charts' }
  },
  {
    path: '/table',
    name: 'Table',
    component: () => import('../views/Table.vue'),
    meta: { requiresAuth: true, feature: 'table' }
  },
  {
    path: '/bird/:name',
    name: 'BirdDetails',
    component: () => import('../views/BirdDetails.vue')
  },
  {
    // Detection Detail — the deep-dive page a share link opens: an on-the-fly
    // spectrogram (faithful playhead) plus live, non-destructive listening tools
    // (high-pass, gain). Route name kept as 'BirdRecording' so existing
    // permalinks/links are unaffected.
    path: '/bird/:name/recording/:id',
    name: 'BirdRecording',
    component: () => import('../views/DetectionDetail.vue')
  }
]

const router = createRouter({
  history: createWebHistory(BASE),
  routes
})

// A deploy replaces every hashed chunk, so a tab loaded before an update
// fails its next lazy route import and the click dies silently. Recover with
// a full page load of the intended route — that picks up the new index.html
// and its chunk names. Matched by message because each browser words the
// TypeError differently (Chrome/Firefox/Safari), plus Vite's CSS-preload
// failure for the same root cause.
const STALE_CHUNK_RE = /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|unable to preload css/i
const RELOAD_GUARD_KEY = 'staleChunkReloadAt'
const RELOAD_GUARD_MS = 10000

export function recoverFromStaleChunk(error, to) {
  if (!STALE_CHUNK_RE.test(error?.message || '')) return false
  // If a fresh page failed the same import moments ago, the build itself is
  // broken — surface the error instead of looping reloads.
  const lastReload = Number(sessionStorage.getItem(RELOAD_GUARD_KEY)) || 0
  if (Date.now() - lastReload < RELOAD_GUARD_MS) return false
  sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
  window.location.assign(router.resolve(to.fullPath).href)
  return true
}

router.onError(recoverFromStaleChunk)

// Shared auth state — the single source of truth, kept current by every
// mutation in useAuth. The guard reads it; it keeps no copy of its own.
// This runs at module load, so useAuth() must stay free of component-
// lifecycle calls (onMounted / inject / getCurrentInstance).
const { authStatus, ensureAuthLoaded } = useAuth()

/**
 * Navigation guard for protected routes.
 *
 * The guard decides from the shared auth state and issues no fetch of its
 * own. ensureAuthLoaded() does at most one /auth/status load for the whole
 * app lifetime — the first protected navigation (or App startup, whichever
 * is first) pays for it; every later navigation awaits an already-resolved
 * promise and never touches the network.
 *
 * It fails *open* — if auth state cannot be determined, navigation is
 * allowed. This is not a security hole: the backend enforces auth on every
 * protected endpoint (401 -> login modal via the api response interceptor).
 * The client guard only decides whether to prompt before or after a
 * navigation that, unauthenticated, would render an empty shell anyway.
 */
router.beforeEach(async (to, from, next) => {
  if (!to.meta.requiresAuth) return next()

  await ensureAuthLoaded()
  const status = authStatus.value

  if (!status.authEnabled) return next()
  if (to.meta.feature && status.publicFeatures.includes(to.meta.feature)) return next()
  if (!status.authenticated) {
    sessionStorage.setItem('authRedirect', to.fullPath)
    window.dispatchEvent(new Event('auth:required'))
    return next(false)
  }
  return next()
})

export default router
