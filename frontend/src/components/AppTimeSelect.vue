<template>
  <AppListbox
    :model-value="modelValue"
    :options="options"
    :disabled="disabled"
    fluid
    @update:model-value="emit('update:modelValue', $event)"
    @change="emit('change', $event)"
  />
</template>

<script setup>
import { computed } from 'vue'
import AppListbox from '@/components/AppListbox.vue'
import { useTimeFormat } from '@/composables/useTimeFormat'
import { formatClock } from '@/utils/quietHours'

/**
 * Clock-time dropdown for Quiet Hours: AppListbox over the whole-hour grid.
 *
 * The model is a strict 24-hour "HH:MM" string — what the backend stores —
 * while the labels follow the user's 12/24-hour preference. A native
 * <input type="time"> cannot do that (it renders in the browser's locale), but
 * a label-based dropdown can, because the labels are just strings.
 */

// Whole hours only. Fixed for the life of the app, so it is built once and
// shared by every instance.
const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`)

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  disabled: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

const { formatTime } = useTimeFormat()

// The backend stores any valid "HH:MM", and off-the-hour values exist — set
// through the API, by the native time input this replaced, or by an earlier
// half-hour version of this picker. Such a value has to be listed even though
// nothing here offers it, or the control renders blank. Drop this and a saved
// 22:30 disappears.
const options = computed(() => {
  const current = props.modelValue
  const times = !current || HOURS.includes(current)
    ? HOURS
    : [...HOURS, current].sort()  // "HH:MM" sorts chronologically
  return times.map((time) => ({ value: time, label: formatClock(time, formatTime) }))
})
</script>
