<template>
  <div class="bird-detection-list">
    <h2 class="text-lg font-semibold mb-2">
      Recent Detections
    </h2>
    <transition-group
      name="list"
      tag="ul"
      class="space-y-2"
    >
      <li
        v-for="detection in detections"
        :key="detection.common_name" 
        :class="[
          'p-3 bg-gray-100 rounded-lg border-l-4 border-green-500 transition-all duration-300 cursor-pointer hover:bg-gray-200 hover:shadow-md',
          detection.justUpdated ? '!bg-green-100 !border-l-green-600 shadow-[0_0_20px_rgba(34,197,94,0.3)] scale-[1.02]' : ''
        ]"
        @click="navigateToBirdDetails(detection.common_name)"
      >
        <div class="flex items-center justify-between">
          <div class="flex-grow">
            <div class="font-semibold text-gray-800">
              {{ detection.common_name }}
            </div>
            <div class="text-sm text-gray-600 italic">
              {{ detection.scientific_name }}
            </div>
          </div>
          <div class="text-right">
            <div class="text-lg font-bold text-green-600">
              {{ (detection.confidence * 100).toFixed(0) }}%
            </div>
            <div class="text-xs text-gray-500">
              {{ formatTime(detection.timestamp) }}
            </div>
          </div>
        </div>
      </li>
    </transition-group>
  </div>
</template>
  
  <script>
  import { defineComponent } from 'vue'
  import { useRouter } from 'vue-router'
  
  export default defineComponent({
    name: 'BirdDetectionList',
    props: {
      detections: {
        type: Array,
        required: true
      }
    },
    setup() {
      const router = useRouter()
      
      const formatTime = (timestamp) => {
        return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }
      
      const navigateToBirdDetails = (commonName) => {
        router.push({ name: 'BirdDetails', params: { name: commonName } })
      }
  
      return {
        formatTime,
        navigateToBirdDetails
      }
    }
  })
  </script>
  
  <style scoped>
  .list-enter-active,
  .list-leave-active {
    transition: all 0.5s ease;
  }
  .list-enter-from {
    opacity: 0;
    transform: translateY(-30px);
  }
  .list-leave-to {
    opacity: 0;
    transform: translateY(30px);
  }
  
  .list-move {
    transition: transform 0.5s ease;
  }
  </style>