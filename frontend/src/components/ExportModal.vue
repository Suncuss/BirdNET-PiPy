<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="requestDismiss"
    />
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <!-- Closing never cancels: a preparing export keeps going server-side. -->
        <button
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          title="Close"
          @click="requestDismiss"
        >
          <CloseIcon class="w-5 h-5" />
        </button>

        <h2 class="text-lg font-semibold text-gray-900 mb-1 pr-8">
          Export detections
        </h2>

        <div
          v-if="exportJob.loading.value"
          class="py-10 flex justify-center"
        >
          <Spinner />
        </div>

        <!-- Step 1: options -->
        <div v-else-if="!job">
          <p class="text-sm text-gray-600 mb-4">
            Downloads a .zip file containing a CSV of your detections.
          </p>

          <p class="text-sm font-medium text-gray-700 mb-2">
            Time range
          </p>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3">
            <button
              v-for="preset in RANGE_PRESETS"
              :key="preset.value"
              :class="[
                'py-2 text-sm rounded-lg border transition-colors',
                range === preset.value
                  ? 'border-green-600 bg-green-50 text-green-700 font-medium'
                  : 'border-gray-200 text-gray-600 hover:bg-gray-50'
              ]"
              :aria-pressed="range === preset.value"
              @click="range = preset.value"
            >
              {{ preset.label }}
            </button>
          </div>

          <div
            v-if="range === 'custom'"
            class="flex gap-2 mb-3"
          >
            <div class="flex-1">
              <label class="block text-xs text-gray-500 mb-1">From</label>
              <AppDatePicker
                v-model="startDate"
                :max="endDate || todayDate"
                fluid
              />
            </div>
            <div class="flex-1">
              <label class="block text-xs text-gray-500 mb-1">To</label>
              <AppDatePicker
                v-model="endDate"
                :min="startDate || undefined"
                :max="todayDate"
                fluid
              />
            </div>
          </div>

          <p
            class="text-sm text-gray-600 mb-4 min-h-[1.25rem]"
            data-testid="export-count"
          >
            {{ countLabel }}
          </p>

          <p
            v-if="exportJob.error.value"
            class="mb-4 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
          >
            {{ exportJob.error.value }}
          </p>

          <div class="flex gap-3">
            <button
              class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
              @click="requestDismiss"
            >
              Cancel
            </button>
            <button
              :disabled="!canStart"
              class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors disabled:bg-gray-300"
              @click="startExport"
            >
              {{ exportJob.starting.value ? 'Starting...' : 'Prepare export' }}
            </button>
          </div>
        </div>

        <!-- Step 2: preparing -->
        <div v-else-if="job.state === 'preparing'">
          <p class="text-sm text-gray-600 mb-4">
            Preparing {{ rangeLabel }}…
          </p>
          <div class="flex justify-between text-sm text-gray-600 mb-2">
            <span>{{ job.rows_done.toLocaleString() }} of {{ job.rows_total.toLocaleString() }} detections</span>
            <span>{{ exportJob.percent.value }}%</span>
          </div>
          <div
            class="w-full bg-gray-200 rounded-full h-3 mb-4"
            role="progressbar"
            :aria-valuenow="exportJob.percent.value"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <div
              class="bg-green-600 h-3 rounded-full transition-all duration-300"
              :style="{ width: `${exportJob.percent.value}%` }"
            />
          </div>
          <p class="text-xs text-gray-500 mb-4">
            You can close this window. The export keeps preparing and will be here when you come back.
          </p>
          <button
            class="w-full py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
            @click="exportJob.discard"
          >
            Cancel export
          </button>
        </div>

        <!-- Step 3: ready -->
        <div v-else-if="job.state === 'ready'">
          <p class="text-sm text-gray-600 mb-4">
            Your export of {{ rangeLabel }} is ready.
          </p>
          <div class="bg-gray-50 rounded-lg p-3 mb-3 text-sm">
            <p class="font-medium text-gray-900 break-all">
              {{ job.filename }}
            </p>
            <p class="text-gray-500 mt-1">
              {{ job.rows_total.toLocaleString() }} detections · {{ formatBytes(job.bytes) }}
            </p>
          </div>
          <p class="text-xs text-gray-500 mb-4">
            Available to download for an hour.
          </p>
          <div class="flex gap-3">
            <button
              class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
              @click="exportJob.discard"
            >
              New export
            </button>
            <a
              :href="exportJob.downloadUrl.value"
              :download="job.filename"
              class="flex-1 py-2 text-sm text-center bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
            >
              Download
            </a>
          </div>
        </div>

        <!-- Failed -->
        <div v-else>
          <p class="mb-4 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded">
            {{ job.error || 'The export failed.' }}
          </p>
          <button
            class="w-full py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
            @click="exportJob.discard"
          >
            Start over
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import Spinner from '@/components/Spinner.vue'
import CloseIcon from '@/components/icons/CloseIcon.vue'
import { useExportJob } from '@/composables/useExportJob'
import { useModalDismiss } from '@/composables/useModalDismiss'
import { formatBytes, getLocalDateString } from '@/utils/format'

