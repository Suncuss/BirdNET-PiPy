<template>
  <DatePicker
    v-model="dateValue"
    :disabled="disabled"
    :maxDate="maxDateObj"
    dateFormat="mm/dd/yy"
    showIcon
    iconDisplay="input"
    :pt="passThrough"
    @date-select="onDateSelect"
  />
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import DatePicker from 'primevue/datepicker'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  disabled: {
    type: Boolean,
    default: false
  },
  max: {
    type: String,
    default: null
  },
  size: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'large'].includes(v)
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

// Convert string date (YYYY-MM-DD) to Date object for PrimeVue
const dateValue = ref(props.modelValue ? new Date(props.modelValue + 'T00:00:00') : null)

// Convert max string to Date object
const maxDateObj = computed(() => {
  if (!props.max) return null
  return new Date(props.max + 'T23:59:59')
})

// Watch for external changes to modelValue
watch(() => props.modelValue, (newVal) => {
  if (newVal) {
    const newDate = new Date(newVal + 'T00:00:00')
    // Only update if different to avoid loops
    if (!dateValue.value || newDate.getTime() !== dateValue.value.getTime()) {
      dateValue.value = newDate
    }
  } else {
    dateValue.value = null
  }
})

// Handle date selection - convert back to string format
const onDateSelect = (date) => {
  if (date) {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const dateString = `${year}-${month}-${day}`
    emit('update:modelValue', dateString)
    emit('change', dateString)
  } else {
    emit('update:modelValue', '')
    emit('change', '')
  }
}

// Size classes
const heightClass = computed(() => props.size === 'large' ? 'h-10' : 'h-9')

// Custom styling to match existing Tailwind design
const passThrough = computed(() => ({
  root: {
    class: 'relative inline-block w-[140px] font-sans'
  },
  pcInputText: {
    root: {
      class: [
        heightClass.value,
        'w-full px-2 border rounded-md !text-base leading-none transition-colors font-normal',
        props.disabled
          ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
          : 'border-gray-300 bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
      ].join(' ')
    }
  },
  dropdown: {
    class: 'absolute right-0 top-0 h-full px-2 flex items-center text-gray-400 hover:text-gray-600'
  },
  panel: {
    class: 'bg-white border border-gray-200 rounded-lg shadow-lg mt-1 p-1.5'
  },
  header: {
    class: 'flex items-center justify-between p-1'
  },
  pcPrevButton: {
    root: {
      class: 'p-1.5 hover:bg-gray-100 rounded-md text-gray-600'
    }
  },
  pcNextButton: {
    root: {
      class: 'p-1.5 hover:bg-gray-100 rounded-md text-gray-600'
    }
  },
  title: {
    class: 'font-semibold text-gray-700 text-sm'
  },
  dayView: {
    class: 'mt-1'
  },
  weekHeader: {
    class: 'text-xs font-semibold text-gray-500 p-1'
  },
  weekDay: {
    class: 'text-xs font-semibold text-gray-500 p-1 text-center'
  },
  day: {
    class: 'p-0'
  },
  dayLabel: ({ context }) => ({
    class: [
      'w-7 h-7 flex items-center justify-center rounded-md text-xs cursor-pointer transition-colors',
      context.selected
        ? 'bg-blue-600 text-white'
        : context.today
          ? 'border border-blue-500 text-blue-600'
          : context.disabled
            ? 'text-gray-300 cursor-not-allowed'
            : context.otherMonth
              ? 'text-gray-400 hover:bg-gray-100'
              : 'text-gray-700 hover:bg-gray-100'
    ].join(' ')
  }),
  monthView: {
    class: 'mt-2'
  },
  month: ({ context }) => ({
    class: [
      'p-2 rounded-md cursor-pointer transition-colors',
      context.selected
        ? 'bg-blue-600 text-white'
        : 'text-gray-700 hover:bg-gray-100'
    ].join(' ')
  }),
  yearView: {
    class: 'mt-2'
  },
  year: ({ context }) => ({
    class: [
      'p-2 rounded-md cursor-pointer transition-colors',
      context.selected
        ? 'bg-blue-600 text-white'
        : 'text-gray-700 hover:bg-gray-100'
    ].join(' ')
  })
}))
</script>
