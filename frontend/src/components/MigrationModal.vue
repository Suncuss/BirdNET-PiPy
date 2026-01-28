<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop -->
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="handleBackdropClick"
    ></div>

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-lg w-full p-6">
        <!-- Close button -->
        <button
          v-if="!migration.isImporting.value"
          @click="handleClose"
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
        >
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <!-- Step 1: Upload -->
        <div v-if="currentStep === 'upload'">
          <!-- Header -->
          <div class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-blue-100 mb-4">
              <svg class="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Import from BirdNET-Pi</h2>
            <p class="mt-2 text-sm text-gray-600">
              Upload your BirdNET-Pi <code class="bg-gray-100 px-1 rounded">birds.db</code> file to import your historical bird detections.
            </p>
          </div>

          <!-- Error message -->
          <div v-if="migration.error.value" class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm">
            {{ migration.error.value }}
          </div>

          <!-- Drop zone -->
          <div
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop"
            :class="[
              'border-2 border-dashed rounded-lg p-8 text-center transition-colors',
              isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
            ]"
          >
            <input
              ref="fileInput"
              type="file"
              accept=".db"
              @change="handleFileSelect"
              class="hidden"
            />

            <div v-if="migration.isUploading.value" class="flex flex-col items-center">
              <!-- Upload progress bar -->
              <div class="w-full mb-3">
                <div class="flex justify-between text-xs text-gray-600 mb-1">
                  <span>Uploading...</span>
                  <span>{{ migration.uploadProgress.value }}%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                  <div
                    class="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    :style="{ width: `${migration.uploadProgress.value}%` }"
                  ></div>
                </div>
              </div>
              <p class="text-sm text-gray-600">Validating file...</p>
            </div>

            <div v-else>
              <svg class="mx-auto h-12 w-12 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
              <p class="text-sm text-gray-600 mb-2">
                Drag and drop your <code class="bg-gray-100 px-1 rounded">birds.db</code> file here
              </p>
              <p class="text-xs text-gray-500 mb-3">or</p>
              <button
                @click="$refs.fileInput.click()"
                class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                Browse Files
              </button>
            </div>
          </div>

          <!-- Help text -->
          <p class="mt-4 text-xs text-gray-500 text-center">
            The <code class="bg-gray-100 px-1 rounded">birds.db</code> file is typically located at
            <code class="bg-gray-100 px-1 rounded">/home/pi/BirdNET-Pi/scripts/birds.db</code> on your BirdNET-Pi system.
          </p>
        </div>

        <!-- Step 2: Preview -->
        <div v-else-if="currentStep === 'preview'">
          <!-- Header -->
          <div class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
              <svg class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Ready to Import</h2>
            <p class="mt-2 text-sm text-gray-600">
              Review the import summary below before proceeding.
            </p>
          </div>

          <!-- Statistics -->
          <div class="bg-gray-50 rounded-lg p-4 mb-4">
            <div class="text-center">
              <p class="text-2xl font-bold text-gray-900">{{ migration.recordCount.value.toLocaleString() }}</p>
              <p class="text-xs text-gray-500">Total Records</p>
            </div>
            <p class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
              Duplicate records will be automatically skipped during import.
            </p>
          </div>

          <!-- Preview table -->
          <div v-if="migration.previewRecords.value.length > 0" class="mb-4">
            <p class="text-sm font-medium text-gray-700 mb-2">Sample Records:</p>
            <div class="border rounded-lg overflow-hidden">
              <table class="min-w-full divide-y divide-gray-200 text-sm">
                <thead class="bg-gray-50">
                  <tr>
                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">Species</th>
                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">Date</th>
                    <th class="px-3 py-2 text-right text-xs font-medium text-gray-500">Confidence</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-200">
                  <tr v-for="(record, index) in migration.previewRecords.value.slice(0, 5)" :key="index">
                    <td class="px-3 py-2 text-gray-900">{{ record.common_name }}</td>
                    <td class="px-3 py-2 text-gray-600">{{ formatDate(record.timestamp) }}</td>
                    <td class="px-3 py-2 text-right text-gray-600">{{ formatConfidence(record.confidence) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Error message -->
          <div v-if="migration.error.value" class="mb-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm">
            {{ migration.error.value }}
          </div>

          <!-- Buttons -->
          <div class="flex gap-3">
            <button
              @click="handleCancel"
              class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              @click="handleImport"
              class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
            >
              Import
            </button>
          </div>
        </div>

        <!-- Step 3: Importing (Progress) -->
        <div v-else-if="currentStep === 'importing'">
          <!-- Header -->
          <div class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-blue-100 mb-4">
              <svg class="h-6 w-6 text-blue-600 animate-pulse" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Importing Records</h2>
            <p class="mt-2 text-sm text-gray-600">
              Please wait while your data is being imported...
            </p>
          </div>

          <!-- Progress bar -->
          <div class="mb-4">
            <div class="flex justify-between text-sm text-gray-600 mb-2">
              <span>Progress</span>
              <span>{{ migration.importProgressPercent.value }}%</span>
            </div>
            <div class="w-full bg-gray-200 rounded-full h-3">
              <div
                class="bg-blue-600 h-3 rounded-full transition-all duration-300"
                :style="{ width: `${migration.importProgressPercent.value}%` }"
              ></div>
            </div>
          </div>

          <!-- Statistics -->
          <div class="bg-gray-50 rounded-lg p-4 mb-4">
            <div class="grid grid-cols-3 gap-4 text-center">
              <div>
                <p class="text-lg font-bold text-green-600">{{ migration.importProgress.value.imported.toLocaleString() }}</p>
                <p class="text-xs text-gray-500">Imported</p>
              </div>
              <div>
                <p class="text-lg font-bold text-gray-500">{{ migration.importProgress.value.skipped.toLocaleString() }}</p>
                <p class="text-xs text-gray-500">Skipped</p>
              </div>
              <div>
                <p class="text-lg font-bold" :class="migration.importProgress.value.errors > 0 ? 'text-red-600' : 'text-gray-400'">
                  {{ migration.importProgress.value.errors.toLocaleString() }}
                </p>
                <p class="text-xs text-gray-500">Errors</p>
              </div>
            </div>
            <div class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
              {{ migration.importProgress.value.processed.toLocaleString() }} / {{ migration.importProgress.value.total.toLocaleString() }} records processed
            </div>
          </div>

          <!-- Note about background processing -->
          <p class="text-xs text-gray-500 text-center">
            Please wait while your data is being imported.
          </p>
        </div>

        <!-- Step 4: Result -->
        <div v-else-if="currentStep === 'result'">
          <!-- Success Header -->
          <div v-if="!hasErrors && !migration.importResult.value?.warning" class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
              <svg class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Import Complete</h2>
            <p class="mt-2 text-sm text-gray-600">
              Your BirdNET-Pi data has been imported successfully.
            </p>
          </div>

          <!-- Status Expired Warning Header -->
          <div v-else-if="migration.importResult.value?.warning" class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-amber-100 mb-4">
              <svg class="h-6 w-6 text-amber-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Import Status Unknown</h2>
            <p class="mt-2 text-sm text-gray-600">
              {{ migration.importResult.value.warning }}
            </p>
          </div>

          <!-- Partial Success Header -->
          <div v-else class="text-center mb-6">
            <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-amber-100 mb-4">
              <svg class="h-6 w-6 text-amber-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <h2 class="text-xl font-semibold text-gray-900">Import Completed with Warnings</h2>
            <p class="mt-2 text-sm text-gray-600">
              Some records could not be imported.
            </p>
          </div>

          <!-- Statistics -->
          <div class="bg-gray-50 rounded-lg p-4 mb-4">
            <div class="grid grid-cols-3 gap-4 text-center">
              <div>
                <p class="text-2xl font-bold text-green-600">{{ migration.importResult.value?.imported?.toLocaleString() || 0 }}</p>
                <p class="text-xs text-gray-500">Imported</p>
              </div>
              <div>
                <p class="text-2xl font-bold text-gray-600">{{ migration.importResult.value?.skipped?.toLocaleString() || 0 }}</p>
                <p class="text-xs text-gray-500">Skipped</p>
              </div>
              <div>
                <p class="text-2xl font-bold" :class="hasErrors ? 'text-red-600' : 'text-gray-400'">{{ migration.importResult.value?.errors || 0 }}</p>
                <p class="text-xs text-gray-500">Errors</p>
              </div>
            </div>
          </div>

          <!-- Done button -->
          <button
            @click="handleDone"
            class="w-full py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onUnmounted } from 'vue'
import { useMigration } from '@/composables/useMigration'

export default {
  name: 'MigrationModal',
  emits: ['close'],
  setup(props, { emit }) {
    // Composable
    const migration = useMigration()

    // Local state
    const isDragging = ref(false)
    const fileInput = ref(null)

    // Current step: 'upload' | 'preview' | 'importing' | 'result'
    const currentStep = computed(() => {
      if (migration.importResult.value) return 'result'
      if (migration.isImporting.value) return 'importing'
      if (migration.isValidated.value) return 'preview'
      return 'upload'
    })

    // Check if import had errors
    const hasErrors = computed(() => {
      return (migration.importResult.value?.errors || 0) > 0
    })

    // Handle file drop
    const handleDrop = (event) => {
      isDragging.value = false
      const files = event.dataTransfer.files
      if (files.length > 0) {
        processFile(files[0])
      }
    }

    // Handle file selection via input
    const handleFileSelect = (event) => {
      const files = event.target.files
      if (files.length > 0) {
        processFile(files[0])
      }
      // Reset input so same file can be selected again
      event.target.value = ''
    }

    // Process the selected file
    const processFile = async (file) => {
      migration.clearError()
      await migration.validateFile(file)
    }

    // Handle import button click
    const handleImport = async () => {
      await migration.runImport(true) // Always skip duplicates
    }

    // Handle cancel button
    const handleCancel = async () => {
      await migration.cancelMigration()
    }

    // Handle done button
    const handleDone = () => {
      migration.reset()
      emit('close')
    }

    // Handle close (X button or backdrop)
    const handleClose = async () => {
      if (migration.isImporting.value) return // Don't allow close during import

      // Clean up if we're in preview state
      if (migration.isValidated.value) {
        await migration.cancelMigration()
      } else {
        migration.reset()
      }
      emit('close')
    }

    // Handle backdrop click
    const handleBackdropClick = () => {
      if (!migration.isImporting.value) {
        handleClose()
      }
    }

    // Format date for preview
    const formatDate = (timestamp) => {
      if (!timestamp) return ''
      try {
        const date = new Date(timestamp)
        return date.toLocaleDateString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric'
        })
      } catch {
        return timestamp
      }
    }

    // Format confidence for preview
    const formatConfidence = (confidence) => {
      if (confidence === undefined || confidence === null) return ''
      return `${Math.round(confidence * 100)}%`
    }

    // Cleanup on unmount
    onUnmounted(() => {
      // Note: Don't cancel migration on unmount - let it continue in background
      // Just stop polling
      migration.reset()
    })

    return {
      migration,
      isDragging,
      fileInput,
      currentStep,
      hasErrors,
      handleDrop,
      handleFileSelect,
      handleImport,
      handleCancel,
      handleDone,
      handleClose,
      handleBackdropClick,
      formatDate,
      formatConfidence
    }
  }
}
</script>
