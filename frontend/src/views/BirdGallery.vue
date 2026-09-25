<template>
  <div class="px-4 sm:px-6 lg:px-8">
    <div class="mb-4 sm:mb-6 overflow-x-auto">
      <nav class="flex space-x-2 sm:space-x-4 border-b whitespace-nowrap">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          :class="[
            'py-2 px-3 sm:px-4 text-xs sm:text-sm font-medium flex items-center',
            selectedTab === tab.value
              ? 'border-b-2 border-blue-500 text-blue-600'
              : 'text-gray-500 hover:text-gray-700'
          ]"
          @click="selectTab(tab.value)"
        >
          <!-- eslint-disable vue/no-v-html -- icons are hardcoded constants, not user input -->
          <span
            class="mr-1.5"
            v-html="tab.icon"
          />
          <!-- eslint-enable vue/no-v-html -->
          {{ tab.label }}
        </button>
      </nav>
    </div>

    <div>
      <!-- Loading: show a spinner while an uncached tab's query runs, rather
           than leaving the previous tab's cards on screen until it resolves. -->
      <div
        v-if="isLoading"
        class="flex items-center justify-center py-16"
      >
        <Spinner class="h-8 w-8 text-green-600" />
        <span class="ml-3 text-gray-600">Loading...</span>
      </div>

      <div
        v-else-if="birds.length === 0"
        class="text-center text-gray-500 p-4"
      >
        No birds to display yet.
      </div>

      <!-- Grid of bird cards -->
      <div
        v-else
        class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-6"
      >
        <div
          v-for="bird in birds"
          :key="bird.commonName"
          :ref="el => registerCard(el, bird)"
          class="bird-card bg-white rounded-lg shadow-md overflow-hidden transition-all duration-300 hover:shadow-lg"
        >
          <!-- Wrap the image and related content inside the router-link -->
          <router-link
            :to="{ name: 'BirdDetails', params: { name: bird.commonName } }"
            class="group"
          >
            <div class="relative aspect-square overflow-hidden bg-gray-200">
              <!-- The illustration holds the card (with a sheen while its
                   photo loads); the photo mounts over it on reveal and
                   fades in. -->
              <img
                :src="defaultImageUrl"
                :alt="bird.imageState === 'shown' ? '' : bird.name"
                class="absolute inset-0 w-full h-full object-cover transition-transform duration-200 group-hover:scale-110"
              >
              <div
                v-if="bird.imageState === 'loading'"
                class="gallery-sheen absolute inset-0"
              />
              <img
                v-if="bird.imageState === 'shown'"
                :key="bird.imageUrl"
                :src="bird.imageUrl"
                :alt="bird.name"
                class="gallery-reveal absolute inset-0 w-full h-full object-cover transition-transform duration-200 group-hover:scale-110"
                :style="{ objectPosition: bird.focalPoint || '50% 50%' }"
                @error="onImageError(bird)"
              >
            </div>
          </router-link>

          <div
            class="p-3 sm:p-4 bg-gray-100 text-xs text-gray-600 transition-opacity duration-500"
            :class="bird.imageState === 'shown' ? 'opacity-100' : 'opacity-0'"
          >
            <template v-if="bird.hasCustomImage">
              <p>Custom image</p>
              <p>Uploaded by you</p>
            </template>
            <template v-else>
              <p class="truncate">
                Photo by <a
                  :href="bird.authorUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-blue-600 underline"
                >{{ bird.authorName
                }}</a>
              </p>
              <p>
                Licensed under {{ bird.licenseType }}
              </p>
            </template>
          </div>
          <div class="p-3 sm:p-4">
            <h2 class="text-lg font-semibold mb-2">
              {{ bird.name }}
            </h2>
            <p class="text-sm text-gray-600 mb-1">
              {{ bird.scientificName }}
            </p>
            <p class="text-xs text-gray-500">
              {{ bird.lastDetected ? `Last detected: ${formatDate(bird.lastDetected)}` : 'Detection info available in details' }}
            </p>
            <AppButton
              :to="{ name: 'BirdDetails', params: { name: bird.commonName } }"
              class="mt-2"
            >
              Learn More
            </AppButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Scroll to Top FAB -->
    <ScrollToTopButton />
  </div>
