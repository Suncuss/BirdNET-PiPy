<template>
  <div class="fixed inset-0 z-50 overflow-y-auto">
    <div
      class="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
      @click="$emit('close')"
    />
    <div class="flex min-h-full items-center justify-center p-4">
      <div class="relative bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
        <!-- Header -->
        <div class="p-4 border-b border-gray-200">
          <h3 class="text-lg font-semibold text-gray-900">
            {{ title }}
          </h3>
          <p class="text-sm text-gray-500 mt-1">
            {{ description }}
          </p>
        </div>

        <!-- Search -->
        <div class="p-4 border-b border-gray-200">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search species by name..."
            class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
            @input="debouncedSearch"
          >
        </div>

        <!-- Species List -->
        <div class="flex-1 overflow-y-auto p-4 min-h-[300px]">
          <div
            v-if="loading"
            class="flex justify-center items-center h-32"
          >
            <svg
              class="animate-spin h-6 w-6 text-blue-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
          </div>

          <div
            v-else-if="filteredSpecies.length === 0"
            class="text-center text-gray-500 py-8"
          >
            <p v-if="searchQuery">
              No species found matching "{{ searchQuery }}"
            </p>
            <p v-else>
              No species available
            </p>
          </div>

          <div
            v-else
            class="space-y-1"
          >
            <div
              v-for="species in filteredSpecies"
              :key="species.scientific_name"
              class="flex items-center justify-between p-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
              :class="{ 'bg-blue-50': isSelected(species.scientific_name) }"
              @click="toggleSpecies(species.scientific_name)"
            >
              <div>
                <p class="text-sm font-medium text-gray-800">
                  {{ species.common_name }}
                </p>
                <p class="text-xs text-gray-500">
                  {{ species.scientific_name }}
                </p>
              </div>
              <div
                v-if="isSelected(species.scientific_name)"
                class="text-blue-600"
              >
                <svg
                  class="w-5 h-5"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fill-rule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clip-rule="evenodd"
                  />
                </svg>
              </div>
            </div>
          </div>
        </div>

        <!-- Selected Count & Actions -->
        <div class="p-4 border-t border-gray-200 bg-gray-50 rounded-b-xl">
          <!-- Restart Progress -->
          <div
            v-if="isRestarting && restartMessage"
            class="flex items-center gap-2 text-blue-700 text-sm"
          >
            <svg
              class="animate-spin h-4 w-4"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>{{ restartMessage }}</span>
          </div>

          <!-- Error (save or restart) -->
          <div
            v-else-if="saveError || restartError"
            class="flex items-center justify-between w-full"
          >
            <div class="flex items-center gap-2 text-amber-700 text-sm">
              <svg
                class="h-4 w-4 flex-shrink-0"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <span>{{ saveError || restartError }}</span>
            </div>
            <div class="flex gap-2">
              <button
                class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                @click="handleDismiss"
              >
                Cancel
              </button>
              <button
                class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                @click="saveAndClose"
              >
                Retry
              </button>
            </div>
          </div>

          <!-- Normal Actions -->
          <div
            v-else
            class="flex items-center justify-between"
          >
            <div class="text-sm text-gray-600">
              <span class="font-medium">{{ selectedSpecies.length }}</span> species selected
              <span
                v-if="totalSpecies"
                class="text-gray-400"
              >of {{ totalSpecies }} available</span>
            </div>
            <div class="flex gap-2">
              <button
                class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                :disabled="saving"
                @click="$emit('close')"
              >
                Cancel
              </button>
              <button
                class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-400"
                :disabled="saving"
                @click="saveAndClose"
              >
                {{ saving ? 'Saving...' : 'Save' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/services/api'

export default {
  name: 'SpeciesFilterModal',
  props: {
    title: {
      type: String,
      default: 'Select Species'
    },
    description: {
      type: String,
      default: 'Select species to add to the filter list'
    },
    modelValue: {
      type: Array,
      default: () => []
    },
    onSave: {
      type: Function,
      default: null
    },
    isRestarting: {
      type: Boolean,
      default: false
    },
    restartMessage: {
      type: String,
      default: ''
    },
    restartError: {
      type: String,
      default: ''
    },
    speciesList: {
      type: Array,
      default: null
    }
  },
  emits: ['update:modelValue', 'close'],
  setup(props, { emit }) {
    const loading = ref(false)
    const saving = ref(false)
    const saveError = ref('')
    const searchQuery = ref('')
    const allSpecies = ref([])
    const totalSpecies = ref(0)
    const selectedSpecies = ref([...props.modelValue])

    // Debounce search
    let searchTimeout = null
    const debouncedSearch = () => {
      clearTimeout(searchTimeout)
      searchTimeout = setTimeout(() => {
        // Search is handled client-side since we load all species
      }, 300)
    }

    // Filter species based on search query
    const filteredSpecies = computed(() => {
      if (!searchQuery.value) {
        return allSpecies.value
      }
      const query = searchQuery.value.toLowerCase()
      return allSpecies.value.filter(s =>
        s.common_name.toLowerCase().includes(query) ||
        s.scientific_name.toLowerCase().includes(query)
      )
    })

    // Check if species is selected
    const isSelected = (scientificName) => {
      return selectedSpecies.value.includes(scientificName)
    }

    // Toggle species selection
    const toggleSpecies = (scientificName) => {
      const index = selectedSpecies.value.indexOf(scientificName)
      if (index === -1) {
        selectedSpecies.value.push(scientificName)
      } else {
        selectedSpecies.value.splice(index, 1)
      }
    }

    // Load available species (use prop if provided, otherwise fetch)
    const loadSpecies = async () => {
      if (props.speciesList && props.speciesList.length > 0) {
        allSpecies.value = props.speciesList
        totalSpecies.value = props.speciesList.length
        return
      }

      loading.value = true
      try {
        const { data } = await api.get('/species/available')
        allSpecies.value = data.species
        totalSpecies.value = data.total
      } catch (error) {
        console.error('Error loading species:', error)
      } finally {
        loading.value = false
      }
    }

    // Save and close
    const saveAndClose = async () => {
      emit('update:modelValue', [...selectedSpecies.value])

      // If onSave callback is provided, call it and wait for restart
      if (props.onSave) {
        saving.value = true
        saveError.value = ''
        try {
          await props.onSave([...selectedSpecies.value])
          // Page will reload after restart, modal closes automatically
        } catch (error) {
          console.error('Error saving species filter:', error)
          saveError.value = 'Failed to save. Please try again.'
          saving.value = false
        }
      } else {
        // Legacy behavior: just close
        emit('close')
      }
    }

    // Handle dismiss from RestartStatus component
    const handleDismiss = () => {
      saveError.value = ''
      emit('close')
    }

    // Watch for prop changes
    watch(() => props.modelValue, (newVal) => {
      selectedSpecies.value = [...newVal]
    })

    onMounted(() => {
      loadSpecies()
    })

    onUnmounted(() => {
      clearTimeout(searchTimeout)
    })

    return {
      loading,
      saving,
      saveError,
      searchQuery,
      filteredSpecies,
      totalSpecies,
      selectedSpecies,
      debouncedSearch,
      isSelected,
      toggleSpecies,
      saveAndClose,
      handleDismiss
    }
  }
}
</script>
