import { ref, computed } from 'vue'
import { useLogger } from './useLogger'
import api, { createLongRequest } from '@/services/api'

/**
 * Create a polling helper for background job status tracking.
 *
 * @param {Object} config - Polling configuration
 * @param {string} config.endpoint - API endpoint path (e.g., '/migration/status')
 * @param {string} config.idParamName - Query parameter name for job ID (e.g., 'migration_id')
 * @param {Function} config.getJobId - Function that returns current job ID
 * @param {Object} config.progressRef - Vue ref for progress state
 * @param {Object} config.resultRef - Vue ref for final result
 * @param {Object} config.isProcessingRef - Vue ref for processing state (boolean)
 * @param {Object} config.errorRef - Vue ref for error messages
 * @param {Function} config.mapProgress - Function to map API response to progress object
 * @param {Function} config.mapResult - Function to map API response to result object
 * @param {Function} config.mapExpiredResult - Function to map last progress to expired result
 * @param {string} config.expiredErrorMessage - Error message when status not found
 * @param {string} config.logPrefix - Prefix for log messages
 * @param {Object} config.logger - Logger instance
 * @param {Function} [config.onComplete] - Optional callback when job completes successfully
 * @param {Function} [config.onExpired] - Optional callback when status expires with progress
 * @returns {Object} - { poll, startPolling, stopPolling }
 */
function createPollingHelper(config) {
  let pollIntervalId = null

  const stopPolling = () => {
    if (pollIntervalId) {
      clearInterval(pollIntervalId)
      pollIntervalId = null
    }
  }

  const poll = async () => {
    const jobId = config.getJobId()
    if (!jobId) return

    try {
      const response = await api.get(config.endpoint, {
        params: { [config.idParamName]: jobId }
      })

      const status = response.data
      config.progressRef.value = config.mapProgress(status)

      if (status.status === 'completed') {
        stopPolling()
        config.isProcessingRef.value = false
        config.resultRef.value = config.mapResult(status)
        config.logger.info(`${config.logPrefix} completed`, config.resultRef.value)
        config.onComplete?.()

      } else if (status.status === 'failed') {
        stopPolling()
        config.isProcessingRef.value = false
        config.errorRef.value = status.error || `${config.logPrefix} failed`
        config.logger.error(`${config.logPrefix} failed`, { error: status.error })
      }

    } catch (err) {
      if (err.response?.status === 404) {
        stopPolling()
        config.isProcessingRef.value = false

        if (config.progressRef.value.processed > 0) {
          config.resultRef.value = config.mapExpiredResult(config.progressRef.value)
          config.logger.warn(`${config.logPrefix} status expired, showing last known progress`, config.resultRef.value)
          config.onExpired?.()
        } else {
          config.errorRef.value = config.expiredErrorMessage
          config.logger.error(`${config.logPrefix} not found and no progress recorded`)
        }
        return
      }
      config.logger.warn(`${config.logPrefix} status poll failed`, { error: err.message })
    }
  }

  const startPolling = () => {
    if (pollIntervalId) return
    pollIntervalId = setInterval(poll, 1000)
  }

  return { poll, startPolling, stopPolling }
}

/**
 * Composable for BirdNET-Pi database migration.
 *
 * Handles the workflow of:
 * 1. Stage 1 (DB): Uploading and validating a BirdNET-Pi birds.db file
 * 2. Stage 2 (Audio): Importing audio files from migration folder
 * 3. Stage 3 (Spectrogram): Generating spectrograms for imported audio
 */
