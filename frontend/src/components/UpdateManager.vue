<template>
  <div class="update-manager p-4 bg-gray-50 rounded-lg">
    <h3 class="text-lg font-semibold mb-4">System Updates</h3>
    
    <!-- Check for Updates Button -->
    <div v-if="!updateInfo" class="mb-4">
      <button 
        @click="checkForUpdates" 
        :disabled="checking"
        class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:opacity-50"
      >
        {{ checking ? 'Checking...' : 'Check for Updates' }}
      </button>
    </div>
    
    <!-- Update Status -->
    <div v-if="updateInfo" class="space-y-4">
      <!-- Current Version -->
      <div class="text-sm">
        <span class="font-medium">Current Version:</span> 
        <code class="bg-gray-200 px-2 py-1 rounded">{{ updateInfo.current_tag || updateInfo.current_version }}</code>
      </div>
      
      <!-- Update Available -->
      <div v-if="updateInfo.update_available" class="bg-yellow-50 border border-yellow-200 p-4 rounded">
        <h4 class="font-medium text-yellow-800 mb-2">Update Available!</h4>
        <div class="text-sm text-gray-700 mb-2">
          <span class="font-medium">New Version:</span> 
          <code class="bg-yellow-100 px-2 py-1 rounded">{{ updateInfo.remote_tag || updateInfo.remote_version }}</code>
        </div>
        
        <!-- Changes List -->
        <div v-if="updateInfo.changes && updateInfo.changes.length > 0" class="mb-3">
          <p class="text-sm font-medium text-gray-700 mb-1">Changes:</p>
          <ul class="text-sm text-gray-600 list-disc list-inside space-y-1">
            <li v-for="change in updateInfo.changes.slice(0, 5)" :key="change">
              {{ change }}
            </li>
            <li v-if="updateInfo.changes.length > 5" class="text-gray-400">
              ... and {{ updateInfo.changes.length - 5 }} more
            </li>
          </ul>
        </div>
        
        <!-- Update Actions -->
        <div class="flex space-x-2 mt-4">
          <button 
            @click="applyUpdate" 
            :disabled="updating"
            class="bg-green-600 hover:bg-green-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-green-300 text-sm disabled:opacity-50"
          >
            {{ updating ? 'Updating...' : 'Apply Update' }}
          </button>
          <button 
            @click="dismissUpdate"
            class="bg-gray-600 hover:bg-gray-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-gray-300 text-sm"
          >
            Later
          </button>
        </div>
      </div>
      
      <!-- No Updates -->
      <div v-else class="bg-green-50 border border-green-200 p-4 rounded">
        <p class="text-green-800">✓ System is up to date</p>
      </div>
    </div>
    
    <!-- Update Progress -->
    <div v-if="updateProgress" class="mt-4 bg-blue-50 border border-blue-200 p-4 rounded">
      <div class="flex items-center">
        <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-3"></div>
        <span class="text-blue-800">{{ updateProgress }}</span>
      </div>
    </div>
    
    <!-- Error Message -->
    <div v-if="error" class="mt-4 bg-red-50 border border-red-200 p-4 rounded">
      <p class="text-red-800">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api, { createLongRequest } from '@/services/api'

const checking = ref(false)
const updating = ref(false)
const updateInfo = ref(null)
const updateProgress = ref('')
const error = ref('')

const checkForUpdates = async () => {
  checking.value = true
  error.value = ''

  try {
    const { data } = await api.get('/update/check')
    updateInfo.value = data
  } catch (err) {
    error.value = err.response?.data?.message || 'Failed to check for updates'
  } finally {
    checking.value = false
  }
}

const applyUpdate = async () => {
  if (!confirm('Apply update? The system will restart during the update process.')) {
    return
  }
  
  updating.value = true
  error.value = ''
  updateProgress.value = 'Downloading updates...'
  
  try {
    // Apply the update (use long timeout for update operation)
    updateProgress.value = 'Applying updates...'
    const longApi = createLongRequest()
    const { data } = await longApi.post('/update/apply')

    if (data.status === 'success') {
      updateProgress.value = 'Update complete! Reloading...'
      
      // Wait a moment for services to restart
      setTimeout(() => {
        window.location.reload()
      }, 3000)
    }
  } catch (err) {
    error.value = err.response?.data?.message || 'Failed to apply update'
    updateProgress.value = ''
  } finally {
    updating.value = false
  }
}

const dismissUpdate = () => {
  updateInfo.value = null
}

// Auto-check on component mount
checkForUpdates()
</script>