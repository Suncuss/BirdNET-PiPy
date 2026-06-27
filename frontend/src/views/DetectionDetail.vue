<template>
  <!-- Standalone detail page — what a share permalink (or any direct link) opens.
       The same content also appears as an in-app modal from the Detections table
       (see DetectionModal.vue); both wrap the shared DetectionPlayer. -->
  <div class="p-4 max-w-[1120px] mx-auto">
    <div class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      <DetectionPlayer
        :id="route.params.id"
        :name="route.params.name"
      >
        <template #not-found-action>
          <router-link
            :to="{ name: 'Dashboard' }"
            class="inline-flex items-center px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
          >
            Go to dashboard
          </router-link>
        </template>
      </DetectionPlayer>
    </div>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import DetectionPlayer from '@/components/DetectionPlayer.vue'

const route = useRoute()
</script>
