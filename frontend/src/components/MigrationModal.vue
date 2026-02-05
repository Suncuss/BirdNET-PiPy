<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <!-- Backdrop -->
    <div class="fixed inset-0 bg-black bg-opacity-50 transition-opacity" />

    <!-- Modal -->
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-lg w-full p-6 min-h-[420px] flex flex-col">
        <!-- Close button -->
        <button
          v-if="!isProcessing"
          class="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          @click="handleClose"
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

        <!-- Stage indicator -->
        <div
          v-if="currentStep !== 'spectrogram_result'"
          class="flex justify-center mb-4"
        >
          <div class="flex items-center space-x-2 text-xs text-gray-500">
            <span :class="stage === 'db' ? 'text-green-600 font-medium' : ''">Database</span>
            <span class="text-gray-300">></span>
            <span :class="stage === 'audio' ? 'text-green-600 font-medium' : ''">Audio</span>
            <span class="text-gray-300">></span>
            <span :class="stage === 'spectrogram' ? 'text-green-600 font-medium' : ''">Spectrograms</span>
          </div>
        </div>

        <!-- Main content area (flex-grow to fill space) -->
        <div class="flex-grow flex flex-col">
          <!-- ================================================================ -->
          <!-- STAGE 1: DATABASE IMPORT -->
          <!-- ================================================================ -->

          <!-- Step 1: Upload -->
          <div
            v-if="currentStep === 'upload'"
            class="flex flex-col flex-grow"
          >
            <!-- Header -->
            <div class="text-center mb-4">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Import from BirdNET-Pi
              </h2>
              <p class="mt-1 text-sm text-gray-600">
                Upload your <code class="bg-gray-100 px-1 rounded">birds.db</code> file to import detections.
              </p>
            </div>

            <!-- Error message -->
            <div
              v-if="migration.error.value"
              class="mb-3 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
            >
              {{ migration.error.value }}
            </div>

            <!-- Drop zone -->
            <div class="flex-grow flex flex-col">
              <div
                :class="[
                  'border-2 border-dashed rounded-lg p-6 text-center transition-colors flex-grow flex flex-col justify-center',
                  isDragging ? 'border-green-400 bg-green-50' : 'border-gray-300 hover:border-gray-400'
                ]"
                @dragover.prevent="isDragging = true"
                @dragleave.prevent="isDragging = false"
                @drop.prevent="handleDrop"
              >
                <input
                  ref="fileInput"
                  type="file"
                  accept=".db"
                  class="hidden"
                  @change="handleFileSelect"
                >

                <div
                  v-if="migration.isUploading.value"
                  class="relative flex-grow"
                >
                  <!-- Center the bar itself -->
                  <div class="absolute left-1/2 top-1/2 w-full max-w-xs -translate-x-1/2 -translate-y-1/2">
                    <div class="w-full bg-gray-200 rounded-full h-3">
                      <div
                        class="bg-green-600 h-3 rounded-full transition-all duration-300"
                        :style="{ width: `${migration.uploadProgress.value}%` }"
                      />
                    </div>
                  </div>
                  <!-- Text just below the centered bar -->
                  <p class="absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-4 text-sm text-gray-600 text-center">
                    Uploading... {{ migration.uploadProgress.value }}%
                  </p>
                </div>

                <div v-else>
                  <svg
                    class="mx-auto h-10 w-10 text-gray-400 mb-2"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="1"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"
                    />
                  </svg>
                  <p class="text-sm text-gray-600 mb-1">
                    Drag and drop <code class="bg-gray-100 px-1 rounded">birds.db</code> here
                  </p>
                  <p class="text-xs text-gray-500 mb-2">
                    or
                  </p>
                  <button
                    class="px-4 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                    @click="$refs.fileInput.click()"
                  >
                    Browse Files
                  </button>
                </div>
              </div>
            </div>

            <!-- Help text -->
            <p class="mt-3 text-xs text-gray-500 text-center">
              Located at <code class="bg-gray-100 px-1 rounded">~/BirdNET-Pi/scripts/birds.db</code> on your BirdNET-Pi.
            </p>
          </div>

          <!-- Step 2: Preview -->
          <div
            v-else-if="currentStep === 'preview'"
            class="flex flex-col flex-grow"
          >
            <!-- Header -->
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Ready to Import
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Review the import summary below before proceeding.
              </p>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 mb-4">
              <div class="text-center">
                <p class="text-2xl font-bold text-gray-900">
                  {{ migration.recordCount.value.toLocaleString() }}
                </p>
                <p class="text-xs text-gray-500">
                  Total Records
                </p>
              </div>
              <p class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
                Duplicate records will be automatically skipped during import.
              </p>
            </div>

            <!-- Preview table -->
            <div
              v-if="migration.previewRecords.value.length > 0"
              class="mb-4 flex-grow overflow-auto"
            >
              <p class="text-sm font-medium text-gray-700 mb-2">
                Sample Records:
              </p>
              <div class="border rounded-lg overflow-hidden">
                <table class="min-w-full divide-y divide-gray-200 text-sm">
                  <thead class="bg-gray-50">
                    <tr>
                      <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">
                        Species
                      </th>
                      <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">
                        Date
                      </th>
                      <th class="px-3 py-2 text-right text-xs font-medium text-gray-500">
                        Confidence
                      </th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-200">
                    <tr
                      v-for="(record, index) in migration.previewRecords.value.slice(0, 5)"
                      :key="index"
                    >
                      <td class="px-3 py-2 text-gray-900">
                        {{ record.common_name }}
                      </td>
                      <td class="px-3 py-2 text-gray-600">
                        {{ formatDate(record.timestamp) }}
                      </td>
                      <td class="px-3 py-2 text-right text-gray-600">
                        {{ formatConfidence(record.confidence) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Error message -->
            <div
              v-if="migration.error.value"
              class="mb-4 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
            >
              {{ migration.error.value }}
            </div>

            <!-- Buttons -->
            <div class="flex gap-3 mt-auto">
              <button
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
                @click="handleCancel"
              >
                Cancel
              </button>
              <button
                class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="handleImport"
              >
                Import
              </button>
            </div>
          </div>

          <!-- Step 3: Importing (Progress) -->
          <div
            v-else-if="currentStep === 'importing'"
            class="flex flex-col flex-grow"
          >
            <!-- Header -->
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600 animate-pulse"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Importing Records
              </h2>
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
                  class="bg-green-600 h-3 rounded-full transition-all duration-300"
                  :style="{ width: `${migration.importProgressPercent.value}%` }"
                />
              </div>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 flex-grow flex flex-col justify-center">
              <div class="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p class="text-lg font-bold text-green-600">
                    {{ migration.importProgress.value.imported.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Imported
                  </p>
                </div>
                <div>
                  <p class="text-lg font-bold text-gray-500">
                    {{ migration.importProgress.value.skipped.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Duplicates Skipped
                  </p>
                </div>
                <div>
                  <p
                    class="text-lg font-bold"
                    :class="migration.importProgress.value.errors > 0 ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.importProgress.value.errors.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
              <div class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
                {{ migration.importProgress.value.processed.toLocaleString() }} / {{ migration.importProgress.value.total.toLocaleString() }} records processed
              </div>
            </div>
          </div>

          <!-- Step 4: Database Import Result -->
          <div
            v-else-if="currentStep === 'db_result'"
            class="flex flex-col flex-grow"
          >
            <!-- Success Header -->
            <div
              v-if="!hasDbErrors && !migration.importResult.value?.warning"
              class="text-center mb-6"
            >
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M4.5 12.75l6 6 9-13.5"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Database Import Complete
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Your BirdNET-Pi records have been imported successfully.
              </p>
            </div>

            <!-- Status Expired Warning Header -->
            <div
              v-else-if="migration.importResult.value?.warning"
              class="text-center mb-4"
            >
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-amber-100 mb-3">
                <svg
                  class="h-5 w-5 text-amber-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Import Status Unknown
              </h2>
              <p class="mt-1 text-sm text-gray-600">
                {{ migration.importResult.value.warning }}
              </p>
            </div>

            <!-- Partial Success Header -->
            <div
              v-else
              class="text-center mb-4"
            >
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-amber-100 mb-3">
                <svg
                  class="h-5 w-5 text-amber-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Import Completed with Warnings
              </h2>
              <p class="mt-1 text-sm text-gray-600">
                Some records could not be imported.
              </p>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 mb-4 flex-grow flex items-center justify-center">
              <div class="grid grid-cols-3 gap-4 text-center w-full">
                <div>
                  <p class="text-2xl font-bold text-green-600">
                    {{ migration.importResult.value?.imported?.toLocaleString() || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Imported
                  </p>
                </div>
                <div>
                  <p class="text-2xl font-bold text-gray-600">
                    {{ migration.importResult.value?.skipped?.toLocaleString() || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Duplicates Skipped
                  </p>
                </div>
                <div>
                  <p
                    class="text-2xl font-bold"
                    :class="hasDbErrors ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.importResult.value?.errors || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
            </div>

            <!-- Buttons -->
            <div class="flex flex-col sm:flex-row gap-3 mt-auto">
              <button
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
                @click="handleDone"
              >
                Finish & Exit
              </button>
              <button
                class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="continueToAudio"
              >
                Continue to Audio Import
              </button>
            </div>
          </div>

          <!-- ================================================================ -->
          <!-- STAGE 2: AUDIO IMPORT -->
          <!-- ================================================================ -->

          <!-- Audio Prompt -->
          <div
            v-else-if="currentStep === 'audio_prompt'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-4">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Import Audio Files
              </h2>
              <p class="mt-1 text-sm text-gray-600">
                Import your BirdNET-Pi audio recordings.
              </p>
            </div>

            <!-- Instructions (only show before scan) -->
            <div
              v-if="!migration.audioScanResult.value"
              class="bg-green-50 rounded-lg p-3 mb-3 text-sm"
            >
              <p class="font-medium text-green-800 mb-1">
                To import audio files:
              </p>
              <ol class="list-decimal list-inside text-green-700 space-y-0.5 text-xs">
                <li>Find <code class="bg-white px-1 rounded">~/BirdSongs/Extracted/By_Date</code> on your BirdNET-Pi</li>
                <li>Copy to <code class="bg-white px-1 rounded">~/BirdNET-PiPy/data</code> on this system</li>
                <li>Select the folder below and click Scan</li>
              </ol>
            </div>

            <!-- Scan result (with folder selector inside) -->
            <div
              v-if="migration.audioScanResult.value"
              class="bg-gray-50 rounded-lg p-4 mb-3 flex-grow flex flex-col"
            >
              <!-- Folder selector at top -->
              <div class="mb-4">
                <label class="block text-xs font-medium text-gray-500 mb-1">Source folder:</label>
                <div class="flex gap-2">
                  <select
                    v-model="migration.selectedFolder.value"
                    class="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                    :disabled="migration.isLoadingFolders.value || migration.isAudioScanning.value"
                    @change="handleFolderChange"
                  >
                    <option
                      v-if="migration.availableFolders.value.length === 0"
                      :value="null"
                    >
                      {{ migration.isLoadingFolders.value ? 'Loading...' : 'No folders found' }}
                    </option>
                    <option
                      v-for="folder in migration.availableFolders.value"
                      :key="folder.path"
                      :value="folder.path"
                    >
                      {{ folder.name }} ({{ folder.audio_count }} files)
                    </option>
                  </select>
                  <button
                    :disabled="migration.isLoadingFolders.value"
                    class="px-3 py-2 text-gray-600 hover:bg-gray-200 border border-gray-300 rounded-lg transition-colors disabled:opacity-50 bg-white"
                    title="Refresh folder list"
                    @click="handleRefreshFolders"
                  >
                    <svg
                      class="w-5 h-5"
                      :class="{ 'animate-spin': migration.isLoadingFolders.value }"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                      />
                    </svg>
                  </button>
                </div>
              </div>

              <!-- Stats centered -->
              <div class="flex-grow flex flex-col justify-center">
                <div
                  v-if="migration.audioScanResult.value.matched_count === 0"
                  class="text-center text-gray-600"
                >
                  <p class="text-sm">
                    No matching audio files found.
                  </p>
                  <p class="text-xs mt-1">
                    Ensure files match your imported database records.
                  </p>
                </div>
                <div v-else>
                  <div class="grid grid-cols-2 gap-3 text-center">
                    <div>
                      <p class="text-2xl font-bold text-green-600">
                        {{ migration.audioScanResult.value.matched_count.toLocaleString() }}
                      </p>
                      <p class="text-xs text-gray-500">
                        Files Found
                      </p>
                    </div>
                    <div>
                      <p class="text-2xl font-bold text-gray-500">
                        {{ formatBytes(migration.audioScanResult.value.total_size_bytes) }}
                      </p>
                      <p class="text-xs text-gray-500">
                        Total Size
                      </p>
                    </div>
                  </div>
                  <!-- Disk space warning -->
                  <div
                    v-if="!migration.audioScanResult.value.disk_usage.has_enough_space"
                    class="mt-3 p-2 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-xs rounded"
                  >
                    Not enough disk space for import.
                  </div>
                </div>
              </div>
            </div>

            <!-- Folder selection (before scan) -->
            <div
              v-if="!migration.audioScanResult.value"
              class="mb-3"
            >
              <label class="block text-sm font-medium text-gray-700 mb-1">Select audio folder:</label>
              <div class="flex gap-2">
                <select
                  v-model="migration.selectedFolder.value"
                  class="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  :disabled="migration.isLoadingFolders.value || migration.isAudioScanning.value"
                  @change="handleFolderChange"
                >
                  <option
                    v-if="migration.availableFolders.value.length === 0"
                    :value="null"
                  >
                    {{ migration.isLoadingFolders.value ? 'Loading...' : 'No folders found' }}
                  </option>
                  <option
                    v-for="folder in migration.availableFolders.value"
                    :key="folder.path"
                    :value="folder.path"
                  >
                    {{ folder.name }} ({{ folder.audio_count }} files)
                  </option>
                </select>
                <button
                  :disabled="migration.isLoadingFolders.value"
                  class="px-3 py-2 text-gray-600 hover:bg-gray-100 border border-gray-300 rounded-lg transition-colors disabled:opacity-50"
                  title="Refresh folder list"
                  @click="handleRefreshFolders"
                >
                  <svg
                    class="w-5 h-5"
                    :class="{ 'animate-spin': migration.isLoadingFolders.value }"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    />
                  </svg>
                </button>
              </div>
            </div>

            <!-- No folders message -->
            <div
              v-if="!migration.audioScanResult.value && !migration.isLoadingFolders.value && migration.availableFolders.value.length === 0"
              class="bg-gray-50 rounded-lg p-3 mb-3 flex-grow flex flex-col justify-center text-center text-gray-600"
            >
              <p class="text-sm">
                No folders with audio files found.
              </p>
              <p class="text-xs mt-1">
                Copy your files to the data folder and refresh.
              </p>
            </div>

            <!-- Spacer when no results and has folders -->
            <div
              v-if="!migration.audioScanResult.value && migration.availableFolders.value.length > 0"
              class="flex-grow"
            />

            <!-- Error message -->
            <div
              v-if="migration.error.value"
              class="mb-3 p-2 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
            >
              {{ migration.error.value }}
            </div>

            <!-- Buttons -->
            <div class="mt-auto">
              <button
                v-if="!migration.audioScanResult.value || migration.audioScanResult.value.matched_count === 0"
                :disabled="migration.isAudioScanning.value || !migration.selectedFolder.value"
                class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors disabled:opacity-50"
                @click="handleScanAudio"
              >
                {{ migration.isAudioScanning.value ? 'Scanning...' : 'Scan for Files' }}
              </button>
              <button
                v-else-if="migration.audioScanResult.value.disk_usage.has_enough_space"
                class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="handleAudioImport"
              >
                Import Files
              </button>
            </div>
          </div>

          <!-- Audio Importing -->
          <div
            v-else-if="currentStep === 'audio_importing'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600 animate-pulse"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Importing Audio Files
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Please wait while your audio files are being imported...
              </p>
            </div>

            <!-- Progress bar -->
            <div class="mb-4">
              <div class="flex justify-between text-sm text-gray-600 mb-2">
                <span>Progress</span>
                <span>{{ migration.audioImportProgressPercent.value }}%</span>
              </div>
              <div class="w-full bg-gray-200 rounded-full h-3">
                <div
                  class="bg-green-600 h-3 rounded-full transition-all duration-300"
                  :style="{ width: `${migration.audioImportProgressPercent.value}%` }"
                />
              </div>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 flex-grow flex flex-col justify-center">
              <div class="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p class="text-lg font-bold text-green-600">
                    {{ migration.audioImportProgress.value.imported.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Imported
                  </p>
                </div>
                <div>
                  <p class="text-lg font-bold text-gray-500">
                    {{ migration.audioImportProgress.value.skipped.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Skipped
                  </p>
                </div>
                <div>
                  <p
                    class="text-lg font-bold"
                    :class="migration.audioImportProgress.value.errors > 0 ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.audioImportProgress.value.errors.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
              <div class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
                {{ migration.audioImportProgress.value.processed.toLocaleString() }} / {{ migration.audioImportProgress.value.total.toLocaleString() }} files processed
              </div>
            </div>
          </div>

          <!-- Audio Import Result -->
          <div
            v-else-if="currentStep === 'audio_result'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M4.5 12.75l6 6 9-13.5"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Audio Import Complete
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Your audio files have been imported.
              </p>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 mb-4 flex-grow flex items-center justify-center">
              <div class="grid grid-cols-3 gap-4 text-center w-full">
                <div>
                  <p class="text-2xl font-bold text-green-600">
                    {{ migration.audioImportResult.value?.imported?.toLocaleString() || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Imported
                  </p>
                </div>
                <div>
                  <p class="text-2xl font-bold text-gray-600">
                    {{ migration.audioImportResult.value?.skipped?.toLocaleString() || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Skipped
                  </p>
                </div>
                <div>
                  <p
                    class="text-2xl font-bold"
                    :class="(migration.audioImportResult.value?.errors || 0) > 0 ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.audioImportResult.value?.errors || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
            </div>

            <!-- Buttons -->
            <div class="flex flex-col sm:flex-row gap-3 mt-auto">
              <button
                class="flex-1 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
                @click="handleDone"
              >
                Finish & Exit
              </button>
              <button
                class="flex-1 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="continueToSpectrogram"
              >
                Continue to Spectrograms
              </button>
            </div>
          </div>

          <!-- ================================================================ -->
          <!-- STAGE 3: SPECTROGRAM GENERATION -->
          <!-- ================================================================ -->

          <!-- Spectrogram Prompt -->
          <div
            v-else-if="currentStep === 'spectrogram_prompt'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-4">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Generate Spectrograms
              </h2>
              <p class="mt-1 text-sm text-gray-600">
                Create visual waveforms for your imported audio files.
              </p>
            </div>

            <!-- Scan result -->
            <div
              v-if="migration.spectrogramScanResult.value"
              class="bg-gray-50 rounded-lg p-4 mb-4 flex-grow flex flex-col justify-center"
            >
              <div
                v-if="migration.spectrogramScanResult.value.count === 0"
                class="text-center text-gray-600"
              >
                <p class="text-sm">
                  All audio files already have spectrograms.
                </p>
              </div>
              <div v-else>
                <div class="grid grid-cols-2 gap-4 text-center">
                  <div>
                    <p class="text-2xl font-bold text-green-600">
                      {{ migration.spectrogramScanResult.value.count.toLocaleString() }}
                    </p>
                    <p class="text-xs text-gray-500">
                      Files Need Spectrograms
                    </p>
                  </div>
                  <div>
                    <p class="text-2xl font-bold text-gray-500">
                      ~{{ formatBytes(migration.spectrogramScanResult.value.estimated_size_bytes) }}
                    </p>
                    <p class="text-xs text-gray-500">
                      Estimated Size
                    </p>
                  </div>
                </div>
                <!-- Time warning -->
                <p class="mt-4 text-xs text-amber-600 text-center">
                  Note: Generation may take a while depending on the number of files.
                </p>
                <!-- Disk space warning -->
                <div
                  v-if="!migration.spectrogramScanResult.value.disk_usage.has_enough_space"
                  class="mt-3 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
                >
                  Not enough disk space. Generation would use too much storage.
                </div>
              </div>
            </div>

            <!-- Pre-scan info -->
            <div
              v-else
              class="bg-gray-50 rounded-lg p-4 mb-4 flex-grow flex flex-col justify-center text-center"
            >
              <p class="text-2xl font-bold text-gray-600 mb-1">
                {{ migration.audioImportResult.value?.imported?.toLocaleString() || 0 }}
              </p>
              <p class="text-xs text-gray-500 mb-3">
                Audio Files Imported
              </p>
              <p class="text-sm text-gray-600">
                Click below to check how many files need spectrograms.
              </p>
              <p class="text-xs text-gray-500 mt-2">
                Generation may take a while for large collections.
              </p>
            </div>

            <!-- Error message -->
            <div
              v-if="migration.error.value"
              class="mb-4 p-3 bg-amber-50 border-l-4 border-amber-400 text-amber-800 text-sm rounded"
            >
              {{ migration.error.value }}
            </div>

            <!-- Buttons -->
            <div class="mt-auto">
              <button
                v-if="!migration.spectrogramScanResult.value"
                :disabled="migration.isSpectrogramScanning.value"
                class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors disabled:opacity-50"
                @click="handleScanSpectrograms"
              >
                {{ migration.isSpectrogramScanning.value ? 'Scanning...' : 'Check Files' }}
              </button>
              <button
                v-else-if="migration.spectrogramScanResult.value.count === 0"
                class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="handleDone"
              >
                Finish
              </button>
              <button
                v-else-if="migration.spectrogramScanResult.value.disk_usage.has_enough_space"
                class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                @click="handleGenerateSpectrograms"
              >
                Generate
              </button>
            </div>
          </div>

          <!-- Spectrogram Generating -->
          <div
            v-else-if="currentStep === 'spectrogram_generating'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600 animate-pulse"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Generating Spectrograms
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Please wait while spectrograms are being generated...
              </p>
            </div>

            <!-- Progress bar -->
            <div class="mb-4">
              <div class="flex justify-between text-sm text-gray-600 mb-2">
                <span>Progress</span>
                <span>{{ migration.spectrogramProgressPercent.value }}%</span>
              </div>
              <div class="w-full bg-gray-200 rounded-full h-3">
                <div
                  class="bg-green-600 h-3 rounded-full transition-all duration-300"
                  :style="{ width: `${migration.spectrogramProgressPercent.value}%` }"
                />
              </div>
            </div>

            <!-- Statistics -->
            <div class="bg-gray-50 rounded-lg p-4 flex-grow flex flex-col justify-center">
              <div class="grid grid-cols-2 gap-4 text-center">
                <div>
                  <p class="text-lg font-bold text-green-600">
                    {{ migration.spectrogramProgress.value.generated.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Generated
                  </p>
                </div>
                <div>
                  <p
                    class="text-lg font-bold"
                    :class="migration.spectrogramProgress.value.errors > 0 ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.spectrogramProgress.value.errors.toLocaleString() }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
              <div class="mt-3 pt-3 border-t border-gray-200 text-center text-xs text-gray-500">
                {{ migration.spectrogramProgress.value.processed.toLocaleString() }} / {{ migration.spectrogramProgress.value.total.toLocaleString() }} files processed
              </div>
            </div>
          </div>

          <!-- Spectrogram Result / Final Done -->
          <div
            v-else-if="currentStep === 'spectrogram_result'"
            class="flex flex-col flex-grow"
          >
            <div class="text-center mb-6">
              <div class="mx-auto flex items-center justify-center h-10 w-10 rounded-full bg-green-100 mb-3">
                <svg
                  class="h-5 w-5 text-green-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
              <h2 class="text-xl font-semibold text-gray-900">
                Migration Complete
              </h2>
              <p class="mt-2 text-sm text-gray-600">
                Your BirdNET-Pi data has been imported successfully.
              </p>
            </div>

            <!-- Spectrogram stats if available -->
            <div
              v-if="migration.spectrogramResult.value"
              class="bg-gray-50 rounded-lg p-4 mb-4 flex-grow flex items-center justify-center"
            >
              <div class="grid grid-cols-2 gap-4 text-center w-full">
                <div>
                  <p class="text-2xl font-bold text-green-600">
                    {{ migration.spectrogramResult.value?.generated?.toLocaleString() || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Spectrograms Generated
                  </p>
                </div>
                <div>
                  <p
                    class="text-2xl font-bold"
                    :class="(migration.spectrogramResult.value?.errors || 0) > 0 ? 'text-amber-600' : 'text-gray-400'"
                  >
                    {{ migration.spectrogramResult.value?.errors || 0 }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Errors
                  </p>
                </div>
              </div>
            </div>

            <!-- Spacer when no results -->
            <div
              v-else
              class="flex-grow"
            />

            <button
              class="w-full py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors mt-auto"
              @click="handleDone"
            >
              Done
            </button>
          </div>
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
    const stage = ref('db') // 'db' | 'audio' | 'spectrogram'

    // Check if any processing is happening (disable close)
    const isProcessing = computed(() => {
      return migration.isImporting.value ||
             migration.isAudioImporting.value ||
             migration.isSpectrogramGenerating.value
    })

    // Current step based on stage and state
    const currentStep = computed(() => {
      // Stage 3: Spectrogram
      if (stage.value === 'spectrogram') {
        if (migration.spectrogramResult.value) return 'spectrogram_result'
        if (migration.isSpectrogramGenerating.value) return 'spectrogram_generating'
        return 'spectrogram_prompt'
      }

      // Stage 2: Audio
      if (stage.value === 'audio') {
        if (migration.audioImportResult.value) return 'audio_result'
        if (migration.isAudioImporting.value) return 'audio_importing'
        return 'audio_prompt'
      }

      // Stage 1: Database
      if (migration.importResult.value) return 'db_result'
      if (migration.isImporting.value) return 'importing'
      if (migration.isValidated.value) return 'preview'
      return 'upload'
    })

    // Check if database import had errors
    const hasDbErrors = computed(() => {
      return (migration.importResult.value?.errors || 0) > 0
    })

    // Format helpers
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

    const formatConfidence = (confidence) => {
      if (confidence === undefined || confidence === null) return ''
      return `${Math.round(confidence * 100)}%`
    }

    const formatBytes = (bytes) => {
      if (!bytes) return '0 B'
      const units = ['B', 'KB', 'MB', 'GB']
      let size = bytes
      let unitIndex = 0
      while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024
        unitIndex++
      }
      return `${size.toFixed(1)} ${units[unitIndex]}`
    }

    // Stage 1 handlers
    const handleDrop = (event) => {
      isDragging.value = false
      const files = event.dataTransfer.files
      if (files.length > 0) {
        processFile(files[0])
      }
    }

    const handleFileSelect = (event) => {
      const files = event.target.files
      if (files.length > 0) {
        processFile(files[0])
      }
      event.target.value = ''
    }

    const processFile = async (file) => {
      migration.clearError()
      await migration.validateFile(file)
    }

    const handleImport = async () => {
      await migration.runImport(true)
    }

    const handleCancel = async () => {
      await migration.cancelMigration()
    }

    // Stage transitions
    const continueToAudio = async () => {
      stage.value = 'audio'
      migration.clearError()
      // Load available folders when entering audio stage
      await migration.loadAvailableFolders()
    }

    const continueToSpectrogram = () => {
      stage.value = 'spectrogram'
      migration.clearError()
    }

    // Stage 2 handlers
    const handleRefreshFolders = async () => {
      migration.clearError()
      await migration.loadAvailableFolders()
    }

    const handleFolderChange = () => {
      // Clear previous scan result when folder changes
      migration.audioScanResult.value = null
      migration.clearError()
    }

    const handleScanAudio = async () => {
      migration.clearError()
      await migration.scanAudioFiles()
    }

    const handleAudioImport = async () => {
      migration.clearError()
      await migration.runAudioImport()
    }

    // Stage 3 handlers
    const handleScanSpectrograms = async () => {
      migration.clearError()
      await migration.scanSpectrograms()
    }

    const handleGenerateSpectrograms = async () => {
      migration.clearError()
      await migration.runSpectrogramGeneration()
    }

    // General handlers
    const handleDone = () => {
      migration.reset()
      emit('close')
    }

    const handleClose = async () => {
      if (isProcessing.value) return

      if (migration.isValidated.value) {
        await migration.cancelMigration()
      } else {
        migration.reset()
      }
      emit('close')
    }

    // Cleanup on unmount
    onUnmounted(() => {
      migration.reset()
    })

    return {
      migration,
      isDragging,
      fileInput,
      stage,
      currentStep,
      isProcessing,
      hasDbErrors,
      handleDrop,
      handleFileSelect,
      handleImport,
      handleCancel,
      handleDone,
      handleClose,
      formatDate,
      formatConfidence,
      formatBytes,
      // Stage transitions
      continueToAudio,
      continueToSpectrogram,
      // Stage 2
      handleRefreshFolders,
      handleFolderChange,
      handleScanAudio,
      handleAudioImport,
      // Stage 3
      handleScanSpectrograms,
      handleGenerateSpectrograms
    }
  }
}
</script>
