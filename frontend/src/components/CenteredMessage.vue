<template>
  <div :class="['flex items-center justify-center', containerClass]">
    <p :class="textClass">
      <slot />
    </p>
  </div>
</template>

<script>
const variantStyles = {
  loading: 'text-lg text-gray-400',
  error: 'text-lg text-gray-500',
  info: 'text-lg text-gray-500'
}

export default {
  name: 'CenteredMessage',
  props: {
    variant: {
      type: String,
      default: 'info',
      validator: (v) => v in variantStyles
    },
    containerClass: {
      type: String,
      default: ''
    }
  },
  computed: {
    textClass() {
      return variantStyles[this.variant]
    }
  }
}
</script>
