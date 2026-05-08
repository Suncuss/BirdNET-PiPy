<template>
  <Transition
    enter-active-class="transition ease-out duration-200"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition ease-in duration-150"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="isVisible"
      class="fixed inset-0 z-50 overflow-y-auto bg-black/70"
      @click.self="onCancel"
    >
      <div
        class="flex min-h-full items-center justify-center p-4"
        @click.self="onCancel"
      >
        <div class="relative bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[90vh] flex flex-col">
          <!-- Header -->
          <div class="flex items-center justify-between p-5 border-b border-gray-200">
            <h2 class="text-lg font-semibold text-gray-900">
              Choose image <span class="text-gray-500 font-normal">— {{ speciesName }}</span>
            </h2>
            <button
              class="p-1 rounded-full text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
              title="Close"
              @click="onCancel"
            >
              <svg
                class="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2.5"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="p-5 overflow-y-auto">
            <div
              v-if="loadingCandidates"
              class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
            >
              <div
                v-for="i in 8"
                :key="`skeleton-${i}`"
                class="aspect-square rounded-lg bg-gray-200 animate-pulse"
              />
            </div>

            <div
              v-else-if="loadError && visibleCandidates.length === 0"
              class="text-center py-8 text-gray-500"
            >
              <p>{{ loadError }}</p>
              <button
                class="mt-3 px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
                @click="loadCandidates"
              >
                Retry
              </button>
            </div>

            <div
              v-else
              class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
            >
              <button
                v-for="(candidate, idx) in visibleCandidates"
                :key="candidate.fileTitle"
                type="button"
                class="relative aspect-square rounded-lg overflow-hidden bg-gray-100 group focus:outline-none transition-shadow"
                :class="isWikimediaSelected(candidate) ? 'ring-2 ring-green-600 ring-offset-2' : 'hover:ring-2 hover:ring-gray-300'"
                @click="selectWikimedia(idx)"
                @mouseenter="hoveredCandidate = candidate"
                @mouseleave="hoveredCandidate = null"
              >
                <img
                  :src="candidate.thumbUrl || candidate.imageUrl"
                  :alt="candidate.fileTitle"
                  class="absolute inset-0 w-full h-full object-cover"
                  loading="lazy"
                  decoding="async"
                  @error="onCandidateImageError(candidate)"
                >
                <span
                  v-if="isWikimediaSelected(candidate)"
                  class="absolute top-1.5 right-1.5 bg-green-600 text-white rounded-full w-6 h-6 flex items-center justify-center shadow"
                  aria-label="Selected"
                >
                  <svg
                    class="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="3"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                </span>
              </button>

              <!-- Upload tile (always last) -->
              <button
                type="button"
                class="relative aspect-square rounded-lg overflow-hidden focus:outline-none transition-shadow"
                :class="[
                  uploadTileClass,
                  isUploadSelected ? 'ring-2 ring-green-600 ring-offset-2' : 'hover:ring-2 hover:ring-gray-300'
                ]"
                @click="onUploadTileClick"
              >
                <template v-if="hasCustomImage && !pendingFile && selectedKind !== 'reset'">
                  <img
                    :src="customImagePreview"
                    alt="Custom image"
                    class="absolute inset-0 w-full h-full object-cover"
                  >
                  <span
                    class="absolute top-1.5 left-1.5 bg-black/60 text-white text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5"
                  >
                    Yours
                  </span>
                  <button
                    type="button"
                    class="absolute top-1.5 right-1.5 bg-black/70 hover:bg-red-600 text-white rounded-full w-6 h-6 flex items-center justify-center shadow"
                    title="Remove custom image"
                    @click.stop="markReset"
                  >
                    <svg
                      class="w-3.5 h-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke-width="2.5"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </template>
                <template v-else-if="pendingFile">
                  <img
                    :src="pendingFilePreview"
                    alt="Pending upload"
                    class="absolute inset-0 w-full h-full object-cover"
                  >
                  <span
                    class="absolute top-1.5 left-1.5 bg-blue-600 text-white text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5"
                  >
                    Ready
                  </span>
                </template>
                <template v-else>
                  <div class="absolute inset-0 flex flex-col items-center justify-center text-gray-500 px-2 text-center">
                    <svg
                      class="w-7 h-7 mb-1"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path d="M9.25 13.25a.75.75 0 0 0 1.5 0V4.636l2.955 3.129a.75.75 0 0 0 1.09-1.03l-4.25-4.5a.75.75 0 0 0-1.09 0l-4.25 4.5a.75.75 0 1 0 1.09 1.03L9.25 4.636v8.614Z" />
                      <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
                    </svg>
                    <span class="text-xs font-medium">Upload your own</span>
                  </div>
                </template>
                <span
                  v-if="isUploadSelected && (pendingFile || (hasCustomImage && selectedKind !== 'reset'))"
                  class="absolute bottom-1.5 right-1.5 bg-green-600 text-white rounded-full w-6 h-6 flex items-center justify-center shadow"
                  aria-label="Selected"
                >
                  <svg
                    class="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="3"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                </span>
              </button>

              <input
                ref="fileInput"
                type="file"
                accept="image/*"
                class="hidden"
                @change="onFilePicked"
              >
            </div>

            <!-- Attribution / status preview -->
            <div class="mt-4 min-h-[2.5rem] text-sm text-gray-600">
              <p
                v-if="attributionText"
                class="leading-snug"
              >
                {{ attributionText.prefix }}
                <a
                  v-if="attributionText.authorUrl"
                  :href="attributionText.authorUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-blue-600 underline"
                >{{ attributionText.authorName }}</a>
                <span v-else>{{ attributionText.authorName }}</span>
                {{ attributionText.suffix }}
              </p>
              <p
                v-else-if="selectedKind === 'reset'"
                class="text-gray-500"
              >
                Will remove your custom image and revert to the default Wikimedia search result.
              </p>
              <p
                v-else-if="selectedKind === 'upload' && pendingFile"
                class="text-gray-500"
              >
                Ready to upload {{ pendingFile.name }} ({{ formatBytes(pendingFile.size) }}).
              </p>
              <p
                v-if="formError"
                class="text-red-600 mt-1"
              >
                {{ formError }}
              </p>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-3 p-4 border-t border-gray-200">
            <button
              type="button"
              class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
              :disabled="isApplying"
              @click="onCancel"
            >
              Cancel
            </button>
            <button
              type="button"
              class="px-4 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors inline-flex items-center gap-2 disabled:bg-gray-300 disabled:cursor-not-allowed"
              :disabled="!canApply || isApplying"
              @click="onApply"
            >
              <Spinner
                v-if="isApplying"
                class="w-4 h-4"
              />
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script>
import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import Spinner from '@/components/Spinner.vue'
import { useAuth } from '@/composables/useAuth'
import { getBirdImageUrl } from '@/services/media'
import { formatBytes } from '@/utils/format'

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const ALLOWED_UPLOAD_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']

