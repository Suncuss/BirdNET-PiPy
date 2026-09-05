<template>
  <div
    ref="rootRef"
    class="relative"
  >
    <input
      ref="inputRef"
      type="text"
      :value="inputText"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-label="ariaLabel || placeholder"
      role="combobox"
      aria-autocomplete="list"
      :aria-expanded="open"
      :aria-activedescendant="activeDescendant"
      :class="inputClasses"
      @focus="onFocus"
      @input="onInput"
      @keydown.down.prevent="onArrow(1)"
      @keydown.up.prevent="onArrow(-1)"
      @keydown.enter.prevent="onEnter"
      @keydown.esc="close"
    >
    <button
      v-if="modelValue && !disabled"
      type="button"
      class="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
      aria-label="Clear selection"
      @mousedown.prevent="clear"
    >
      <CloseIcon class="w-4 h-4" />
    </button>
    <button
      type="button"
      :disabled="disabled"
      tabindex="-1"
      aria-hidden="true"
      class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 disabled:text-gray-300"
      @mousedown.prevent="toggle"
    >
      <ChevronIcon
        direction="down"
        class="h-4 w-4"
      />
    </button>

    <ul
      v-show="open"
      :id="listId"
      role="listbox"
      class="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto"
    >
      <li
        v-if="filtered.length === 0"
        class="px-3 py-2 text-sm text-gray-500"
      >
        {{ emptyText }}
      </li>
      <li
        v-for="(option, index) in filtered"
        :id="`${listId}-${index}`"
        :key="optionKey(option)"
        ref="optionEls"
        role="option"
        :aria-selected="isSelected(option)"
        class="px-3 py-2 text-sm cursor-pointer"
        :class="index === highlighted ? 'bg-gray-100' : ''"
        @mousedown.prevent="select(option)"
        @mouseenter="highlighted = index"
      >
        <slot
          name="option"
          :option="option"
        >
          {{ label(option) }}
        </slot>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch, onMounted, onUnmounted, useId } from 'vue'
import ChevronIcon from '@/components/icons/ChevronIcon.vue'
import CloseIcon from '@/components/icons/CloseIcon.vue'

/**
 * A search-and-select field for a long option list — the shared behaviour of the
 * Table and Charts species pickers, which were two divergent copies.
 *
 * Interaction: the committed value shows as normal text; focus selects it all so
 * the first keystroke replaces it (search); a chevron opens the full list; the
 * ✕ clears; blur or Escape without a pick restores the committed value.
 * Selection commits on click and on Enter over the arrow-highlighted option, so
 * it works by keyboard — the old copies bound to mousedown only.
 *
 * The model is the whole option object (or null), not a key: the field needs the
 * object to render its label anyway, and callers that key on a field map it at
 * the call site.
 */

const props = defineProps({
  modelValue: {
    type: Object,
    default: null
  },
  options: {
    type: Array,
    required: true
  },
  // How an option renders as text (selected label + default row).
  getLabel: {
    type: Function,
    default: (option) => option?.label ?? ''
  },
  // (option, query) => boolean. Default: case-insensitive substring on the label.
  filter: {
    type: Function,
    default: null
  },
  optionKey: {
    type: Function,
    default: null
  },
  placeholder: {
    type: String,
    default: 'Select...'
  },
  ariaLabel: {
    type: String,
    default: ''
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md'].includes(v)
  },
  disabled: {
    type: Boolean,
    default: false
  },
  emptyText: {
    type: String,
    default: 'No results'
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

const rootRef = ref(null)
const inputRef = ref(null)
const optionEls = ref([])
const open = ref(false)
const query = ref('')
const highlighted = ref(-1)

const listId = useId()

const label = (option) => props.getLabel(option)
const optionKey = (option) => (props.optionKey ? props.optionKey(option) : label(option))
const isSelected = (option) => props.modelValue != null && option === props.modelValue

const committedLabel = computed(() => (props.modelValue ? label(props.modelValue) : ''))

// While open the input shows what is being typed; closed, it shows the commit.
const inputText = computed(() => (open.value ? query.value : committedLabel.value))

// An untouched pre-filled selection (query still equals the committed label)
// lists everything, so opening on a value lets you browse rather than see only
// the one row that matches your current pick.
const filtered = computed(() => {
  const q = query.value.trim()
  if (!q || q === committedLabel.value) return props.options
  const match = props.filter || ((option, text) => label(option).toLowerCase().includes(text.toLowerCase()))
  return props.options.filter((option) => match(option, q))
})

const activeDescendant = computed(() =>
  open.value && highlighted.value >= 0 ? `${listId}-${highlighted.value}` : undefined
)

const inputClasses = computed(() => [
  'block w-full pl-3 pr-14 bg-white border border-gray-300 rounded-lg text-sm text-gray-800 transition-colors',
  'enabled:hover:border-gray-400 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/30',
  'disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed',
  props.size === 'sm' ? 'h-9' : 'h-10'
])

const openList = () => {
  if (props.disabled) return
  open.value = true
  query.value = committedLabel.value
  // Highlight the current selection so arrow keys start from it.
  highlighted.value = props.modelValue ? props.options.indexOf(props.modelValue) : -1
}

const close = () => {
  open.value = false
  query.value = committedLabel.value
}

const onFocus = () => {
  openList()
  nextTick(() => inputRef.value?.select())
}

const onInput = (event) => {
  query.value = event.target.value
  open.value = true
  highlighted.value = filtered.value.length ? 0 : -1
}

const toggle = () => {
  if (open.value) {
    close()
    return
  }
  inputRef.value?.focus()  // @focus opens and selects
}

const select = (option) => {
  emit('update:modelValue', option)
  emit('change', option)
  open.value = false
  query.value = label(option)
}

const clear = () => {
  emit('update:modelValue', null)
  emit('change', null)
  query.value = ''
  open.value = false
}

const onArrow = (delta) => {
  if (!open.value) {
    openList()
    return
  }
  const count = filtered.value.length
  if (!count) return
  highlighted.value = (highlighted.value + delta + count) % count
}

const onEnter = () => {
  if (open.value && highlighted.value >= 0 && filtered.value[highlighted.value]) {
    select(filtered.value[highlighted.value])
  }
}

// Keep the arrow-highlighted row in view.
watch(highlighted, (index) => {
  if (index >= 0) nextTick(() => optionEls.value[index]?.scrollIntoView({ block: 'nearest' }))
})

const closeOnOutsideClick = (event) => {
  if (rootRef.value && !rootRef.value.contains(event.target)) close()
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onUnmounted(() => document.removeEventListener('click', closeOnOutsideClick))
</script>
