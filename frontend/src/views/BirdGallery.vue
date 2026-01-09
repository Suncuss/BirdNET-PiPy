<template>
  <div class="bird-gallery px-4 sm:px-6 lg:px-8">
    <div class="mb-4 sm:mb-6 overflow-x-auto">
      <nav class="flex space-x-2 sm:space-x-4 border-b whitespace-nowrap">
        <button v-for="tab in tabs" :key="tab.value" @click="selectTab(tab.value)" :class="[
          'py-2 px-3 sm:px-4 text-xs sm:text-sm font-medium flex items-center',
          selectedTab === tab.value
            ? 'border-b-2 border-blue-500 text-blue-600'
            : 'text-gray-500 hover:text-gray-700'
        ]">
          <span class="mr-1.5" v-html="tab.icon"></span>
          {{ tab.label }}
        </button>
      </nav>
    </div>

    <div>
      <!-- Conditional check for displayedBirds -->
      <div v-if="displayedBirds.length === 0" class="text-center text-gray-500 p-4">
        No birds to display yet.
      </div>

      <!-- Grid of bird cards -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-6">
        <div v-for="bird in displayedBirds" :key="bird.id"
          class="bird-card bg-white rounded-lg shadow-md overflow-hidden transition-all duration-300 hover:shadow-lg">

          <!-- Wrap the image and related content inside the router-link -->
          <router-link :to="{ name: 'BirdDetails', params: { name: bird.name } }" class="group">
            <div class="relative aspect-square overflow-hidden bg-gray-200">
              <img :src="bird.imageUrl" :alt="bird.name"
                class="absolute inset-0 w-full h-full object-cover transition-[opacity,transform] duration-500 group-hover:scale-110"
                :class="{ 'opacity-0': !bird.focalPointReady, 'opacity-100': bird.focalPointReady }"
                :style="{ objectPosition: bird.focalPoint || '50% 50%' }"
                loading="lazy">
              <div
                class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                <font-awesome-icon icon="fas fa-info-circle" class="text-white text-2xl" />
              </div>
            </div>
          </router-link>

          <div class="p-3 sm:p-4 bg-gray-100 text-xs text-gray-600">
            <p>
              Photo by <a :href="bird.authorUrl" target="_blank" rel="noopener noreferrer" class="text-blue-600 underline">{{ bird.authorName
                }}</a>
            </p>
            <p>
              Licensed under {{ bird.licenseType }}
            </p>
          </div>
          <div class="p-3 sm:p-4">
            <h2 class="text-lg font-semibold mb-2">{{ bird.name }}</h2>
            <p class="text-sm text-gray-600 mb-1">{{ bird.scientificName }}</p>
            <p class="text-xs text-gray-500">{{ bird.lastDetected ? `Last detected: ${formatDate(bird.lastDetected)}` : 'Detection info available in details' }}</p>
            <router-link :to="{ name: 'BirdDetails', params: { name: bird.name } }"
              class="mt-2 inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow focus:outline-none focus:ring-2 focus:ring-blue-300 text-sm transition-all duration-300">
              Learn More
            </router-link>
          </div>
        </div>
      </div>

    </div>

  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api'
import { useSmartCrop } from '@/composables/useSmartCrop'

