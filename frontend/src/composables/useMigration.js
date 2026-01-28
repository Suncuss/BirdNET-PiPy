import { ref, computed } from 'vue'
import { useLogger } from './useLogger'
import api, { createLongRequest } from '@/services/api'

/**
 * Composable for BirdNET-Pi database migration.
 *
 * Handles the workflow of:
 * 1. Uploading and validating a BirdNET-Pi birds.db file (with upload progress)
 * 2. Previewing records
 * 3. Running the migration import (with progress polling)
 * 4. Cancelling and cleaning up
 */
export function useMigration() {
  const logger = useLogger('useMigration')

  // State
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

  // Polling state
  let pollIntervalId = null
  let migrationId = null

  // Computed properties
  const isValidated = computed(() => validationResult.value?.valid === true)
  const recordCount = computed(() => validationResult.value?.record_count ?? 0)
  const previewRecords = computed(() => validationResult.value?.preview ?? [])

  const importProgressPercent = computed(() => {
    if (!importProgress.value.total) return 0
    return Math.round((importProgress.value.processed / importProgress.value.total) * 100)
  })

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
   * Poll for migration status.
   */
  const pollStatus = async () => {
    if (!migrationId) return

    try {
      const response = await api.get('/migration/status', {
        params: { migration_id: migrationId }
      })

      const status = response.data
      importProgress.value = {
        processed: status.processed || 0,
        total: status.total || 0,
        imported: status.imported || 0,
        skipped: status.skipped || 0,
        errors: status.errors || 0,
        status: status.status
      }

      // Check if completed or failed
      if (status.status === 'completed') {
        stopPolling()
        isImporting.value = false
        importResult.value = {
          imported: status.imported,
          skipped: status.skipped,
          errors: status.errors
        }
        validationResult.value = null
        logger.info('Import completed', importResult.value)

      } else if (status.status === 'failed') {
        stopPolling()
        isImporting.value = false
        error.value = status.error || 'Import failed'
        logger.error('Import failed', { error: status.error })
      }

    } catch (err) {
      // Handle 404 - migration progress was cleared (after timeout)
      if (err.response?.status === 404) {
        stopPolling()
        isImporting.value = false

        if (importProgress.value.processed > 0) {
          // Had some progress - show last known state with warning
          // Don't assume success since we don't know the final state
          importResult.value = {
            imported: importProgress.value.imported,
            skipped: importProgress.value.skipped,
            errors: importProgress.value.errors,
            warning: 'Migration status expired. These are the last known counts.'
          }
          validationResult.value = null
          logger.warn('Migration status expired, showing last known progress', importResult.value)
        } else {
          // Never saw progress - something went wrong
          error.value = 'Migration status not found. The import may have failed or completed. Please check your data.'
          logger.error('Migration not found and no progress recorded')
        }
        return
      }
      // Don't stop polling on other network errors, just log
      logger.warn('Status poll failed', { error: err.message })
    }
  }

  /**
   * Start polling for import status.
   */
  const startPolling = () => {
    if (pollIntervalId) return
    pollIntervalId = setInterval(pollStatus, 1000) // Poll every second
  }

  /**
   * Stop polling for import status.
   */
  const stopPolling = () => {
    if (pollIntervalId) {
      clearInterval(pollIntervalId)
      pollIntervalId = null
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

  /**
   * Reset all migration state.
   */
  const reset = () => {
    stopPolling()
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
  }

  /**
   * Clear the error message.
   */
  const clearError = () => {
    error.value = ''
  }

  return {
    // State
    isUploading,
    isImporting,
    validationResult,
    importResult,
    error,
    uploadProgress,
    importProgress,

    // Computed
    isValidated,
    recordCount,
    previewRecords,
    importProgressPercent,

    // Methods
    validateFile,
    runImport,
    cancelMigration,
    reset,
    clearError
  }
}
