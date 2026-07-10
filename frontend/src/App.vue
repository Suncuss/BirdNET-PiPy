<template>
  <div class="min-h-screen bg-gray-100">
    <nav class="bg-green-700 text-white p-4">
      <div class="container mx-auto">
        <div class="flex items-center justify-between mb-2">
          <router-link
            to="/"
            class="hover:text-green-200 flex items-baseline gap-2"
          >
            <span class="text-2xl font-bold">{{ DISPLAY_NAME }}</span>
            <span
              v-if="stationName"
              class="text-base font-normal text-green-200"
            >
              {{ stationName }}
            </span>
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
          <button
            v-else-if="auth.needsLogin.value"
            class="text-sm text-green-200 hover:text-white flex items-center gap-1"
            title="Log in"
            @click="showLoginModal = true"
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
                d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9"
              />
            </svg>
            Login
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
      <router-view v-slot="{ Component }">
        <keep-alive :include="['Dashboard', 'BirdGallery']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </main>

    <!-- Status FAB — recorder warning takes priority over update; hidden on
         Settings and while a page-level scroll-to-top button occupies the corner -->
    <router-link
      v-if="recorderHealth.showRecorderWarning.value && statusFabAllowed"
      to="/settings"
      class="fixed bottom-4 right-4 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-full shadow-lg hidden md:flex items-center gap-2 z-50 transition-colors"
      title="Audio recording issues detected"
      @click="handleRecorderWarningClick"
    >
      <WarningIcon class="w-5 h-5" />
      <span class="text-sm font-medium">Audio Recording Issues</span>
    </router-link>
    <router-link
      v-else-if="systemUpdate.showUpdateIndicator.value && statusFabAllowed"
      to="/settings"
      class="fixed bottom-4 right-4 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-full shadow-lg hidden md:flex items-center gap-2 z-50 transition-colors"
      title="System update available"
    >
      <svg
        class="w-5 h-5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M5 10l7-7 7 7M12 3v18"
        />
      </svg>
      <span class="text-sm font-medium">Update Available</span>
    </router-link>

    <!-- Setup Wizard -->
    <SetupWizard
      :is-visible="showSetupWizard"
    />

    <!-- Login Modal -->
    <LoginModal
      :is-visible="showLoginModal"
      @success="onLoginSuccess"
      @cancel="onLoginCancel"
    />

    <WelcomeOverlay
      v-if="showWelcome"
      @done="showWelcome = false"
    />
  </div>
</template>

<script>
import { ref, computed, nextTick, watchEffect, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLogger } from '@/composables/useLogger'
import { useAuth } from '@/composables/useAuth'
import { useSettings } from '@/composables/useSettings'
import { useAppStatus } from '@/composables/useAppStatus'
import { useSystemUpdate } from '@/composables/useSystemUpdate'
import { useRecorderHealth } from '@/composables/useRecorderHealth'
import { useScrollToTop } from '@/composables/useScrollToTop'
import { DISPLAY_NAME } from './version'
import SetupWizard from '@/components/SetupWizard.vue'
import LoginModal from '@/components/LoginModal.vue'
import WelcomeOverlay from '@/components/WelcomeOverlay.vue'
import WarningIcon from '@/components/icons/WarningIcon.vue'
import { WELCOME_PENDING_KEY } from '@/utils/storageKeys'