export function useMigration() {
  const logger = useLogger('useMigration')

  // ==========================================================================
  // Stage 1: Database Import State
  // ==========================================================================
  const isUploading = ref(false)
  const isImporting = ref(false)
  const validationResult = ref(null)
  const importResult = ref(null)
  const error = ref('')

  // Progress tracking
  const uploadProgress = ref(0) // 0-100
  const importProgress = ref({
    processed: 0,
    total: 0,
    imported: 0,
    skipped: 0,
    errors: 0,
    status: null
  })

  // Job IDs for polling
  let migrationId = null

  // Computed properties
  const isValidated = computed(() => validationResult.value?.valid === true)
  const recordCount = computed(() => validationResult.value?.record_count ?? 0)
  const previewRecords = computed(() => validationResult.value?.preview ?? [])

  const importProgressPercent = computed(() => {
    if (!importProgress.value.total) return 0
    return Math.round((importProgress.value.processed / importProgress.value.total) * 100)
  })

  // ==========================================================================
  // Stage 2: Audio Import State
  // ==========================================================================
  const availableFolders = ref([])
  const selectedFolder = ref(null)
  const isLoadingFolders = ref(false)
  const audioScanResult = ref(null)
  const isAudioScanning = ref(false)
  const isAudioImporting = ref(false)
  const audioImportProgress = ref({
    processed: 0,
    total: 0,
    imported: 0,
    skipped: 0,
    errors: 0,
    status: null
  })
  const audioImportResult = ref(null)

  let audioImportId = null

  const audioImportProgressPercent = computed(() => {
    if (!audioImportProgress.value.total) return 0
    return Math.round((audioImportProgress.value.processed / audioImportProgress.value.total) * 100)
  })

  // ==========================================================================
  // Stage 3: Spectrogram Generation State
  // ==========================================================================
  const spectrogramScanResult = ref(null)
  const isSpectrogramScanning = ref(false)
  const isSpectrogramGenerating = ref(false)
  const spectrogramProgress = ref({
    processed: 0,
    total: 0,
    generated: 0,
    errors: 0,
    status: null
  })
  const spectrogramResult = ref(null)

  let spectrogramGenerationId = null

  const spectrogramProgressPercent = computed(() => {
    if (!spectrogramProgress.value.total) return 0
    return Math.round((spectrogramProgress.value.processed / spectrogramProgress.value.total) * 100)
  })

  // ==========================================================================
  // Polling Helpers (shared logic for all stages)
  // ==========================================================================

  // Database import polling
  const dbPolling = createPollingHelper({
    endpoint: '/migration/status',
    idParamName: 'migration_id',
    getJobId: () => migrationId,
    progressRef: importProgress,
    resultRef: importResult,
    isProcessingRef: isImporting,
    errorRef: error,
    mapProgress: (status) => ({
      processed: status.processed || 0,
      total: status.total || 0,
      imported: status.imported || 0,
      skipped: status.skipped || 0,
      errors: status.errors || 0,
      status: status.status
    }),
    mapResult: (status) => ({
      imported: status.imported,
      skipped: status.skipped,
      errors: status.errors
    }),
    mapExpiredResult: (progress) => ({
      imported: progress.imported,
      skipped: progress.skipped,
      errors: progress.errors,
      warning: 'Migration status expired. These are the last known counts.'
    }),
    expiredErrorMessage: 'Migration status not found. The import may have failed or completed. Please check your data.',
    logPrefix: 'Import',
    logger,
    onComplete: () => { validationResult.value = null },
    onExpired: () => { validationResult.value = null }
  })

  // Audio import polling
  const audioPolling = createPollingHelper({
    endpoint: '/migration/audio/status',
    idParamName: 'import_id',
    getJobId: () => audioImportId,
    progressRef: audioImportProgress,
    resultRef: audioImportResult,
    isProcessingRef: isAudioImporting,
    errorRef: error,
    mapProgress: (status) => ({
      processed: status.processed || 0,
      total: status.total || 0,
      imported: status.imported || 0,
      skipped: status.skipped || 0,
      errors: status.errors || 0,
      status: status.status
    }),
    mapResult: (status) => ({
      imported: status.imported,
      skipped: status.skipped,
      errors: status.errors
    }),
    mapExpiredResult: (progress) => ({
      imported: progress.imported,
      skipped: progress.skipped,
      errors: progress.errors,
      warning: 'Import status expired. These are the last known counts.'
    }),
    expiredErrorMessage: 'Audio import status not found.',
    logPrefix: 'Audio import',
    logger
  })

  // Spectrogram generation polling
  const spectrogramPolling = createPollingHelper({
    endpoint: '/migration/spectrogram/status',
    idParamName: 'generation_id',
    getJobId: () => spectrogramGenerationId,
    progressRef: spectrogramProgress,
    resultRef: spectrogramResult,
    isProcessingRef: isSpectrogramGenerating,
    errorRef: error,
    mapProgress: (status) => ({
      processed: status.processed || 0,
      total: status.total || 0,
      generated: status.generated || 0,
      errors: status.errors || 0,
      status: status.status
    }),
    mapResult: (status) => ({
      generated: status.generated,
      errors: status.errors
    }),
    mapExpiredResult: (progress) => ({
      generated: progress.generated,
      errors: progress.errors,
      warning: 'Generation status expired. These are the last known counts.'
    }),
    expiredErrorMessage: 'Spectrogram generation status not found.',
    logPrefix: 'Spectrogram generation',
    logger
  })

  // Aliases for compatibility
  const startPolling = dbPolling.startPolling
  const stopPolling = dbPolling.stopPolling
  const startAudioImportPolling = audioPolling.startPolling
  const stopAudioImportPolling = audioPolling.stopPolling
  const startSpectrogramPolling = spectrogramPolling.startPolling
  const stopSpectrogramPolling = spectrogramPolling.stopPolling

  // ==========================================================================
  // Stage 1: Database Import Methods
  // ==========================================================================

  /**
   * Upload and validate a BirdNET-Pi database file.
   *
   * @param {File} file - The birds.db file to validate
   * @returns {Promise<boolean>} - True if validation successful
   */
  const validateFile = async (file) => {
    isUploading.value = true
    uploadProgress.value = 0
    error.value = ''
    validationResult.value = null
    importResult.value = null

    try {
      // Create form data with file
      const formData = new FormData()
      formData.append('file', file)

      // Use long timeout for large file uploads and validation
      const longApi = createLongRequest()
      const response = await longApi.post('/migration/validate', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            uploadProgress.value = Math.round((progressEvent.loaded / progressEvent.total) * 100)
          }
        }
      })

      validationResult.value = response.data
      logger.info('File validated', {
        recordCount: response.data.record_count
      })
      return true

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Failed to validate file'
      error.value = errorMessage
      logger.error('Validation failed', { error: errorMessage })
      return false

    } finally {
      isUploading.value = false
      uploadProgress.value = 0
    }
  }

  /**
   * Run the migration import.
   *
   * @param {boolean} skipDuplicates - Whether to skip duplicate records (default: true)
   * @returns {Promise<boolean>} - True if import started successfully
   */
  const runImport = async (skipDuplicates = true) => {
    if (!isValidated.value) {
      error.value = 'Please validate a file first'
      return false
    }

    isImporting.value = true
    error.value = ''
    importResult.value = null
    importProgress.value = {
      processed: 0,
      total: recordCount.value,
      imported: 0,
      skipped: 0,
      errors: 0,
      status: 'starting'
    }

    try {
      // Start the import (returns immediately)
      const response = await api.post('/migration/import', {
        skip_duplicates: skipDuplicates
      })

      if (response.data.status === 'started' || response.data.status === 'already_running') {
        migrationId = response.data.migration_id
        importProgress.value.total = response.data.total_records || recordCount.value

        // Start polling for progress
        startPolling()
        logger.info('Import started', { migrationId })
        return true

      } else {
        error.value = 'Unexpected response from server'
        isImporting.value = false
        return false
      }

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Failed to start import'
      error.value = errorMessage
      logger.error('Import start failed', { error: errorMessage })
      isImporting.value = false
      return false
    }
  }

  /**
   * Cancel the migration and clean up temporary files.
   *
   * @returns {Promise<void>}
   */
  const cancelMigration = async () => {
    stopPolling()

    try {
      await api.post('/migration/cancel')
      logger.info('Migration cancelled')
    } catch (err) {
      logger.warn('Cancel request failed', { error: err.message })
    }

    // Reset state regardless of API result
    reset()
  }

  // ==========================================================================
  // Stage 2: Audio Import Methods
  // ==========================================================================

  /**
   * Load available folders that contain audio files.
   *
   * @returns {Promise<boolean>} - True if successful
   */
  const loadAvailableFolders = async () => {
    isLoadingFolders.value = true
    error.value = ''

    try {
      const response = await api.get('/migration/audio/folders')
      availableFolders.value = response.data.folders || []
      // Auto-select first folder if available
      if (availableFolders.value.length > 0 && !selectedFolder.value) {
        selectedFolder.value = availableFolders.value[0].path
      }
      logger.info('Loaded available folders', {
        count: availableFolders.value.length
      })
      return true

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Could not load folder list'
      error.value = errorMessage
      logger.error('Failed to load folders', { error: errorMessage })
      return false

    } finally {
      isLoadingFolders.value = false
    }
  }

  /**
   * Scan for audio files that can be imported.
   *
   * @returns {Promise<boolean>} - True if scan successful
   */
  const scanAudioFiles = async () => {
    isAudioScanning.value = true
    error.value = ''
    audioScanResult.value = null

    try {
      const response = await api.post('/migration/audio/scan', {
        source_folder: selectedFolder.value
      })
      audioScanResult.value = response.data
      logger.info('Audio scan completed', {
        matched: response.data.matched_count,
        unmatched: response.data.unmatched_count
      })
      return true

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Could not scan the selected folder'
      const hint = err.response?.data?.hint || ''
      error.value = hint ? `${errorMessage} ${hint}` : errorMessage
      logger.error('Audio scan failed', { error: errorMessage })
      return false

    } finally {
      isAudioScanning.value = false
    }
  }

  /**
   * Run the audio import.
   *
   * @returns {Promise<boolean>} - True if import started successfully
   */
  const runAudioImport = async () => {
    isAudioImporting.value = true
    error.value = ''
    audioImportResult.value = null
    audioImportProgress.value = {
      processed: 0,
      total: audioScanResult.value?.matched_count || 0,
      imported: 0,
      skipped: 0,
      errors: 0,
      status: 'starting'
    }

    try {
      const response = await api.post('/migration/audio/import', {
        source_folder: selectedFolder.value
      })

      if (response.data.status === 'started' || response.data.status === 'already_running') {
        audioImportId = response.data.import_id
        audioImportProgress.value.total = response.data.total_files || audioScanResult.value?.matched_count || 0
        startAudioImportPolling()
        logger.info('Audio import started', { audioImportId })
        return true

      } else {
        error.value = 'Unexpected response from server'
        isAudioImporting.value = false
        return false
      }

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Could not start the import'
      const hint = err.response?.data?.hint || ''
      error.value = hint ? `${errorMessage} ${hint}` : errorMessage
      logger.error('Audio import start failed', { error: errorMessage })
      isAudioImporting.value = false
      return false
    }
  }

  // ==========================================================================
  // Stage 3: Spectrogram Generation Methods
  // ==========================================================================

  /**
   * Scan for files needing spectrograms.
   *
   * @returns {Promise<boolean>} - True if scan successful
   */
  const scanSpectrograms = async () => {
    isSpectrogramScanning.value = true
    error.value = ''
    spectrogramScanResult.value = null

    try {
      const response = await api.post('/migration/spectrogram/scan')
      spectrogramScanResult.value = response.data
      logger.info('Spectrogram scan completed', {
        count: response.data.count
      })
      return true

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Failed to scan for spectrograms'
      error.value = errorMessage
      logger.error('Spectrogram scan failed', { error: errorMessage })
      return false

    } finally {
      isSpectrogramScanning.value = false
    }
  }

  /**
   * Run the spectrogram generation.
   *
   * @returns {Promise<boolean>} - True if generation started successfully
   */
  const runSpectrogramGeneration = async () => {
    isSpectrogramGenerating.value = true
    error.value = ''
    spectrogramResult.value = null
    spectrogramProgress.value = {
      processed: 0,
      total: spectrogramScanResult.value?.count || 0,
      generated: 0,
      errors: 0,
      status: 'starting'
    }

    try {
      const response = await api.post('/migration/spectrogram/generate')

      if (response.data.status === 'no_files') {
        // No files need spectrograms - treat as complete
        isSpectrogramGenerating.value = false
        spectrogramResult.value = { generated: 0, errors: 0 }
        logger.info('No files need spectrograms')
        return true
      }

      if (response.data.status === 'started' || response.data.status === 'already_running') {
        spectrogramGenerationId = response.data.generation_id
        spectrogramProgress.value.total = response.data.total_files || spectrogramScanResult.value?.count || 0
        startSpectrogramPolling()
        logger.info('Spectrogram generation started', { spectrogramGenerationId })
        return true

      } else {
        error.value = 'Unexpected response from server'
        isSpectrogramGenerating.value = false
        return false
      }

    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Failed to start spectrogram generation'
      error.value = errorMessage
      logger.error('Spectrogram generation start failed', { error: errorMessage })
      isSpectrogramGenerating.value = false
      return false
    }
  }

  // ==========================================================================
  // General Methods
  // ==========================================================================

  /**
   * Reset all migration state.
   */
  const reset = () => {
    // Stop all polling
    stopPolling()
    stopAudioImportPolling()
    stopSpectrogramPolling()

    // Stage 1 state
    isUploading.value = false
    isImporting.value = false
    validationResult.value = null
    importResult.value = null
    error.value = ''
    uploadProgress.value = 0
    importProgress.value = {
      processed: 0,
      total: 0,
      imported: 0,
      skipped: 0,
      errors: 0,
      status: null
    }
    migrationId = null

    // Stage 2 state
    availableFolders.value = []
    selectedFolder.value = null
    isLoadingFolders.value = false
    audioScanResult.value = null
    isAudioScanning.value = false
    isAudioImporting.value = false
    audioImportProgress.value = {
      processed: 0,
      total: 0,
      imported: 0,
      skipped: 0,
      errors: 0,
      status: null
    }
    audioImportResult.value = null
    audioImportId = null

    // Stage 3 state
    spectrogramScanResult.value = null
    isSpectrogramScanning.value = false
    isSpectrogramGenerating.value = false
    spectrogramProgress.value = {
      processed: 0,
      total: 0,
      generated: 0,
      errors: 0,
      status: null
    }
    spectrogramResult.value = null
    spectrogramGenerationId = null
  }

  /**
   * Clear the error message.
   */
  const clearError = () => {
    error.value = ''
  }

  return {
    // Stage 1 State
    isUploading,
    isImporting,
    validationResult,
    importResult,
    error,
    uploadProgress,
    importProgress,

    // Stage 1 Computed
    isValidated,
    recordCount,
    previewRecords,
    importProgressPercent,

    // Stage 2 State
    availableFolders,
    selectedFolder,
    isLoadingFolders,
    audioScanResult,
    isAudioScanning,
    isAudioImporting,
    audioImportProgress,
    audioImportResult,

    // Stage 2 Computed
    audioImportProgressPercent,

    // Stage 3 State
    spectrogramScanResult,
    isSpectrogramScanning,
    isSpectrogramGenerating,
    spectrogramProgress,
    spectrogramResult,

    // Stage 3 Computed
    spectrogramProgressPercent,

    // Stage 1 Methods
    validateFile,
    runImport,
    cancelMigration,

    // Stage 2 Methods
    loadAvailableFolders,
    scanAudioFiles,
    runAudioImport,

    // Stage 3 Methods
    scanSpectrograms,
    runSpectrogramGeneration,

    // General Methods
    reset,
    clearError
  }
}
