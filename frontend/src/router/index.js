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
