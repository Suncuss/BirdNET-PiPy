<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop -->
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="handleBackdropClick"
    />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-lg w-full p-6">
        <!-- Close button -->
        <button
          v-if="!testing"
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          @click="$emit('close')"
        >
          <svg
            class="w-5 h-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>

        <h3 class="text-lg font-semibold text-gray-900 mb-4">
          {{ isEditing ? 'Edit Source' : 'Add Source' }}
        </h3>

        <form
          class="space-y-3"
          @submit.prevent="handleSubmit"
        >
          <!-- Source type selector (only when adding) -->
          <div v-if="!isEditing">
            <label class="block text-sm text-gray-600 mb-1">Type</label>
            <div class="flex gap-2">
              <button
                type="button"
                class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors"
                :class="sourceType === 'pulseaudio'
                  ? 'border-blue-400 bg-blue-50 text-blue-700 font-medium'
                  : 'border-gray-200 text-gray-600 hover:bg-gray-50'"
                :disabled="hasMicSource"
                :title="hasMicSource ? 'A microphone source already exists' : ''"
                @click="sourceType = 'pulseaudio'"
              >
                Microphone
              </button>
              <button
                type="button"
                class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors"
                :class="sourceType === 'rtsp'
                  ? 'border-blue-400 bg-blue-50 text-blue-700 font-medium'
                  : 'border-gray-200 text-gray-600 hover:bg-gray-50'"
                @click="sourceType = 'rtsp'"
              >
                RTSP Stream
              </button>
            </div>
            <p
              v-if="hasMicSource && sourceType !== 'rtsp'"
              class="text-xs text-amber-600 mt-1"
            >
              Only one microphone source is supported
            </p>
          </div>

          <!-- URL field (RTSP only) -->
          <div v-if="sourceType === 'rtsp'">
            <label
              for="stream-url"
              class="block text-sm text-gray-600 mb-1"
            >Stream URL</label>
            <input
              id="stream-url"
              ref="urlInput"
              v-model="url"
              type="text"
              class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              placeholder="rtsp://192.168.1.100/stream"
              @input="clearErrors"
            >
          </div>

          <!-- Label field -->
          <div>
            <label
              for="stream-label"
              class="block text-sm text-gray-600 mb-1"
            >Label <span class="text-gray-400 font-normal">(optional)</span></label>
            <input
              id="stream-label"
              ref="labelInput"
              v-model="label"
              type="text"
              maxlength="30"
              class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              :placeholder="sourceType === 'rtsp' ? 'e.g. Backyard mic' : 'e.g. Local Mic'"
              @input="sanitizeLabelInput"
            >
            <p class="text-xs text-gray-400 mt-0.5">
              Letters, numbers, spaces, hyphens, underscores. Max 30 characters.
            </p>
          </div>

          <!-- Enabled toggle (edit mode only) -->
          <div
            v-if="isEditing"
            class="flex items-center justify-between"
          >
            <div>
              <label class="text-sm text-gray-600">Active</label>
              <p class="text-xs text-gray-400">
                {{ enabled ? 'This source is being recorded' : 'This source will not be recorded' }}
              </p>
            </div>
            <ToggleSwitch
              v-model="enabled"
              size="sm"
            />
          </div>

          <!-- Testing progress -->
          <div
            v-if="testing"
            class="flex items-center gap-2 text-blue-700 text-sm"
          >
            <Spinner class="h-4 w-4" />
            <span>Testing stream connection...</span>
          </div>

          <!-- Error display -->
          <div
            v-else-if="error"
            class="text-xs text-red-600 bg-red-50 p-2 rounded-lg"
          >
            <span>{{ error }}</span>
            <button
              v-if="canForceSubmit"
              type="button"
              class="block text-gray-500 hover:text-gray-700 underline mt-1"
              @click="handleForceSubmit"
            >
              {{ isEditing ? 'Save anyway' : 'Add anyway' }}
            </button>
          </div>

          <!-- Actions -->
          <div class="flex items-center justify-between pt-2">
            <button
              v-if="isEditing"
              type="button"
              class="text-xs text-red-500 hover:text-red-700 transition-colors"
              @click="handleDelete"
            >
              Remove source
            </button>
            <span v-else />
            <button
              type="submit"
              :disabled="!canSubmit || testing"
              class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
            >
              {{ submitLabel }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { sanitizeLabel } from '@/utils/inputHelpers'
import api from '@/services/api'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import Spinner from '@/components/Spinner.vue'

export default {
  name: 'StreamSourceModal',
  components: { ToggleSwitch, Spinner },
  props: {
    source: {
      type: Object,
      default: null
    },
    existingSources: {
      type: Array,
      default: () => []
    }
  },
  emits: ['close', 'add', 'save', 'delete'],
  setup(props, { emit }) {
    const urlInput = ref(null)
    const labelInput = ref(null)
    const sourceType = ref(props.source?.type || 'rtsp')
    const url = ref(props.source?.url || '')
    const label = ref(props.source?.label || '')
    const enabled = ref(props.source?.enabled ?? true)
    const testing = ref(false)
    const error = ref('')
    const canForceSubmit = ref(false)

    const isEditing = computed(() => !!props.source)

    const hasMicSource = computed(() =>
      props.existingSources.some(s => s.type === 'pulseaudio')
    )

    // Auto-select RTSP if mic already exists and we're adding
    if (!isEditing.value && hasMicSource.value) {
      sourceType.value = 'rtsp'
    }

    const canSubmit = computed(() => {
      if (sourceType.value === 'rtsp') return !!url.value.trim()
      return true // mic always valid
    })

    const urlChanged = computed(() =>
      !isEditing.value || url.value.trim() !== (props.source?.url || '')
    )

    const submitLabel = computed(() => {
      return isEditing.value ? 'Save' : 'Add'
    })

    const clearErrors = () => {
      error.value = ''
      canForceSubmit.value = false
    }

    const sanitizeLabelInput = () => {
      label.value = sanitizeLabel(label.value)
    }

    const sanitizeLabelForFilename = (val) =>
      (val || '').trim().replace(/ /g, '_').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 30).toLowerCase()

    const validateLabel = () => {
      const sanitized = sanitizeLabelForFilename(label.value)
      const otherSanitized = props.existingSources
        .filter(s => !isEditing.value || s.id !== props.source.id)
        .map(s => sanitizeLabelForFilename(s.label))
      if (otherSanitized.includes(sanitized)) {
        error.value = sanitized
          ? 'Another source resolves to the same filename suffix'
          : 'Another source also has an empty label — each source needs a unique label for filenames'
        return false
      }
      return true
    }

    const validateRtsp = () => {
      const trimmed = url.value.trim()
      if (!trimmed) {
        error.value = 'URL is required'
        return null
      }
      if (!trimmed.startsWith('rtsp://') && !trimmed.startsWith('rtsps://')) {
        error.value = 'Must start with rtsp:// or rtsps://'
        return null
      }
      // Check duplicates (exclude current source in edit mode)
      const otherUrls = props.existingSources
        .filter(s => s.type === 'rtsp' && (!isEditing.value || s.id !== props.source.id))
        .map(s => s.url)
      if (otherUrls.includes(trimmed)) {
        error.value = 'This URL is already added'
        return null
      }
      return trimmed
    }

    const testStream = async (streamUrl) => {
      testing.value = true
      try {
        const { data } = await api.post('/stream/test', {
          url: streamUrl,
          type: 'rtsp',
        })
        if (!data.success) {
          error.value = data.message || 'Stream not accessible'
          canForceSubmit.value = true
          return false
        }
        return true
      } catch {
        error.value = 'Test request failed'
        canForceSubmit.value = true
        return false
      } finally {
        testing.value = false
      }
    }

    const buildSourceObject = (validatedUrl) => {
      const trimmedLabel = label.value.trim()
      if (sourceType.value === 'rtsp') {
        return {
          type: 'rtsp',
          url: validatedUrl,
          label: trimmedLabel || ''
        }
      }
      return {
        type: 'pulseaudio',
        device: 'default',
        label: trimmedLabel || 'Local Mic'
      }
    }

    const submitSource = (validatedUrl) => {
      if (isEditing.value) {
        const updates = {}
        updates.label = label.value.trim()
        updates.enabled = enabled.value
        if (sourceType.value === 'rtsp') {
          updates.url = validatedUrl
        }
        emit('save', { id: props.source.id, updates })
      } else {
        emit('add', buildSourceObject(validatedUrl))
      }
    }

    const handleSubmit = async () => {
      clearErrors()
      if (!validateLabel()) return

      if (sourceType.value === 'pulseaudio') {
        submitSource(null)
        return
      }

      const validatedUrl = validateRtsp()
      if (!validatedUrl) return

      // Skip test if editing and URL hasn't changed
      if (!urlChanged.value) {
        submitSource(validatedUrl)
        return
      }

      const success = await testStream(validatedUrl)
      if (success) {
        submitSource(validatedUrl)
      }
    }

    const handleForceSubmit = () => {
      clearErrors()
      if (!validateLabel()) return

      if (sourceType.value === 'pulseaudio') {
        submitSource(null)
        return
      }
      const validatedUrl = validateRtsp()
      if (!validatedUrl) return
      submitSource(validatedUrl)
    }

    const handleDelete = () => {
      emit('delete', props.source.id)
    }

    const handleBackdropClick = () => {
      if (!testing.value) {
        emit('close')
      }
    }

    onMounted(() => {
      if (sourceType.value === 'rtsp' && urlInput.value) {
        urlInput.value.focus()
      } else if (labelInput.value) {
        labelInput.value.focus()
      }
    })

    return {
      urlInput,
      labelInput,
      sourceType,
      url,
      label,
      enabled,
      testing,
      error,
      canForceSubmit,
      isEditing,
      hasMicSource,
      canSubmit,
      submitLabel,
      clearErrors,
      sanitizeLabelInput,
      handleSubmit,
      handleForceSubmit,
      handleDelete,
      handleBackdropClick,
    }
  }
}
</script>
