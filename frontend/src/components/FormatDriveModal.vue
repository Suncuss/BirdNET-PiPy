<template>
  <dialog
    ref="dialog"
    aria-labelledby="format-drive-title"
    :aria-describedby="job ? 'format-drive-progress' : 'format-drive-warning'"
    class="m-auto w-full max-w-sm rounded-xl p-0 shadow-xl backdrop:bg-black/50"
    @cancel.prevent="closeDialog"
  >
    <div class="relative bg-white p-6">
      <button
        type="button"
        :aria-label="job && !finished ? 'Hide progress' : 'Close'"
        :disabled="checking"
        class="absolute top-4 right-4 text-gray-500 hover:text-gray-700"
        @click="closeDialog"
      >
        <CloseIcon class="h-5 w-5" />
      </button>
      <h2
        id="format-drive-title"
        class="text-lg font-semibold text-gray-900 pr-8 mb-3"
      >
        {{ title }}
      </h2>
      <p class="text-sm font-medium text-gray-800">
        {{ drive.name }} · {{ sizeLabel }}
      </p>
      <p class="text-xs text-gray-600 mb-4">
        {{ drive.path }}
      </p>
      <section
        v-if="job"
        id="format-drive-progress"
        :role="currentJob.state === 'failed' ? 'alert' : 'status'"
        aria-live="polite"
        aria-atomic="true"
      >
        <p
          :class="currentJob.state === 'failed' ? 'text-red-700' : 'text-gray-800'"
          class="text-sm"
        >
          {{ currentJob.message || 'Waiting for formatting to start…' }}
        </p>
        <progress
          v-if="!finished"
          aria-label="Drive formatting progress"
          :aria-valuetext="currentJob.message || 'Starting formatting'"
          class="mt-4 h-2 w-full accent-blue-600"
        />
        <p
          v-if="!finished"
          class="mt-3 text-sm text-gray-700"
        >
          Keep the drive connected until formatting finishes.
        </p>
        <button
          type="button"
          class="mt-5 w-full rounded-lg border border-gray-300 py-2 text-sm text-gray-800 hover:bg-gray-100"
          @click="closeDialog"
        >
          {{ finished ? 'Done' : 'Hide progress' }}
        </button>
      </section>
      <template v-else>
        <p
          id="format-drive-warning"
          class="text-sm font-medium text-red-700 mb-3"
        >
          Formatting will erase all data on this drive.
        </p>
        <p class="text-sm text-gray-700 mb-4">
          New format: <strong>ext4</strong>
        </p>
        <label
          for="format-drive-name"
          class="block text-sm text-gray-700 mb-1"
        >Type “{{ drive.name }}” to confirm</label>
        <input
          id="format-drive-name"
          v-model="confirmation"
          autofocus
          autocomplete="off"
          :spellcheck="false"
          required
          :disabled="checking"
          :aria-invalid="confirmation.length > 0 && !nameMatches"
          aria-describedby="format-drive-match"
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-green-600 focus:outline-none focus:ring-1 focus:ring-green-600"
        >
        <p
          id="format-drive-match"
          class="mt-1 text-xs text-gray-600 min-h-4"
          role="status"
        >
          {{ confirmation ? nameMatches ? 'Drive name matches.' : 'Drive name does not match.' : '' }}
        </p>
        <p
          v-if="error"
          class="mt-3 text-sm text-red-700"
          role="alert"
        >
          {{ error }}
        </p>
        <p class="mt-3 text-xs text-gray-600">
          Recording continues. No restart needed. The drive will be mounted for media storage.
        </p>
        <div class="flex gap-3 mt-4">
          <button
            type="button"
            :disabled="checking"
            class="flex-1 rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-100"
            @click="closeDialog"
          >
            Cancel
          </button>
          <button
            type="button"
            :disabled="!nameMatches || !drive.device_id || checking"
            :aria-busy="checking"
            class="flex-1 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700 disabled:bg-gray-200 disabled:text-gray-600 disabled:cursor-not-allowed"
            @click="startFormat"
          >
            {{ checking ? 'Starting…' : 'Erase and format' }}
          </button>
        </div>
      </template>
    </div>
  </dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import api from '@/services/api'
import CloseIcon from '@/components/icons/CloseIcon.vue'

const props = defineProps({
  drive: { type: Object, required: true },
  sizeLabel: { type: String, required: true },
  progress: { type: Object, default: null }
})
const emit = defineEmits(['close', 'started'])

const dialog = ref(null)
const confirmation = ref('')
const checking = ref(false)
const error = ref('')
const job = ref(null)
const currentJob = computed(() => props.progress?.id === job.value?.id ? props.progress : job.value)
const finished = computed(() => ['complete', 'failed'].includes(currentJob.value?.state))
const title = computed(() => {
  if (!job.value) return 'Format drive'
  if (!finished.value) return 'Formatting drive'
  return currentJob.value.state === 'complete' ? 'Drive ready' : 'Formatting failed'
})
const closeDialog = () => { if (!checking.value) emit('close') }
watch(confirmation, () => { error.value = '' })
const startFormat = async () => {
  if (!nameMatches.value || !props.drive.device_id || checking.value || job.value) return
  checking.value = true
  error.value = ''
  try {
    const { data } = await api.post('/system/storage/format', {
      path: props.drive.path,
      device_id: props.drive.device_id,
      confirmation: confirmation.value
    })
    job.value = data
    emit('started', data)
  } catch (failure) {
    error.value = failure.response?.data?.error || 'Could not start formatting. Try again.'
  } finally {
    checking.value = false
  }
}

const nameMatches = computed(() => confirmation.value === props.drive.name)
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => dialog.value.close())
</script>
