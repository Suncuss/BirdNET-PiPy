<template>
  <div class="flex h-full">
    <div class="w-full lg:w-1/3 lg:pr-2 relative">
      <canvas
        ref="barCanvas"
        class="h-full"
      />
      <SpeciesAxisLinks
        :ticks="speciesAxisLayout.ticks"
        :axis-left="speciesAxisLayout.axisLeft"
        :axis-width="speciesAxisLayout.axisWidth"
        :row-height="speciesAxisLayout.rowHeight"
      />
    </div>
    <div class="hidden lg:block lg:w-2/3 lg:pl-2 h-full">
      <!-- Inner wrapper is the positioning context: it has no padding,
           so the absolute overlay's origin matches the canvas origin
           (the chart's pixel coords are canvas-relative). -->
      <div class="h-full relative">
        <canvas
          ref="heatmapCanvas"
          class="h-full"
        />
        <TimeAxisLinks
          :ticks="timeAxisLayout.ticks"
          :axis-top="timeAxisLayout.axisTop"
          :axis-height="timeAxisLayout.axisHeight"
          :col-width="timeAxisLayout.colWidth"
          :date="timeAxisLayout.date"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
// The Activity Overview chart pair: species totals (bars) and, from lg up, the
// hourly heatmap beside them, row for row. The parent draws on the exposed
// canvases with useBirdCharts and passes back the axis layouts those charts
// emit. It fills its parent, which sizes it (.activity-chart-region in
// style.css).
import { ref, onBeforeUnmount } from 'vue'
import { useChartHelpers } from '@/composables/useChartHelpers'
import SpeciesAxisLinks from '@/components/SpeciesAxisLinks.vue'
import TimeAxisLinks from '@/components/TimeAxisLinks.vue'

defineProps({
  speciesAxisLayout: {
    type: Object,
    required: true
  },
  timeAxisLayout: {
    type: Object,
    required: true
  }
})

const barCanvas = ref(null)
const heatmapCanvas = ref(null)

// The canvases go when this component does — including when a page swaps it
// for its empty or error placeholder — so the charts drawn on them are
// released here rather than by each page.
const { destroyChart } = useChartHelpers()
onBeforeUnmount(() => {
  destroyChart(barCanvas)
  destroyChart(heatmapCanvas)
})

defineExpose({ barCanvas, heatmapCanvas })
</script>