const RANGE_PRESETS = [
  { value: 'all', label: 'All time' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'year', label: 'This year' },
  { value: 'custom', label: 'Custom' }
]

// Debounce for the row-count preview while dates are being picked.
const COUNT_DEBOUNCE_MS = 250

const emit = defineEmits(['close'])

const exportJob = useExportJob()
const job = exportJob.job

const range = ref('all')
const startDate = ref('')
const endDate = ref('')
const count = ref(null) // null while counting
const countFailed = ref(false)
// The station's date bounds the custom range; the browser's is a fallback.
const todayDate = computed(() => exportJob.today.value || getLocalDateString())

const options = computed(() =>
  range.value === 'custom'
    ? { range: 'custom', start_date: startDate.value, end_date: endDate.value }
    : { range: range.value }
)

const optionsComplete = computed(() =>
  range.value !== 'custom' || Boolean(startDate.value && endDate.value)
)

// A failed count doesn't block the export itself — the server counts again.
const canStart = computed(() =>
  optionsComplete.value && (count.value > 0 || countFailed.value) && !exportJob.starting.value
)

const countLabel = computed(() => {
  if (!optionsComplete.value) return 'Pick a start and end date.'
  if (countFailed.value) return "Couldn't count the detections in this range."
  if (count.value === null) return 'Counting detections…'
  if (count.value === 0) return 'No detections in this range.'
  return `${count.value.toLocaleString()} detection${count.value === 1 ? '' : 's'}`
})

// Describes the running/finished job's own range, not the (reset) form.
const rangeLabel = computed(() => {
  const { start_date: start, end_date: end } = job.value || {}
  if (!start) return 'all detections'
  return start === end ? `detections on ${start}` : `detections from ${start} to ${end}`
})

let countTimer = null
let countSeq = 0

const refreshCount = () => {
  clearTimeout(countTimer)
  count.value = null
  countFailed.value = false
  if (!optionsComplete.value) return
  const seq = ++countSeq
  countTimer = setTimeout(async () => {
    try {
      const value = await exportJob.fetchCount(options.value)
      if (seq === countSeq) count.value = value
    } catch {
      if (seq === countSeq) countFailed.value = true
    }
  }, COUNT_DEBOUNCE_MS)
}

watch(options, refreshCount, { deep: true })

// Back on the options step (after Cancel / New export / Start over): recount,
// since detections may have arrived meanwhile.
watch(() => job.value === null, (noJob) => {
  if (noJob) refreshCount()
})

const startExport = () => exportJob.start(options.value)

const { requestDismiss } = useModalDismiss(
  () => true,
  () => emit('close')
)

onMounted(async () => {
  await exportJob.load()
  if (!job.value) refreshCount()
})
</script>