</template>

<script>
import { ref, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import api from '@/services/api'
import { getBirdImageUrl, getDefaultBirdImageUrl } from '@/services/media'
import { useSmartCrop } from '@/composables/useSmartCrop'
import { createRevealScheduler } from '@/utils/revealScheduler'
import AppButton from '@/components/AppButton.vue'
import ScrollToTopButton from '@/components/ScrollToTopButton.vue'
import Spinner from '@/components/Spinner.vue'

export default {
  name: 'BirdGallery',
  components: {
    AppButton,
    ScrollToTopButton,
    Spinner
  },
  setup() {
    const defaultImageUrl = getDefaultBirdImageUrl()
    const selectedTab = ref('recent')
    const birds = ref([])
    // True only while an uncached tab's query is in flight — see selectTab.
    const isLoading = ref(false)
    const { calculateFocalPoint } = useSmartCrop()
    const tabs = [
      { value: 'recent', label: 'Today\'s Detections', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd" /></svg>' },
      { value: 'frequent', label: 'Most Frequent', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" clip-rule="evenodd" /></svg>' },
      { value: 'rare', label: 'Least Frequent', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12 13a1 1 0 100 2h5a1 1 0 001-1V9a1 1 0 10-2 0v2.586l-4.293-4.293a1 1 0 00-1.414 0L8 9.586 3.707 5.293a1 1 0 00-1.414 1.414l5 5a1 1 0 001.414 0L11 9.414 14.586 13H12z" clip-rule="evenodd" /></svg>' },
      { value: 'all', label: 'Species Catalog', icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" /></svg>' },
    ]

    // Per-tab cache of already-loaded bird lists. Switching back to a visited
    // tab renders instantly; an entry older than STALE_THRESHOLD is shown at
    // once and then refreshed in the background.
    const tabCache = {}
    const STALE_THRESHOLD = 2 * 60 * 1000  // 2 minutes
    let hasBeenDeactivated = false

    // Bumped on every tab switch so background image work from a previous tab
    // can detect it is stale and stop mutating cards the user no longer sees.
    let imageLoadVersion = 0

    // Card images load lazily, gated by an IntersectionObserver so only cards
    // in (or near) the viewport cost a Wikimedia lookup — Species Catalog can
    // hold 200+ cards but only ~12 are ever on screen. Intersecting cards are
    // queued and loaded IMAGE_CONCURRENCY at a time. This is also the only
    // throttle on thumbnail downloads, which the browser fetches straight from
    // Wikimedia's image CDN; the metadata lookups behind them are additionally
    // capped by the backend across every viewer.
    const IMAGE_CONCURRENCY = 4
    const cardBirds = new WeakMap()  // card element -> bird (no ad-hoc DOM props)
    const loadQueue = []
    let activeLoads = 0

    // Each card's image lifecycle, in bird.imageState:
    //   'idle'    on the illustration, not yet queued
    //   'loading' queued, loading, or waiting for its turn to reveal
    //             (bird.loadVersion records which tab visit queued it)
    //   'shown'   photo revealed
    //   'none'    nothing to show (no photo, failed lookup, or broken image)
    // registerCard re-fires on every render, so only this decides whether a
    // card still needs loading. A 'loading' card from an abandoned visit
    // (stale loadVersion) is picked up again when its tab is revisited.
    const needsLoad = (bird) => bird.imageState === 'idle' ||
      (bird.imageState === 'loading' && bird.loadVersion !== imageLoadVersion)
    let imageObserver = null
    const ioSupported = typeof IntersectionObserver !== 'undefined'

    const fetchUniqueBirds = async () => {
      const today = new Date().toLocaleDateString('en-CA');
      try {
        const { data } = await api.get('/sightings/unique', {
          params: { date: today }
        })
        return data.map(bird => ({
          commonName: bird.common_name,
          name: bird.display_common_name || bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageState: 'idle',
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
          commonName: bird.common_name,
          name: bird.display_common_name || bird.common_name,
          scientificName: bird.scientific_name,
          lastDetected: new Date(bird.timestamp),
          imageState: 'idle',
        }))
      } catch (error) {
        console.error(`Error fetching ${type} birds:`, error)
        return []
      }
    }

    const fetchAllSpecies = async () => {
      try {
        const { data: speciesList } = await api.get('/species/all')
        // /species/all returns last_detected per species — no per-species fetch.
        return speciesList.map(species => ({
          commonName: species.common_name,
          name: species.display_common_name || species.common_name,
          scientificName: species.scientific_name,
          lastDetected: species.last_detected ? new Date(species.last_detected) : null,
          imageState: 'idle',
        }))
      } catch (error) {
        console.error('Error fetching all species:', error)
        return []
      }
    }

    // Show resolved image fields on a card. The photo <img> mounts (keyed by
    // URL) over the illustration and its CSS animation fades it in.
    const applyResolvedImage = (bird, fields) => {
      bird.imageUrl = fields.imageUrl
      bird.imageState = 'shown'
      bird.hasCustomImage = Boolean(fields.hasCustomImage)
      bird.focalPoint = fields.focalPoint
      if (!bird.hasCustomImage) {
        bird.authorName = fields.authorName
        bird.authorUrl = fields.authorUrl
        bird.licenseType = fields.licenseType
      }
    }

    // Resolve one card's image fields (lookup + focal point, which also
    // preloads the thumbnail) without showing it — the reveal scheduler
    // decides when. Returns null for nothing to show.
    const resolveBirdImage = async (bird, version) => {
      try {
        const imageData = await fetchWikimediaImage(bird.commonName)
        // Skip smart-crop for a tab the user already left; its result would
        // be dropped anyway.
        if (!imageData || version !== imageLoadVersion) return null

        let fields
        if (imageData.hasCustomImage) {
          fields = {
            imageUrl: getBirdImageUrl(bird.commonName),
            hasCustomImage: true,
            focalPoint: '50% 50%',
          }
        } else {
          // Display the CDN thumbnail (500px), not the multi-MB original: the
          // backend already returns thumbUrl, and full-size upload.wikimedia.org
          // URLs are the ones most prone to 429s (see investigation doc).
          const displayUrl = imageData.thumbUrl || imageData.imageUrl
          // Calculate the focal point first — this also preloads the image
          const focalPoint = await calculateFocalPoint(displayUrl)
          fields = { ...imageData, imageUrl: displayUrl, focalPoint }
        }
        return fields
      } catch (error) {
        console.error(`Error loading image for ${bird.commonName}:`, error)
        return null
      }
    }

    // Loads finish in any order; the scheduler reveals them in reading order
    // so the grid fills in as one wave instead of flickering at random.
    const revealScheduler = createRevealScheduler({
      reveal: (bird, fields) => applyResolvedImage(bird, fields)
    })

    // Start queued loads up to IMAGE_CONCURRENCY. The queue and scheduler are
    // reset on every version bump, so only a load's result can go stale.
    const pumpLoads = () => {
      while (activeLoads < IMAGE_CONCURRENCY && loadQueue.length) {
        const { bird, version } = loadQueue.shift()
        const ticket = revealScheduler.add(bird)
        activeLoads++
        resolveBirdImage(bird, version)
          .then(fields => {
            if (version !== imageLoadVersion) return
            if (!fields) bird.imageState = 'none'
            revealScheduler.settle(ticket, fields)
          })
          .finally(() => {
            activeLoads--
            pumpLoads()
          })
      }
    }

    const enqueueLoad = (bird, version) => {
      if (version !== imageLoadVersion || !needsLoad(bird)) return
      bird.imageState = 'loading'
      bird.loadVersion = version
      loadQueue.push({ bird, version })
      pumpLoads()
    }

    const teardownImageObserver = () => {
      if (imageObserver) {
        imageObserver.disconnect()
        imageObserver = null
      }
    }

    // Drop pending image work. Bumping the version makes in-flight loads
    // discard their results; clearing the queue drops anything not yet
    // started. Used when the view goes off-screen/unmounts.
    const cancelPendingImageLoads = () => {
      imageLoadVersion++
      resetLoadQueue()
    }

    // Drop queued cards and unrevealed results. In-flight loads keep their
    // slot until they finish, then see the stale version and reveal nothing.
    const resetLoadQueue = () => {
      loadQueue.length = 0
      revealScheduler.reset()
    }

    // (Re)create the observer for the current tab. `version` is captured so a
    // late intersection from a previous tab is dropped by enqueueLoad's guard.
    // Use the callback's own `observer` arg (not the outer `imageObserver`,
    // which may already be null or a newer observer when a late callback fires).
    const setupImageObserver = (version) => {
      teardownImageObserver()
      if (!ioSupported) return
      imageObserver = new IntersectionObserver((entries, observer) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const bird = cardBirds.get(entry.target)
          observer.unobserve(entry.target)
          if (bird) enqueueLoad(bird, version)
        }
      }, { rootMargin: '300px 0px' })  // start loading ~one card-row ahead
    }

    // Function ref on each card. Observes cards that still need an image;
    // settled cards (including ones cached from an earlier visit) are skipped.
    // With no observer (fallback env) the card loads immediately, ungated by
    // viewport.
    const registerCard = (el, bird) => {
      if (!el || !bird || !needsLoad(bird)) return
      cardBirds.set(el, bird)
      if (imageObserver) {
        imageObserver.observe(el)
      } else if (!ioSupported) {
        // No IntersectionObserver in this env — load ungated by viewport.
        enqueueLoad(bird, imageLoadVersion)
      }
      // else: observer not yet (re)created for the current tab — this is a
      // stale render of the *outgoing* tab (the selectedTab change re-renders
      // the old list while loadTab is still pending). Ignore it; the observer
      // is set up only after birds.value is replaced, so the live tab's cards
      // register against the live observer.
    }

    // <img @error>: a thumbnail/original that fails to load (404, network,
    // upstream 429 on the image CDN) must not strand the card on a broken
    // image. Unmount it back to the illustration; never retry the failed URL.
    const onImageError = (bird) => {
      bird.imageState = 'none'
    }

    const loadTab = (tab) => {
      if (tab === 'recent') return fetchUniqueBirds()
      if (tab === 'all') return fetchAllSpecies()
      return fetchSightings(tab)
    }

    const selectTab = async (tab) => {
      selectedTab.value = tab
      // New version stamp: in-flight work from the previous tab compares
      // against it, detects it is stale, and stops overwriting this tab.
      const version = ++imageLoadVersion
      // Stale results would hold the head of the new tab's reveal order.
      resetLoadQueue()
      // Stop the previous tab's observer NOW, and leave it null across the
      // await below. The selectedTab change above triggers a re-render of the
      // *outgoing* list; with no observer in place, registerCard ignores those
      // stale cards instead of loading them under the new version. The observer
      // is (re)created only after birds.value holds the tab we are switching to.
      teardownImageObserver()

      const cached = tabCache[tab]
      // Spinner only when there's nothing cached to show: a cached tab (fresh or
      // stale) renders its own cards immediately, so it never shows the spinner —
      // a stale one refreshes underneath them. An uncached tab has nothing to
      // display, so the spinner replaces the outgoing tab's cards while it loads.
      isLoading.value = !cached

      if (cached) {
        const fresh = Date.now() - cached.at <= STALE_THRESHOLD
        // Assign a fresh array (same bird objects) so the v-for re-renders and
        // the card function refs re-fire. On keep-alive reactivation birds.value
        // is already === cached.birds; assigning it verbatim would be a no-op,
        // so registerCard would never run and placeholders would never resume.
        birds.value = cached.birds.slice()  // render the visited tab instantly
        if (fresh) {
          // Observe the cached cards: any a prior interrupted visit left on a
          // placeholder load as they scroll in; resolved cards are skipped.
          setupImageObserver(version)
          return
        }
        // Stale: show cached instantly but don't observe — about to refresh.
      } else {
        birds.value = []  // clear outgoing tab's cards; the spinner shows instead
      }

      const loaded = await loadTab(tab)
      // Drop the result if another tab switch started while data was loading;
      // that superseding selectTab now owns isLoading / birds.
      if (version !== imageLoadVersion) return
      tabCache[tab] = { birds: loaded, at: Date.now() }
      birds.value = loaded
      isLoading.value = false
      // Observer created after the swap, so only the live tab's cards register.
      setupImageObserver(version)
    }

    // Patch a single card in place when the customize-image modal applies a
    // change, without re-fetching the API.
    const applyImageChange = async (detail) => {
      if (!detail?.species || !detail.imageUrl) return
      const bird = birds.value.find(b => b.commonName === detail.species)
      if (!bird) return
      // Match the grid: display the thumbnail when the change is a Wikimedia
      // choice (uploads carry no thumbUrl and fall back to their own URL).
      const displayUrl = detail.thumbUrl || detail.imageUrl
      const focalPoint = detail.hasCustomImage
        ? '50% 50%'
        : await calculateFocalPoint(displayUrl)
      applyResolvedImage(bird, { ...detail, imageUrl: displayUrl, focalPoint })
    }

    const onBirdImageChanged = (event) => {
      applyImageChange(event.detail)
    }

    onMounted(() => {
      window.addEventListener('bird-image:changed', onBirdImageChanged)
      selectTab(selectedTab.value)
    })

    onUnmounted(() => {
      window.removeEventListener('bird-image:changed', onBirdImageChanged)
      teardownImageObserver()
      cancelPendingImageLoads()
    })

    onDeactivated(() => {
      hasBeenDeactivated = true
      // Stop all image work while the keep-alive'd view is off-screen:
      // disconnect the observer, drop the queue, and invalidate in-flight
      // loads. onActivated re-runs selectTab, which rebuilds everything.
      teardownImageObserver()
      cancelPendingImageLoads()
    })

    onActivated(() => {
      // selectTab() shows the cached tab instantly and refreshes it if stale.
      if (hasBeenDeactivated) selectTab(selectedTab.value)
    })

    const formatDate = (date) => {
      return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
    }

    const fetchWikimediaImage = async (speciesName) => {
      try {
        // for_display_only: the gallery only needs hasCustomImage / image URLs,
        // so the backend can skip the Wikimedia lookup for custom-upload species.
        const { data } = await api.get('/wikimedia_image', {
          params: { species: speciesName, for_display_only: 1 }
        })
        return data
      } catch (error) {
        console.error(`Error fetching Wikimedia image for ${speciesName}:`, error)
        return null
      }
    }

    return {
      selectedTab,
      isLoading,
      tabs,
      birds,
      formatDate,
      selectTab,
      registerCard,
      onImageError,
      defaultImageUrl,
    }
  }
}
</script>

<style scoped>
/* The photo mounts over the illustration and fades in. `backwards` holds it
   transparent until the animation starts, then releases the element so the
   hover scale transform still applies. */
.gallery-reveal {
  animation: gallery-reveal 500ms cubic-bezier(0.2, 0, 0, 1) backwards;
}

@keyframes gallery-reveal {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Loading sheen over the illustration while the card's photo is on its way,
   so unloaded cards read as "loading", not as finished cards. */
.gallery-sheen {
  overflow: hidden;
  pointer-events: none;
}

.gallery-sheen::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 30%, rgb(255 255 255 / 0.35) 50%, transparent 70%);
  transform: translateX(-100%);
  animation: gallery-sheen 1.8s ease-in-out infinite;
}

@keyframes gallery-sheen {
  to { transform: translateX(100%); }
}

@media (prefers-reduced-motion: reduce) {
  .gallery-reveal,
  .gallery-sheen::after {
    animation: none;
  }
}
</style>
