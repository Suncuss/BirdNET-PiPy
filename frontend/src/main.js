import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import { setupGlobalErrorHandler, useLogger } from './composables/useLogger'
import { VERSION, DISPLAY_NAME } from './version'

// PrimeVue
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'

// Setup global error handling
setupGlobalErrorHandler()

const app = createApp(App)
const logger = useLogger('Main')

// Log app initialization
logger.info(`Initializing ${DISPLAY_NAME} v${VERSION}`)

// Vue error handler
app.config.errorHandler = (err, instance, info) => {
  logger.error('Vue error', {
    error: err,
    componentInfo: info,
    componentName: instance?.$options?.name || 'Unknown'
  })
}

// Vue warning handler (development only)
if (import.meta.env.DEV) {
  app.config.warnHandler = (msg, instance, trace) => {
    logger.warn('Vue warning', {
      message: msg,
      componentName: instance?.$options?.name || 'Unknown',
      trace
    })
  }
}

app.use(router)
app.use(PrimeVue, {
    theme: {
        preset: Aura,
        options: {
            darkModeSelector: false // Disable dark mode
        }
    }
})

app.mount('#app')

logger.info('Application mounted successfully')