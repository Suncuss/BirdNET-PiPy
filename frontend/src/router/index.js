import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import api from '@/services/api'
import { BASE } from '@/services/baseUrl'

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
  }
]

const router = createRouter({
  history: createWebHistory(BASE),
  routes
})

/**
 * Cache for the auth status response. Without this, every click on a
 * protected route fires a fresh /api/auth/status — a network roundtrip plus
 * three disk reads and two deep-copies on the server — before the lazy
 * route chunk even starts loading. Invalidated on login/logout/setup via
 * the 'auth:invalidate-cache' window event dispatched from useAuth.
 */
const AUTH_STATUS_TTL_MS = 30000
let authStatusCache = { value: null, expiresAt: 0 }

if (typeof window !== 'undefined') {
  window.addEventListener('auth:invalidate-cache', () => {
    authStatusCache = { value: null, expiresAt: 0 }
  })
}

/**
 * Check authentication status from API, with a short TTL cache.
 * @param {{force?: boolean}} [opts]
 * @returns {Promise<{authEnabled: boolean, authenticated: boolean, setupComplete: boolean, publicFeatures: string[], checkFailed: boolean}>}
 */
async function checkAuthStatus({ force = false } = {}) {
  const now = Date.now()
  if (!force && authStatusCache.value && authStatusCache.expiresAt > now) {
    return authStatusCache.value
  }
  try {
    const { data } = await api.get('/auth/status')
    const status = {
      authEnabled: data.auth_enabled,
      setupComplete: data.setup_complete,
      authenticated: data.authenticated,
      publicFeatures: data.public_features || [],
      checkFailed: false
    }
    authStatusCache = { value: status, expiresAt: now + AUTH_STATUS_TTL_MS }
    return status
  } catch (error) {
    console.error('Failed to check auth status:', error)
  }
  // Fail-closed: assume auth is required and user is not authenticated
  // This prevents unauthorized access when API is unreachable. Do not
  // cache failures — we want the next click to retry immediately.
  return { authEnabled: true, authenticated: false, setupComplete: true, publicFeatures: [], checkFailed: true }
}

// Navigation guard for protected routes
router.beforeEach(async (to, from, next) => {
  // Only check auth for routes that require it
  if (to.meta.requiresAuth) {
    const status = await checkAuthStatus()

    if (!status.authEnabled) {
      // Auth disabled, allow access
      next()
    } else if (to.meta.feature && status.publicFeatures.includes(to.meta.feature)) {
      // Feature is configured as publicly accessible
      next()
    } else if (!status.authenticated) {
      // Need to login - stay on current page and show login modal
      sessionStorage.setItem('authRedirect', to.fullPath)
      next(false)
      window.dispatchEvent(new Event('auth:required'))
    } else {
      // Authenticated, allow access
      next()
    }
  } else {
    next()
  }
})

export default router
