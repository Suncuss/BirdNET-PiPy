<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-100">
    <button
      class="w-full p-5 flex items-center justify-between text-left hover:bg-gray-50 transition-colors rounded-lg"
      @click="expanded = !expanded"
    >
      <div>
        <h2 class="text-base font-medium text-gray-800">
          {{ title }}
        </h2>
        <p class="text-xs text-gray-400 mt-0.5">
          {{ subtitle }}
        </p>
      </div>
      <svg
        class="w-5 h-5 text-gray-400 transition-transform duration-200"
        :class="{ 'rotate-180': expanded }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M19 9l-7 7-7-7"
        />
      </svg>
    </button>

    <div
      v-show="expanded"
      :class="bodyClass"
    >
      <slot />
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'

export default {
  name: 'CollapsibleSection',
  props: {
    title: {
      type: String,
      required: true
    },
    subtitle: {
      type: String,
      required: true
    },
    bodyClass: {
      type: String,
      default: 'border-t border-gray-100 p-5'
    }
  },
  setup() {
    const expanded = ref(false)
    return { expanded }
  }
}
</script>
