<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <path d="M6 18L18 6M6 6l12 12" />
  </svg>
</template>

<script setup>
defineProps({
  strokeWidth: {
    type: [Number, String],
    default: 2
  }
})
</script>