export default {
  name: 'BirdGallery',
  setup() {
    const selectedTab = ref('recent')
    const birds = ref([])
    const { calculateFocalPoint } = useSmartCrop()
    const tabs = [
      { value: 'recent', label: 'Today\'s Detections', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd" /></svg>' },
      { value: 'frequent', label: 'Most Frequent', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" clip-rule="evenodd" /></svg>' },
      { value: 'rare', label: 'Least Frequent', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12 13a1 1 0 100 2h5a1 1 0 001-1V9a1 1 0 10-2 0v2.586l-4.293-4.293a1 1 0 00-1.414 0L8 9.586 3.707 5.293a1 1 0 00-1.414 1.414l5 5a1 1 0 001.414 0L11 9.414 14.586 13H12z" clip-rule="evenodd" /></svg>' },
      { value: 'all', label: 'Species Catalog', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" /></svg>' },
    ]

    // TODO, fix bird id for non-unique birds

    const fetchUniqueBirds = async () => {
      const today = new Date().toLocaleDateString('en-CA');
      console.log(today);
      try {
        const { data } = await api.get('/sightings/unique', {
          params: { date: today }
        })
        return data.map(bird => ({
          id: bird.id,
          name: bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageUrl: '/default_bird.png',
          focalPointReady: true,  // Show placeholder immediately
        }))
      } catch (error) {
        console.error('Error fetching unique birds:', error)
        return []
      }
    }

    const fetchSightings = async (type) => {
      try {
        const { data } = await api.get('/sightings', {
          params: { type }
        })
        return data.map(bird => ({
          id: bird.common_name,
          name: bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageUrl: '/default_bird.png',
          focalPointReady: true,  // Show placeholder immediately
        }))
      } catch (error) {
        console.error(`Error fetching ${type} birds:`, error)
        return []
      }
    }

    const fetchAllSpecies = async () => {
      try {
        const { data: speciesList } = await api.get('/species/all')
        // For all species, we need to fetch additional details for each one
        const speciesWithDetails = await Promise.all(
          speciesList.map(async (species) => {
            try {
              // Fetch bird details to get last detected date
              const { data: details } = await api.get(`/bird/${species.common_name}`)
              return {
                id: species.common_name,
                name: species.common_name,
                scientificName: species.scientific_name,
                lastDetected: details.last_detected ? new Date(details.last_detected) : null,
                imageUrl: '/default_bird.png',
                focalPointReady: true,  // Show placeholder immediately
              }
            } catch (error) {
              // If details fetch fails, still show the bird
              return {
                id: species.common_name,
                name: species.common_name,
                scientificName: species.scientific_name,
                lastDetected: null,
                imageUrl: '/default_bird.png',
                focalPointReady: true,  // Show placeholder immediately
              }
            }
          })
        )
        return speciesWithDetails
      } catch (error) {
        console.error('Error fetching all species:', error)
        return []
      }
    }

    const updateBirdImages = async (birds) => {
      for (const bird of birds) {
        // Hide image while loading real one
        bird.focalPointReady = false

        const imageData = await fetchWikimediaImage(bird.name)
        if (imageData) {
          bird.imageUrl = imageData.imageUrl
          bird.authorName = imageData.authorName
          bird.authorUrl = imageData.authorUrl
          bird.licenseType = imageData.licenseType

          // Calculate focal point immediately for this bird
          bird.focalPoint = await calculateFocalPoint(imageData.imageUrl)
        }

        // Show image with correct crop
        bird.focalPointReady = true
      }
    }

    const selectTab = async (tab) => {
      selectedTab.value = tab
      if (tab === 'recent') {
        birds.value = await fetchUniqueBirds()
        //TODO ERROR MESSAGE WHEN NO BIRDS
      } else if (tab === 'all') {
        birds.value = await fetchAllSpecies()
      } else if (tab === 'frequent' || tab === 'rare') {
        birds.value = await fetchSightings(tab)
      }
      await updateBirdImages(birds.value)
    }

    onMounted(async () => {
      if (selectedTab.value === 'recent') {
        birds.value = await fetchUniqueBirds()
        await updateBirdImages(birds.value)
      }
    })

    const displayedBirds = computed(() => {
      return birds.value
    })

    const formatDate = (date) => {
      return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
    }

    const fetchWikimediaImage = async (speciesName) => {
      try {
        const { data } = await api.get('/wikimedia_image', {
          params: { species: speciesName }
        })
        return data
      } catch (error) {
        console.error(`Error fetching Wikimedia image for ${speciesName}:`, error)
        return null
      }
    }

    return {
      selectedTab,
      tabs,
      displayedBirds,
      formatDate,
      selectTab,
    }
  }
}
</script>
