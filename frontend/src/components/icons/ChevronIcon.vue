<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <path :d="paths[direction]" />
  </svg>
</template>

<script setup>
const paths = {
  up: 'M5 15l7-7 7 7',
  down: 'M19 9l-7 7-7-7',
  left: 'M15 19l-7-7 7-7',
  right: 'M9 5l7 7-7 7'
}

defineProps({
  direction: {
    type: String,
    default: 'right',
    validator: (value) => ['up', 'down', 'left', 'right'].includes(value)
  }
})
</script>
