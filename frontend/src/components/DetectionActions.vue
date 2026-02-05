<template>
  <div
    class="flex items-center gap-1"
    :class="containerClass"
  >
    <button
      type="button"
      class="p-2 text-blue-500 hover:text-blue-700 disabled:opacity-50"
      :title="isPlaying ? 'Pause' : 'Play'"
      :disabled="disabled"
      @click="$emit('toggle-play', detection)"
    >
      <font-awesome-icon
        :icon="isPlaying ? ['fas', 'pause'] : ['fas', 'play']"
        class="h-4 w-4"
      />
    </button>
    <button
      type="button"
      class="p-2 text-green-600 hover:text-green-700 disabled:opacity-50"
      title="View spectrogram"
      :disabled="disabled"
      @click="$emit('spectrogram', detection)"
    >
      <font-awesome-icon
        :icon="['fas', 'circle-info']"
        class="h-4 w-4"
      />
    </button>
    <button
      type="button"
      class="p-2 text-gray-500 hover:text-gray-700 disabled:opacity-50"
      title="Detection info"
      :disabled="disabled"
      @click="$emit('show-info', detection)"
    >
      <font-awesome-icon
        :icon="['fas', 'database']"
        class="h-4 w-4"
      />
    </button>
    <button
      type="button"
      class="p-2 text-red-400 hover:text-red-600 disabled:opacity-50"
      title="Delete"
      :disabled="disabled"
      @click="$emit('delete', detection)"
    >
      <font-awesome-icon
        :icon="['fas', 'trash-alt']"
        class="h-4 w-4"
      />
    </button>
  </div>
</template>

<script setup>
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

defineProps({
  detection: {
    type: Object,
    required: true
  },
  isPlaying: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  },
  containerClass: {
    type: String,
    default: ''
  }
})

defineEmits(['toggle-play', 'spectrogram', 'show-info', 'delete'])
</script>
