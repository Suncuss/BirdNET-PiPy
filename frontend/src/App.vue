<template>
  <div class="min-h-screen bg-gray-100">
    <nav class="bg-green-700 text-white p-4">
      <div class="container mx-auto">
        <div class="flex items-center justify-between mb-4">
          <router-link
            to="/"
            class="text-2xl font-bold hover:text-green-200"
          >
            {{ DISPLAY_NAME }}
          </router-link>
          <!-- Auth indicator -->
          <button
            v-if="auth.authStatus.value.authEnabled && auth.authStatus.value.authenticated"
            class="text-sm text-green-200 hover:text-white flex items-center gap-1"
            title="Log out"
            @click="handleLogout"
          >
            <svg
              class="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75"
              />
            </svg>
            Logout
          </button>
        </div>
        <div class="flex flex-wrap gap-4">
          <router-link
            to="/"
            class="hover:text-green-200"
          >
            Dashboard
          </router-link>
          <router-link
            to="/gallery"
            class="hover:text-green-200"
          >
            Gallery
          </router-link>
          <router-link
            to="/live"
            class="hover:text-green-200"
          >
            Live Feed
          </router-link>
          <router-link
            to="/charts"
            class="hover:text-green-200"
          >
            Charts
          </router-link>
          <router-link
            to="/table"
            class="hover:text-green-200"
          >
            Table
          </router-link>
          <router-link
            to="/settings"
            class="hover:text-green-200"
          >
            Settings
          </router-link>
        </div>
      </div>
    </nav>

    <main class="container mx-auto p-1">
      <router-view />
    </main>

    <!-- Location Setup Modal -->
    <LocationSetupModal
      :is-visible="showLocationSetup"
      @close="showLocationSetup = false"
      @location-saved="onLocationSaved"
    />

    <!-- Login Modal -->
    <LoginModal
      :is-visible="showLoginModal"
      @success="onLoginSuccess"
      @cancel="onLoginCancel"
    />
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLogger } from '@/composables/useLogger'
import { useAuth } from '@/composables/useAuth'
import { useUnitSettings } from '@/composables/useUnitSettings'
import { useAppStatus } from '@/composables/useAppStatus'
import { DISPLAY_NAME } from './version'
import LocationSetupModal from '@/components/LocationSetupModal.vue'
import LoginModal from '@/components/LoginModal.vue'
import api from '@/services/api'

export default {
  name: 'App',
  components: {
    LocationSetupModal,
    LoginModal
  },
  setup() {
    const logger = useLogger('App')
    const route = useRoute()
    const router = useRouter()
    const auth = useAuth()
    const unitSettings = useUnitSettings()
    const appStatus = useAppStatus()

    const showLocationSetup = ref(false)
    const showLoginModal = ref(false)

    const checkLocationSetup = async () => {
      try {
        const { data: settings } = await api.get('/settings')
        // Sync unit preference from settings
        unitSettings.setUseMetricUnits(settings.display?.use_metric_units ?? true)
        // Show setup modal if location or timezone has not been configured
        if (!settings.location?.configured || !settings.location?.timezone) {
          logger.info('Location or timezone not configured, showing setup modal')
          appStatus.setLocationConfigured(false)
          showLocationSetup.value = true
        } else {
          appStatus.setLocationConfigured(true)
        }
      } catch (error) {
        logger.error('Failed to check location setup', { error: error.message })
        appStatus.setLocationConfigured(false)
      }
    }

    // Handle 401 auth required events from API interceptor
    const handleAuthRequired = async () => {
      logger.info('Auth required event received')
      await auth.checkAuthStatus()
      if (auth.needsLogin.value) {
        showLoginModal.value = true
      }
    }

    const onLocationSaved = (location) => {
      logger.info('Location saved', location)
    }

    const onLoginSuccess = async () => {
      showLoginModal.value = false
      logger.info('Login successful')

      // Load settings (including unit preference) after login
      await checkLocationSetup()

      // Redirect to stored destination if any
      const redirect = sessionStorage.getItem('authRedirect')
      if (redirect) {
        sessionStorage.removeItem('authRedirect')
        router.push(redirect)
      }
    }

    const onLoginCancel = () => {
      showLoginModal.value = false
      logger.info('Login cancelled')
    }

    const handleLogout = async () => {
      await auth.logout()
      // If on a protected page, redirect to dashboard
      if (route.meta.requiresAuth) {
        router.push('/')
      }
    }

    // Watch for auth requirement from router
    watch(
      () => route.query.auth,
      async (authQuery) => {
        if (authQuery === 'required') {
          // Refresh auth status and show login modal
          await auth.checkAuthStatus()
          if (auth.needsLogin.value) {
            showLoginModal.value = true
          }
          // Clear the query parameter
          router.replace({ query: {} })
        }
      },
      { immediate: true }
    )

    // Check auth status on mount
    onMounted(async () => {
      logger.info('Application mounted')
      logger.debug('Environment', {
        mode: import.meta.env.MODE,
        dev: import.meta.env.DEV,
        prod: import.meta.env.PROD
      })

      // Listen for auth required events from API interceptor
      window.addEventListener('auth:required', handleAuthRequired)

      // Check auth status
      await auth.checkAuthStatus()

      // Check if location setup is needed
      if (auth.needsLogin.value) {
        // Auth enabled means initial setup (including location) was already done
        // Allow dashboard to work without login (public access)
        appStatus.setLocationConfigured(true)
      } else {
        checkLocationSetup()
      }
    })

    onUnmounted(() => {
      window.removeEventListener('auth:required', handleAuthRequired)
    })

    return {
      DISPLAY_NAME,
      showLocationSetup,
      showLoginModal,
      onLocationSaved,
      onLoginSuccess,
      onLoginCancel,
      handleLogout,
      auth
    }
  }
}
</script>
