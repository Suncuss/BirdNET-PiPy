<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition ease-out duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition ease-in duration-150"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="isVisible"
        class="fixed inset-0 z-50 overflow-y-auto"
      >
        <!-- Backdrop (visual only — it sits under the centering container below,
             which is what actually receives outside-clicks) -->
        <div class="fixed inset-0 bg-black/60" />
        <!-- Centering container (scrolls when the card is taller than the viewport).
             @click.self closes on a click in the empty area around the card, but
             not on clicks that bubble up from the card itself. -->
        <div
          class="relative min-h-full flex items-center justify-center p-4"
          @click.self="requestDismiss"
        >
          <div class="relative w-full max-w-[1120px]">
            <!-- Close button (outside the top-right corner, matching SpectrogramModal) -->
            <button
              type="button"
              class="absolute -top-2 -right-2 sm:-top-3 sm:-right-3 z-10 p-1 sm:p-1.5 rounded-full bg-gray-800 text-gray-200 hover:bg-gray-700 hover:text-white transition-colors focus:outline-none shadow-lg"
              title="Close"
              @click="requestDismiss"
            >
              <CloseIcon
                class="h-4 w-4 sm:h-5 sm:w-5"
                :stroke-width="2.5"
              />
            </button>
            <div class="bg-white rounded-2xl shadow-xl overflow-hidden">
              <!-- key on name+id so reopening for a different detection remounts
                   the player cleanly (fresh fetch + audio graph). -->
              <DetectionPlayer
                :id="id"
                :key="`${name}-${id}`"
                :name="name"
              />
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import DetectionPlayer from '@/components/DetectionPlayer.vue'
import CloseIcon from '@/components/icons/CloseIcon.vue'
import { useModalDismiss } from '@/composables/useModalDismiss'

const props = defineProps({
  isVisible: {
    type: Boolean,
    default: false
  },
  name: {
    type: String,
    default: ''
  },
  id: {
    type: [String, Number],
    default: null
  }
})
const emit = defineEmits(['close'])

const { requestDismiss } = useModalDismiss(
  () => props.isVisible,
  () => emit('close')
)

// Links inside the player (species names → bird page) navigate the page UNDER
// the overlay — the modal doesn't own the route, so a route change while open
// must dismiss it or it lingers over the destination page.
const route = useRoute()
watch(() => route.fullPath, () => {
  if (props.isVisible) emit('close')
})
</script>
