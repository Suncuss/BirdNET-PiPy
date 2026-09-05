<template>
  <div
    ref="rootRef"
    :class="[fluid ? 'block w-full' : 'inline-block', rootClass]"
    :style="rootStyle"
    class="relative"
  >
    <button
      ref="triggerRef"
      type="button"
      v-bind="buttonAttrs"
      :disabled="disabled"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-activedescendant="activeDescendant"
      :class="triggerClasses"
      @click="toggle"
      @keydown.down.prevent="onArrow(1)"
      @keydown.up.prevent="onArrow(-1)"
      @keydown.home.prevent="onHome"
      @keydown.end.prevent="onEnd"
      @keydown.enter.prevent="onEnter"
      @keydown.space.prevent="onSpace"
      @keydown.esc="close"
      @keydown="onTypeahead"
    >
      <span :class="selectedLabel ? 'truncate' : 'truncate text-gray-400'">
        {{ selectedLabel || placeholder }}
      </span>
      <ChevronIcon
        direction="down"
        class="h-4 w-4 shrink-0"
        :class="disabled ? 'text-gray-300' : 'text-gray-500'"
      />
    </button>

    <ul
      v-show="open"
      :id="listId"
      ref="menuRef"
      role="listbox"
      class="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto"
    >
      <li
        v-for="(option, index) in options"
        :id="`${listId}-${index}`"
        :key="toKey(option.value)"
        ref="optionEls"
        role="option"
        :aria-selected="isSelected(option)"
        class="px-3 py-2 text-sm cursor-pointer"
        :class="[
          index === highlighted ? 'bg-gray-100' : '',
          isSelected(option) ? 'font-medium text-gray-900' : 'text-gray-700'
        ]"
        @click="select(option)"
        @mouseenter="highlighted = index"
      >
        {{ option.label }}
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch, onMounted, onUnmounted, useId, useAttrs } from 'vue'
import ChevronIcon from '@/components/icons/ChevronIcon.vue'

/**
 * The app's dropdown: a custom trigger and popup so the open menu looks the
 * same in every browser (a native <select>'s menu is drawn by the OS). Same
 * props and events as a plain select — { value, label } options, typed values
 * out — so it drops in wherever a select was.
 *
 * Keyboard parity with a native select is deliberate, since the custom popup
 * gives none for free: arrows and Home/End move the highlight, Enter/Space
 * commit, Escape closes, and typing jumps to a matching label (type-ahead).
 *
 * class/style land on the root wrapper; every other fall-through attribute
 * (id, aria-label) lands on the trigger button, so an external <label for>
 * resolves to something focusable.
 */

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: {
    type: [String, Number, Boolean],
    default: null
  },
  options: {
    type: Array,
    required: true
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md'].includes(v)
  },
  fluid: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  },
  placeholder: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

const attrs = useAttrs()
const rootClass = computed(() => attrs.class)
const rootStyle = computed(() => attrs.style)
const buttonAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return rest
})

const rootRef = ref(null)
const triggerRef = ref(null)
const menuRef = ref(null)
const optionEls = ref([])
const open = ref(false)
const highlighted = ref(-1)
const listId = useId()

const toKey = (value) => String(value)
const isSelected = (option) => option.value === props.modelValue
const selectedIndex = computed(() => props.options.findIndex(isSelected))
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label ?? '')

const activeDescendant = computed(() =>
  open.value && highlighted.value >= 0 ? `${listId}-${highlighted.value}` : undefined
)

const triggerClasses = computed(() => [
  'flex w-full items-center justify-between gap-2 pl-3 pr-2.5 text-sm text-left text-gray-800 bg-white',
  'border border-gray-300 rounded-lg transition-colors',
  'enabled:hover:border-gray-400 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/30',
  'disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed',
  props.size === 'sm' ? 'h-9' : 'h-10'
])

const openList = () => {
  if (props.disabled) return
  open.value = true
  highlighted.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
}

const close = () => {
  if (!open.value) return
  open.value = false
  triggerRef.value?.focus?.()
}

const toggle = () => {
  if (open.value) close()
  else openList()
}

const select = (option) => {
  emit('update:modelValue', option.value)
  emit('change', option.value)
  open.value = false
  triggerRef.value?.focus?.()
}

const onArrow = (delta) => {
  if (!open.value) {
    openList()
    return
  }
  const count = props.options.length
  if (!count) return
  highlighted.value = (highlighted.value + delta + count) % count
}

const onHome = () => {
  if (open.value) highlighted.value = 0
}

const onEnd = () => {
  if (open.value) highlighted.value = props.options.length - 1
}

const commitHighlighted = () => {
  if (open.value && props.options[highlighted.value]) select(props.options[highlighted.value])
}

const onEnter = () => {
  if (open.value) commitHighlighted()
  else openList()
}

const onSpace = () => {
  if (open.value) commitHighlighted()
  else openList()
}

// Type-ahead: buffer keystrokes briefly and jump to the first label that
// starts with them, matching a native select. Open — moves the highlight;
// closed — commits directly, as a native select does.
let typeBuffer = ''
let typeTimer = null
const onTypeahead = (event) => {
  if (event.key.length !== 1 || event.altKey || event.ctrlKey || event.metaKey) return
  event.preventDefault()
  typeBuffer += event.key.toLowerCase()
  clearTimeout(typeTimer)
  typeTimer = setTimeout(() => { typeBuffer = '' }, 500)

  const index = props.options.findIndex((option) =>
    String(option.label).toLowerCase().startsWith(typeBuffer)
  )
  if (index === -1) return
  if (open.value) highlighted.value = index
  else select(props.options[index])
}

watch(highlighted, (index) => {
  if (open.value && index >= 0) nextTick(() => optionEls.value[index]?.scrollIntoView({ block: 'nearest' }))
})

const closeOnOutsideClick = (event) => {
  if (rootRef.value && !rootRef.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onUnmounted(() => {
  document.removeEventListener('click', closeOnOutsideClick)
  clearTimeout(typeTimer)
})
</script>
