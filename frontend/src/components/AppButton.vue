<template>
  <component
    :is="to ? 'router-link' : 'button'"
    :to="to"
    :disabled="isDisabled"
    :class="buttonClasses"
    v-bind="$attrs"
  >
    <slot>{{ loading ? loadingText : label }}</slot>
  </component>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'secondary'].includes(v)
  },
  size: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'row'].includes(v)
  },
  disabled: Boolean,
  loading: Boolean,
  label: {
    type: String,
    default: undefined
  },
  loadingText: {
    type: String,
    default: 'Loading...'
  },
  to: {
    type: [String, Object],
    default: undefined
  }
})

const isDisabled = computed(() => props.disabled || props.loading)

const baseClasses = 'inline-block font-medium rounded-lg transition-all duration-200 text-sm'

const variantClasses = {
  primary: 'bg-blue-600 hover:bg-blue-700 text-white shadow focus:outline-none focus:ring-2 focus:ring-blue-300',
  secondary: 'text-gray-600 hover:text-gray-800 hover:bg-gray-100'
}

const sizeClasses = {
  default: 'py-2 px-4',
  row: 'h-9 px-3 flex items-center justify-center'
}

const disabledClasses = {
  primary: 'disabled:bg-gray-400 disabled:cursor-not-allowed',
  secondary: 'disabled:text-gray-400 disabled:cursor-not-allowed disabled:hover:bg-transparent'
}

const buttonClasses = computed(() => [
  baseClasses,
  variantClasses[props.variant],
  sizeClasses[props.size],
  disabledClasses[props.variant]
])
</script>
