<template>
  <button
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    :class="[
      modelValue ? 'bg-green-600' : 'bg-gray-200',
      sizeConfig.track
    ]"
    class="relative inline-flex flex-shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      :class="[
        modelValue ? sizeConfig.on : sizeConfig.off,
        sizeConfig.knob
      ]"
      class="inline-block transform rounded-full bg-white transition-transform"
    />
  </button>
</template>

<script>
export default {
  name: 'ToggleSwitch',
  props: {
    modelValue: {
      type: Boolean,
      required: true
    },
    disabled: {
      type: Boolean,
      default: false
    },
    size: {
      type: String,
      default: 'default',
      validator: (v) => ['default', 'sm'].includes(v)
    }
  },
  emits: ['update:modelValue'],
  computed: {
    sizeConfig() {
      return this.size === 'sm'
        ? { track: 'h-5 w-9', knob: 'h-3.5 w-3.5', on: 'translate-x-5', off: 'translate-x-0.5' }
        : { track: 'h-6 w-11', knob: 'h-4 w-4', on: 'translate-x-6', off: 'translate-x-1' }
    }
  }
}
</script>
