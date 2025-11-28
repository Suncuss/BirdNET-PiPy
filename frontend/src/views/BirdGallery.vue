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
          <span class="mr-1 sm:mr-2" v-html="tab.icon"></span>
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
            <div class="relative aspect-square overflow-hidden">
              <img :src="bird.imageUrl" :alt="bird.name"
                class="absolute inset-0 w-full h-full object-cover object-center transition-transform duration-300 group-hover:scale-110"
                loading="lazy">
              <div
                class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                <font-awesome-icon icon="fas fa-info-circle" class="text-white text-2xl" />
              </div>
            </div>
          </router-link>

          <div class="p-3 sm:p-4 bg-gray-100 text-xs text-gray-600">
            <p>
              Photo by <a :href="bird.authorUrl" target="_blank" class="text-blue-600 underline">{{ bird.authorName
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
import axios from 'axios'

export default {
  name: 'BirdGallery',
  setup() {
    const selectedTab = ref('recent')
    const API_BASE_URL = '/api'
    const birds = ref([])
    const tabs = [
      { value: 'recent', label: 'Today\'s Visitors', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>' },
      { value: 'frequent', label: 'Most Frequent', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 0l-2 2a1 1 0 101.414 1.414L8 10.414l1.293 1.293a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>' },
      { value: 'rare', label: 'Rare Sightings', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5 2a1 1 0 011 1v1h1a1 1 0 010 2H6v1a1 1 0 01-2 0V6H3a1 1 0 010-2h1V3a1 1 0 011-1zm0 10a1 1 0 011 1v1h1a1 1 0 110 2H6v1a1 1 0 11-2 0v-1H3a1 1 0 110-2h1v-1a1 1 0 011-1zM12 2a1 1 0 01.967.744L14.146 7.2 17.5 9.134a1 1 0 010 1.732l-3.354 1.935-1.18 4.455a1 1 0 01-1.933 0L9.854 12.8 6.5 10.866a1 1 0 010-1.732l3.354-1.935 1.18-4.455A1 1 0 0112 2z" clip-rule="evenodd" /></svg>' },
      { value: 'random', label: 'I\'m Feeling Lucky', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.395 2.553a1 1 0 00-1.45-.385c-.345.23-.614.558-.822.88-.214.33-.403.713-.57 1.116-.334.804-.614 1.768-.84 2.734a31.365 31.365 0 00-.613 3.58 2.64 2.64 0 01-.945-1.067c-.328-.68-.398-1.534-.398-2.654A1 1 0 005.05 6.05 6.981 6.981 0 003 11a7 7 0 1011.95-4.95c-.592-.591-.98-.985-1.348-1.467-.363-.476-.724-1.063-1.207-2.03zM12.12 15.12A3 3 0 017 13s.879.5 2.5.5c0-1 .5-4 1.25-4.5.5 1 .786 1.293 1.371 1.879A2.99 2.99 0 0113 13a2.99 2.99 0 01-.879 2.121z" clip-rule="evenodd" /></svg>' },
      { value: 'all', label: 'Species Catalog', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" /></svg>' },
    ]

    // TODO, fix bird id for non-unique birds

    const fetchUniqueBirds = async () => {
      const today = new Date().toLocaleDateString('en-CA');
      console.log(today);
      try {
        const response = await axios.get(`${API_BASE_URL}/sightings/unique`, {
          params: { date: today }
        })
        return response.data.map(bird => ({
          id: bird.id,
          name: bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageUrl: '/default_bird.png',  // Placeholder, will be updated later
        }))
      } catch (error) {
        console.error('Error fetching unique birds:', error)
        return []
      }
    }

    const fetchSightings = async (type) => {
      try {
        const response = await axios.get(`${API_BASE_URL}/sightings`, {
          params: { type }
        })
        return response.data.map(bird => ({
          id: type === 'random' ? bird.id : bird.common_name,  // Random birds have numeric ids
          name: bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageUrl: '/default_bird.png',  // Placeholder, will be updated later
        }))
      } catch (error) {
        console.error(`Error fetching ${type} birds:`, error)
        return []
      }
    }

    const fetchAllSpecies = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/species/all`)
        // For all species, we need to fetch additional details for each one
        const speciesWithDetails = await Promise.all(
          response.data.map(async (species) => {
            try {
              // Fetch bird details to get last detected date
              const detailsResponse = await axios.get(`${API_BASE_URL}/bird/${species.common_name}`)
              return {
                id: species.common_name,
                name: species.common_name,
                scientificName: species.scientific_name,
                lastDetected: detailsResponse.data.last_detected ? new Date(detailsResponse.data.last_detected) : null,
                imageUrl: '/default_bird.png',  // Placeholder, will be updated later
              }
            } catch (error) {
              // If details fetch fails, still show the bird
              return {
                id: species.common_name,
                name: species.common_name,
                scientificName: species.scientific_name,
                lastDetected: null,
                imageUrl: '/default_bird.png',
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
        const imageData = await fetchWikimediaImage(bird.name)
        if (imageData) {
          bird.imageUrl = imageData.imageUrl
          bird.authorName = imageData.authorName
          bird.authorUrl = imageData.authorUrl
          bird.licenseType = imageData.licenseType
        }
      }
    }

    const selectTab = async (tab) => {
      selectedTab.value = tab
      if (tab === 'recent') {
        birds.value = await fetchUniqueBirds()
        //TODO ERROR MESSAGE WHEN NO BIRDS
      } else if (tab === 'all') {
        birds.value = await fetchAllSpecies()
      } else if (tab === 'frequent' || tab === 'rare' || tab === 'random') {
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
        const response = await axios.get(`${API_BASE_URL}/wikimedia_image`, {
          params: { species: speciesName }
        })
        return response.data
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
