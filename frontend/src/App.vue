<template>
  <div class="min-h-screen bg-gray-100">
    <nav class="bg-green-700 text-white p-4">
      <div class="container mx-auto">
        <router-link to="/" class="text-2xl font-bold mb-4 hover:text-green-200 block">{{ DISPLAY_NAME }}</router-link>
        <div class="flex flex-wrap gap-4">
          <router-link to="/" class="hover:text-green-200">Dashboard</router-link>
          <router-link to="/gallery" class="hover:text-green-200">Bird Gallery</router-link>
          <router-link to="/live" class="hover:text-green-200">Live Feed</router-link>
          <router-link to="/charts" class="hover:text-green-200">Charts</router-link>
          <router-link to="/settings" class="hover:text-green-200">Settings</router-link>
        </div>
      </div>
    </nav>

    <main class="container mx-auto p-1">
      <router-view></router-view>
    </main>

    <!-- Location Setup Modal -->
    <LocationSetupModal
      :isVisible="showLocationSetup"
      @close="showLocationSetup = false"
      @location-saved="onLocationSaved"
    />
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useLogger } from '@/composables/useLogger'
import { DISPLAY_NAME } from './version'
import LocationSetupModal from '@/components/LocationSetupModal.vue'

export default {
  name: 'App',
  components: {
    LocationSetupModal
  },
  setup() {
    const logger = useLogger('App')
    const showLocationSetup = ref(false)

    const checkLocationSetup = async () => {
      try {
        const response = await fetch('/api/settings')
        if (response.ok) {
          const settings = await response.json()
          // Show setup modal if location has not been configured
          if (!settings.location?.configured) {
            logger.info('Location not configured, showing setup modal')
            showLocationSetup.value = true
          }
        }
      } catch (error) {
        logger.error('Failed to check location setup', { error: error.message })
      }
    }

    const onLocationSaved = (location) => {
      logger.info('Location saved', location)
    }

    onMounted(() => {
      logger.info('Application mounted')
      logger.debug('Environment', {
        mode: import.meta.env.MODE,
        dev: import.meta.env.DEV,
        prod: import.meta.env.PROD
      })
      // Check if location setup is needed
      checkLocationSetup()
    })

    return {
      DISPLAY_NAME,
      showLocationSetup,
      onLocationSaved
    }
  }
}
</script>