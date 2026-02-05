<template>
  <div
    v-if="message"
    :class="[
      'mb-4 p-3 rounded-lg border',
      variantClasses.bg,
      variantClasses.border
    ]"
  >
    <div class="flex items-center justify-between">
      <div :class="['flex items-center gap-2 text-sm', variantClasses.text]">
        <!-- Warning icon -->
        <svg
          class="h-4 w-4 flex-shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>
        <span>{{ message }}</span>
      </div>
      <button
        v-if="dismissible"
        :class="['text-sm underline', variantClasses.button]"
        @click="dismiss"
      >
        Dismiss
      </button>
    </div>
  </div>
</template>

<script>
import { computed, watch, onUnmounted } from 'vue'

export default {
  name: 'AlertBanner',
  props: {
    message: {
      type: String,
      default: ''
    },
    variant: {
      type: String,
      default: 'warning',
      validator: (value) => ['warning', 'error'].includes(value)
    },
    dismissible: {
      type: Boolean,
      default: true
    },
    autoDismiss: {
      type: Number,
      default: 15000 // 15 seconds, 0 to disable
    }
  },
  emits: ['dismiss'],
  setup(props, { emit }) {
    let dismissTimer = null

    const variantClasses = computed(() => {
      const variants = {
        warning: {
          bg: 'bg-amber-50',
          border: 'border-amber-200',
          text: 'text-amber-700',
          button: 'text-amber-700 hover:text-amber-900'
        },
        error: {
          bg: 'bg-red-50',
          border: 'border-red-200',
          text: 'text-red-700',
          button: 'text-red-700 hover:text-red-900'
        }
      }
      return variants[props.variant]
    })

    const clearTimer = () => {
      if (dismissTimer) {
        clearTimeout(dismissTimer)
        dismissTimer = null
      }
    }

    const dismiss = () => {
      clearTimer()
      emit('dismiss')
    }

    // Auto-dismiss when message appears
    watch(() => props.message, (newMessage) => {
      clearTimer()
      if (newMessage && props.autoDismiss > 0) {
        dismissTimer = setTimeout(() => {
          emit('dismiss')
        }, props.autoDismiss)
      }
    }, { immediate: true })

    onUnmounted(() => {
      clearTimer()
    })

    return {
      variantClasses,
      dismiss
    }
  }
}
</script>
