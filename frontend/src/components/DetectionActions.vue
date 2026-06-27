<template>
  <div
    class="flex items-center gap-0.5"
    :class="containerClass"
  >
    <button
      type="button"
      class="p-1.5 text-blue-500 hover:text-blue-700 disabled:opacity-50"
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
      class="p-1.5 text-green-600 hover:text-green-700 disabled:opacity-50"
      title="View spectrogram"
      :disabled="disabled"
      @click="$emit('spectrogram', detection)"
    >
      <SpectrogramIcon class="h-4 w-4" />
    </button>
    <!-- Real link to the standalone detail page so ⌘/Ctrl/middle-click opens it
         in a new tab; a plain click opens the in-place modal instead (no nav). -->
    <a
      :href="detailHref"
      class="inline-flex items-center p-1.5 text-green-600 hover:text-green-700"
      :class="{ 'pointer-events-none opacity-50': disabled }"
      title="Detection info"
      @click="onInfoClick"
    >
      <font-awesome-icon
        :icon="['fas', 'circle-info']"
        class="h-4 w-4"
      />
    </a>
    <button
      v-if="!hideDelete"
      type="button"
      class="p-1.5 text-red-400 hover:text-red-600 disabled:opacity-50"
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
import { computed } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import SpectrogramIcon from '@/components/icons/SpectrogramIcon.vue'
import { recordingPath } from '@/utils/detectionLinks'

library.add(faCircleInfo)

const props = defineProps({
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
  },
  hideDelete: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-play', 'spectrogram', 'show-detail', 'delete'])

// Permalink to the standalone detail page (the BirdRecording route). Uses the
// shared path helper rather than the router so this stays a plain presentational
// component.
const detailHref = computed(() =>
  recordingPath(props.detection.common_name, props.detection.id)
)

const onInfoClick = (event) => {
  // Let modified clicks fall through to the real link (open in a new tab/window).
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  emit('show-detail', props.detection)
}
</script>
