<template>
  <div
    class="absolute inset-y-0 left-0 pointer-events-none species-axis-links"
    :style="containerStyle"
  >
    <router-link
      v-for="tick in renderableTicks"
      :key="tick.commonName"
      :to="{ name: 'BirdDetails', params: { name: tick.commonName } }"
      class="absolute right-0 pr-2 flex items-center justify-end text-xs text-gray-700 hover:text-blue-600 hover:underline pointer-events-auto overflow-hidden whitespace-nowrap transition-colors duration-200"
      :style="tickStyle(tick)"
      :title="tick.label"
    >
      <!-- pr-2 is the gap to the bars that useBirdCharts sizes the axis for
           (SPECIES_LABEL_GAP_PX). The label is its own element so an overlong
           name ends in an ellipsis: text-overflow has no effect on a flex
           container's bare text, which was clipped at its start instead. -->
      <span class="truncate">{{ tick.label }}</span>
    </router-link>
  </div>
</template>

<script>
export default {
  name: 'SpeciesAxisLinks',
  props: {
    ticks: {
      type: Array,
      default: () => []
    },
    axisLeft: {
      type: Number,
      default: 0
    },
    axisWidth: {
      type: Number,
      default: 0
    },
    rowHeight: {
      type: Number,
      default: 16
    }
  },
  computed: {
    containerStyle() {
      return {
        left: `${this.axisLeft}px`,
        width: `${this.axisWidth}px`
      }
    },
    renderableTicks() {
      return this.ticks.filter(t => t && t.commonName)
    }
  },
  methods: {
    tickStyle(tick) {
      const h = Math.max(this.rowHeight, 14)
      return {
        top: `${tick.y - h / 2}px`,
        height: `${h}px`,
        left: '0',
        width: '100%'
      }
    }
  }
}
</script>

<style scoped>
/* Match Chart.js's default tick font so the overlay labels render at the same width
   as the canvas would. System fonts (Tailwind default) render visibly wider than
   Helvetica/Arial. */
.species-axis-links {
  font-family: 'Helvetica Neue', 'Helvetica', 'Arial', sans-serif;
}
</style>
