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
  </div>
</template>

<script>
import { onMounted } from 'vue'
import { useLogger } from '@/composables/useLogger'
import { DISPLAY_NAME } from './version'

export default {
  name: 'App',
  setup() {
    const logger = useLogger('App')

    onMounted(() => {
      logger.info('Application mounted')
      logger.debug('Environment', {
        mode: import.meta.env.MODE,
        dev: import.meta.env.DEV,
        prod: import.meta.env.PROD
      })
    })

    return {
      DISPLAY_NAME
    }
  }
}
</script>