export default {
  name: 'App',
  components: {
    SetupWizard,
    LoginModal,
    WelcomeOverlay,
    WarningIcon
  },
  setup() {
    const logger = useLogger('App')
    const route = useRoute()
    const router = useRouter()
    const auth = useAuth()
    const appSettings = useSettings()
    const { stationName, setStationName, locationConfigured, setLocationConfigured } = useAppStatus()
    const systemUpdate = useSystemUpdate()
    const recorderHealth = useRecorderHealth()
    const scrollToTop = useScrollToTop()

    // Whether the global status FABs may occupy the bottom-right corner: not on
    // Settings, and not while a page-level scroll-to-top button claims it.
    const statusFabAllowed = computed(
      () => route.name !== 'Settings' && !scrollToTop.isVisible.value
    )

    const showSetupWizard = ref(false)
    const showLoginModal = ref(false)
    const showWelcome = ref(sessionStorage.getItem(WELCOME_PENDING_KEY) === '1')
    if (showWelcome.value) {
      sessionStorage.removeItem(WELCOME_PENDING_KEY)
    }

    // Update browser tab title when station name changes
    watchEffect(() => {
      document.title = stationName.value ? `${DISPLAY_NAME} — ${stationName.value}` : DISPLAY_NAME
    })

    // Retry a failed bootstrap /settings load with backoff. Without this,
    // one timeout on a busy station left locationConfigured null forever
    // and the dashboard never started fetching (eternal spinners).
    const SETTINGS_RETRY_BASE_MS = 10000
    const SETTINGS_RETRY_MAX_MS = 60000
    let settingsRetryTimer = null
    let settingsRetryDelay = SETTINGS_RETRY_BASE_MS

    const cancelSettingsRetry = () => {
      if (settingsRetryTimer) {
        clearTimeout(settingsRetryTimer)
        settingsRetryTimer = null
      }
      settingsRetryDelay = SETTINGS_RETRY_BASE_MS
    }

    const scheduleSettingsRetry = () => {
      if (settingsRetryTimer) return
      settingsRetryTimer = setTimeout(() => {
        settingsRetryTimer = null
        checkLocationSetup()
      }, settingsRetryDelay)
      settingsRetryDelay = Math.min(settingsRetryDelay * 2, SETTINGS_RETRY_MAX_MS)
    }

    const checkLocationSetup = async () => {
      // useSettings owns the fetch and syncs unit / time-format prefs.
      const ok = await appSettings.ensureLoaded()
      if (!ok) {
        // A network error says nothing about whether location is configured.
        // Assume the common case (configured) so the dashboard starts
        // fetching — its data doesn't need settings and it shows its own
        // error states — and retry so prefs eventually sync and a genuinely
        // unconfigured station still gets the setup wizard.
        logger.error('Failed to check location setup')
        if (locationConfigured.value === null) {
          setLocationConfigured(true)
        }
        // When login is the known blocker (401s, not a down server) polling
        // is pointless — onLoginSuccess re-runs this after the user signs in.
        if (!auth.needsLogin.value) {
          scheduleSettingsRetry()
        }
        return
      }
      cancelSettingsRetry()
      const settings = appSettings.settings.value
      setStationName(settings?.display?.station_name)
      // Show setup modal if location has not been configured
      if (!settings?.location?.configured) {
        logger.info('Location not configured, showing setup wizard')
        setLocationConfigured(false)
        showSetupWizard.value = true
      } else {
        setLocationConfigured(true)
      }
    }

    // Handle 401 auth required events from API interceptor
    const handleAuthRequired = async () => {
      logger.info('Auth required event received')
      await auth.checkAuthStatus()
      if (auth.needsLogin.value) {
        // The server is up and answering 401s — login is the recovery path
        // now; a pending settings retry would only re-trigger this event.
        cancelSettingsRetry()
        showLoginModal.value = true
      }
    }

    const onLoginSuccess = async () => {
      showLoginModal.value = false
      logger.info('Login successful')

      // Load settings (including unit preference) after login
      await checkLocationSetup()
      recorderHealth.checkStatus()

      // Redirect to stored destination if any
      const redirect = sessionStorage.getItem('authRedirect')
      if (redirect) {
        sessionStorage.removeItem('authRedirect')
        router.push(redirect)
      }
    }

    const onLoginCancel = () => {
      showLoginModal.value = false
      sessionStorage.removeItem('authRedirect')
      logger.info('Login cancelled')
    }

    const handleLogout = async () => {
      await auth.logout()
      // If on a protected page, redirect to dashboard (unless the feature is public)
      if (route.meta.requiresAuth) {
        const feature = route.meta.feature
        const isPublic = feature && auth.authStatus.value.publicFeatures.includes(feature)
        if (!isPublic) {
          router.push('/')
        }
      }
    }

    // Defer dismiss so router-link navigation completes before the v-if removes the element.
    const handleRecorderWarningClick = () => {
      nextTick(() => recorderHealth.dismissWarning())
    }

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

      // Ensure auth status is loaded (shares the one-time load with the
      // router guard — see useAuth.ensureAuthLoaded)
      await auth.ensureAuthLoaded()

      // Check if location setup is needed
      if (auth.needsLogin.value) {
        // Auth enabled means initial setup (including location) was already done
        // Allow dashboard to work without login (public access)
        setLocationConfigured(true)
        // Station name from public auth endpoint (settings endpoint requires login)
        setStationName(auth.authStatus.value.stationName)
      } else {
        checkLocationSetup()
      }

      // Silent checks for status indicators
      systemUpdate.checkForUpdates({ silent: true }).catch(() => {})
      if (!auth.needsLogin.value) {
        recorderHealth.checkStatus()
      }
    })

    onUnmounted(() => {
      window.removeEventListener('auth:required', handleAuthRequired)
      cancelSettingsRetry()
    })

    return {
      DISPLAY_NAME,
      showSetupWizard,
      showLoginModal,
      showWelcome,
      onLoginSuccess,
      onLoginCancel,
      handleLogout,
      handleRecorderWarningClick,
      auth,
      stationName,
      systemUpdate,
      recorderHealth,
      statusFabAllowed
    }
  }
}
</script>