export default {
  name: 'BirdImageModal',
  components: { Spinner },
  props: {
    isVisible: { type: Boolean, default: false },
    speciesName: { type: String, required: true },
    hasCustomImage: { type: Boolean, default: false },
    selectedFileTitle: { type: String, default: null }
  },
  emits: ['close', 'applied'],
  setup(props, { emit }) {
    const { needsLogin } = useAuth()

    const candidates = ref([])
    const hiddenTitles = ref(new Set())
    const loadingCandidates = ref(false)
    const loadError = ref(null)
    const lastLoadedSpecies = ref(null)
    const customImageCacheBust = ref(Date.now())

    const selectedKind = ref(null) // 'wikimedia' | 'upload' | 'reset'
    const selectedIndex = ref(-1)
    const pendingFile = ref(null)
    const pendingFilePreview = ref(null)

    const isApplying = ref(false)
    const formError = ref(null)
    const hoveredCandidate = ref(null)
    const fileInput = ref(null)

    const visibleCandidates = computed(() =>
      candidates.value.filter((c) => !hiddenTitles.value.has(c.fileTitle))
    )

    const customImagePreview = computed(() =>
      `${getBirdImageUrl(props.speciesName)}?t=${customImageCacheBust.value}`
    )

    const isUploadSelected = computed(() => selectedKind.value === 'upload' || selectedKind.value === 'reset')

    const uploadTileClass = computed(() => {
      if (props.hasCustomImage || pendingFile.value) {
        return 'bg-gray-100'
      }
      return 'border-2 border-dashed border-gray-300 bg-gray-50 hover:bg-gray-100'
    })

    const isWikimediaSelected = (candidate) =>
      selectedKind.value === 'wikimedia' &&
      visibleCandidates.value[selectedIndex.value]?.fileTitle === candidate.fileTitle

    const initialSelection = () => {
      if (props.hasCustomImage) {
        selectedKind.value = 'upload'
        selectedIndex.value = -1
      } else if (props.selectedFileTitle) {
        const idx = visibleCandidates.value.findIndex(
          (c) => c.fileTitle === props.selectedFileTitle
        )
        if (idx >= 0) {
          selectedKind.value = 'wikimedia'
          selectedIndex.value = idx
          return
        }
        selectedKind.value = null
        selectedIndex.value = -1
      } else {
        selectedKind.value = null
        selectedIndex.value = -1
      }
    }

    const formatLoadError = (err) => {
      // Backend wraps Wikimedia's HTTPError as `Error fetching Wikimedia image: 429 ...`
      // — surface a friendlier ask-and-retry instead of the raw upstream text.
      const apiMessage = err?.response?.data?.error || ''
      if (apiMessage.includes('429') || apiMessage.includes('Too Many Requests')) {
        return 'Wikimedia is temporarily rate-limiting requests. Please wait a moment and try again.'
      }
      return apiMessage || 'Could not load candidates from Wikimedia.'
    }

    const loadCandidates = async () => {
      loadingCandidates.value = true
      loadError.value = null
      try {
        const { data } = await api.get('/wikimedia_image/candidates', {
          params: { species: props.speciesName, limit: 8 }
        })
        candidates.value = Array.isArray(data?.candidates) ? data.candidates : []
        hiddenTitles.value = new Set()
        lastLoadedSpecies.value = props.speciesName
        initialSelection()
      } catch (err) {
        loadError.value = formatLoadError(err)
        candidates.value = []
      } finally {
        loadingCandidates.value = false
      }
    }

    const resetTransientState = () => {
      pendingFile.value = null
      if (pendingFilePreview.value) {
        URL.revokeObjectURL(pendingFilePreview.value)
        pendingFilePreview.value = null
      }
      formError.value = null
      hoveredCandidate.value = null
    }

    watch(
      () => [props.isVisible, props.speciesName],
      ([visible, species]) => {
        if (!visible) {
          resetTransientState()
          isApplying.value = false
          return
        }
        customImageCacheBust.value = Date.now()
        if (species && species !== lastLoadedSpecies.value) {
          candidates.value = []
          loadCandidates()
        } else {
          initialSelection()
        }
      },
      { immediate: true }
    )

    const selectWikimedia = (idx) => {
      formError.value = null
      selectedKind.value = 'wikimedia'
      selectedIndex.value = idx
    }

    const onUploadTileClick = () => {
      formError.value = null
      // If a custom image already exists and the user has not staged a different action,
      // keep them on the existing custom image.
      if (props.hasCustomImage && !pendingFile.value && selectedKind.value !== 'reset') {
        // Tapping the tile while not uploading: open file picker to replace.
        fileInput.value?.click()
        return
      }
      if (pendingFile.value) {
        selectedKind.value = 'upload'
        return
      }
      fileInput.value?.click()
    }

    const onFilePicked = (event) => {
      const file = event.target.files?.[0]
      if (!file) return
      if (!ALLOWED_UPLOAD_TYPES.includes(file.type)) {
        formError.value = 'Unsupported image type. Use JPEG, PNG, WebP, or GIF.'
        event.target.value = ''
        return
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        formError.value = `File too large (max ${MAX_UPLOAD_BYTES / (1024 * 1024)}MB).`
        event.target.value = ''
        return
      }
      if (pendingFilePreview.value) {
        URL.revokeObjectURL(pendingFilePreview.value)
      }
      pendingFile.value = file
      pendingFilePreview.value = URL.createObjectURL(file)
      selectedKind.value = 'upload'
      event.target.value = ''
    }

    const markReset = () => {
      formError.value = null
      selectedKind.value = 'reset'
      pendingFile.value = null
      if (pendingFilePreview.value) {
        URL.revokeObjectURL(pendingFilePreview.value)
        pendingFilePreview.value = null
      }
    }

    const onCandidateImageError = (candidate) => {
      hiddenTitles.value = new Set([...hiddenTitles.value, candidate.fileTitle])
      if (selectedKind.value === 'wikimedia' &&
          visibleCandidates.value[selectedIndex.value]?.fileTitle === candidate.fileTitle) {
        selectedKind.value = null
        selectedIndex.value = -1
      }
    }

    const canApply = computed(() => {
      if (selectedKind.value === 'wikimedia') {
        const c = visibleCandidates.value[selectedIndex.value]
        if (!c) return false
        // Wikimedia choice is meaningful if it differs from the saved one OR a custom is currently displayed.
        return props.hasCustomImage || c.fileTitle !== props.selectedFileTitle
      }
      if (selectedKind.value === 'upload') return !!pendingFile.value
      if (selectedKind.value === 'reset') return props.hasCustomImage || !!props.selectedFileTitle
      return false
    })

    const attributionText = computed(() => {
      const c = hoveredCandidate.value || (selectedKind.value === 'wikimedia' ? visibleCandidates.value[selectedIndex.value] : null)
      if (!c) return null
      return {
        prefix: 'Photo by',
        authorName: c.authorName || 'Unknown Author',
        authorUrl: c.authorUrl,
        suffix: `, licensed under ${c.licenseType || 'Unknown License'}.`
      }
    })

    const onCancel = () => {
      if (isApplying.value) return
      emit('close')
    }

    const requireAuth = () => {
      if (needsLogin.value) {
        window.dispatchEvent(new CustomEvent('auth:required'))
        return false
      }
      return true
    }

    // Other views (e.g. BirdGallery) listen for this so they can patch in place
    // without re-fetching the species — the modal already knows the new state.
    const broadcastChange = (detail) => {
      window.dispatchEvent(new CustomEvent('bird-image:changed', { detail }))
    }

    // Wikimedia-sourced broadcast (used by 'wikimedia' apply and 'reset' apply, which
    // both display a Wikimedia candidate post-apply). For 'reset', `source` is
    // visibleCandidates[0] (top-of-search, what the backend will serve once the sidecar
    // is gone); we pass fileTitle=null so consumers know nothing is "saved" anymore.
    const broadcastWikimedia = (kind, source) => broadcastChange({
      species: props.speciesName,
      kind,
      hasCustomImage: false,
      imageUrl: source?.imageUrl,
      pageUrl: source?.pageUrl,
      authorName: source?.authorName,
      authorUrl: source?.authorUrl,
      licenseType: source?.licenseType,
      fileTitle: kind === 'reset' ? null : (source?.fileTitle ?? null)
    })

    const onApply = async () => {
      if (!canApply.value || isApplying.value) return
      if (!requireAuth()) return

      isApplying.value = true
      formError.value = null
      try {
        if (selectedKind.value === 'wikimedia') {
          const candidate = visibleCandidates.value[selectedIndex.value]
          await api.put(`/bird/${encodeURIComponent(props.speciesName)}/wikimedia_choice`, {
            fileTitle: candidate.fileTitle,
            imageUrl: candidate.imageUrl,
            pageUrl: candidate.pageUrl,
            authorName: candidate.authorName,
            authorUrl: candidate.authorUrl,
            licenseType: candidate.licenseType
          })
          if (props.hasCustomImage) {
            try {
              await api.delete(`/bird/${encodeURIComponent(props.speciesName)}/image`)
            } catch (err) {
              if (err?.response?.status !== 404) throw err
            }
          }
          emit('applied', { kind: 'wikimedia', candidate })
          broadcastWikimedia('wikimedia', candidate)
        } else if (selectedKind.value === 'upload') {
          const formData = new FormData()
          formData.append('file', pendingFile.value)
          await api.post(`/bird/${encodeURIComponent(props.speciesName)}/image`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })
          emit('applied', { kind: 'upload', hasCustomImage: true })
          broadcastChange({
            species: props.speciesName,
            kind: 'upload',
            hasCustomImage: true,
            imageUrl: `${getBirdImageUrl(props.speciesName)}?t=${Date.now()}`
          })
        } else if (selectedKind.value === 'reset') {
          const ignore404 = (p) => p.catch((err) => {
            if (err?.response?.status === 404) return null
            throw err
          })
          await Promise.all([
            ignore404(api.delete(`/bird/${encodeURIComponent(props.speciesName)}/image`)),
            ignore404(api.delete(`/bird/${encodeURIComponent(props.speciesName)}/wikimedia_choice`))
          ])
          emit('applied', { kind: 'reset', hasCustomImage: false })
          broadcastWikimedia('reset', visibleCandidates.value[0] || null)
        }
        emit('close')
      } catch (err) {
        formError.value = err?.response?.data?.error || 'Could not save your choice. Please try again.'
      } finally {
        isApplying.value = false
      }
    }

    return {
      candidates,
      visibleCandidates,
      loadingCandidates,
      loadError,
      selectedKind,
      selectedIndex,
      pendingFile,
      pendingFilePreview,
      isApplying,
      formError,
      hoveredCandidate,
      fileInput,
      customImagePreview,
      uploadTileClass,
      isUploadSelected,
      attributionText,
      canApply,
      isWikimediaSelected,
      selectWikimedia,
      onUploadTileClick,
      onFilePicked,
      markReset,
      onCandidateImageError,
      onCancel,
      onApply,
      loadCandidates,
      formatBytes
    }
  }
}
</script>
