import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'

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
    meta: { requiresAuth: true }
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
    component: () => import('../views/Charts.vue')
  },
  {
    path: '/table',
    name: 'Table',
    component: () => import('../views/Table.vue')
  },
  {
    path: '/bird/:name',
    name: 'BirdDetails',
    component: () => import('../views/BirdDetails.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

/**
 * Check authentication status from API
 * @returns {Promise<{authEnabled: boolean, authenticated: boolean, setupComplete: boolean, checkFailed: boolean}>}
 */
async function checkAuthStatus() {
  try {
    const response = await fetch('/api/auth/status')
    if (response.ok) {
      const data = await response.json()
      return {
        authEnabled: data.auth_enabled,
        setupComplete: data.setup_complete,
        authenticated: data.authenticated,
        checkFailed: false
      }
    }
  } catch (error) {
    console.error('Failed to check auth status:', error)
  }
  // Fail-closed: assume auth is required and user is not authenticated
  // This prevents unauthorized access when API is unreachable
  return { authEnabled: true, authenticated: false, setupComplete: true, checkFailed: true }
}

// Navigation guard for protected routes
router.beforeEach(async (to, from, next) => {
  // Only check auth for routes that require it
  if (to.meta.requiresAuth) {
    const status = await checkAuthStatus()

    if (!status.authEnabled) {
      // Auth disabled, allow access
      next()
    } else if (!status.authenticated) {
      // Need to login - store intended destination and redirect
      sessionStorage.setItem('authRedirect', to.fullPath)
      next({ name: 'Dashboard', query: { auth: 'required' } })
    } else {
      // Authenticated, allow access
      next()
    }
  } else {
    next()
  }
})

export default router
