<template>
  <!-- Below sm: one scrolling row instead of a wrapping one — on a phone the
       six links never fit, and wrapping stranded one or two alone on an extra
       line. -mx-4 bleeds the row to the screen edge so a clipped label reads
       as "more this way"; pl-2 plus the links' own padding starts the first
       label on the same line as the site title.
       From sm up the links fit on one line, so the row is the plain one it
       always was: every phone-only style here is max-sm:, and the phone-only
       rules in the stylesheet sit in one media block. -->
  <div
    class="relative max-sm:-mx-4 max-sm:mt-2"
    :style="CSS_LENGTHS"
  >
    <div
      ref="strip"
      class="nav-strip relative flex sm:flex-wrap sm:gap-4 max-sm:overflow-x-auto max-sm:whitespace-nowrap max-sm:pl-2 max-sm:pr-4"
      :class="{ 'more-left': moreLeft, 'more-right': moreRight }"
      :style="{ '--nav-gap': `${gap}px` }"
      @scroll.passive="syncEdges"
    >
      <router-link
        v-for="link in NAV_LINKS"
        :key="link.to"
        :to="link.to"
        class="nav-link relative shrink-0 hover:text-green-200 max-sm:pt-1.5 max-sm:pb-1 max-sm:text-[15px] max-sm:text-green-200 max-sm:hover:text-white"
        exact-active-class="nav-link-active"
      >
        {{ link.label }}
      </router-link>
    </div>
    <!-- Pointer-only helpers: keyboard focus already scrolls a link into view. -->
    <button
      v-show="moreLeft"
      type="button"
      class="nav-chevron left-0"
      tabindex="-1"
      aria-hidden="true"
      @click="scrollByPage(-1)"
    >
      <ChevronIcon
        direction="left"
        class="w-4 h-4"
      />
    </button>
    <button
      v-show="moreRight"
      type="button"
      class="nav-chevron right-0"
      tabindex="-1"
      aria-hidden="true"
      @click="scrollByPage(1)"
    >
      <ChevronIcon
        direction="right"
        class="w-4 h-4"
      />
    </button>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import ChevronIcon from '@/components/icons/ChevronIcon.vue'
import { computePeekGap } from '@/utils/peekGap'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/gallery', label: 'Gallery' },
  { to: '/live', label: 'Live Feed' },
  { to: '/charts', label: 'Charts' },
  { to: '/table', label: 'Table' },
  { to: '/settings', label: 'Settings' }
]

const BASE_GAP_PX = 4
const STRIP_PADDING_START_PX = 8 // pl-2
const STRIP_PADDING_END_PX = 16 // pr-4
const LINK_PADDING_PX = 8
const CHEVRON_PX = 28
const FADE_PX = 56
const EDGE_SLOP_PX = 2
// The stylesheet takes these from here, so each length has one definition.
const CSS_LENGTHS = {
  '--nav-link-pad': `${LINK_PADDING_PX}px`,
  '--nav-chevron': `${CHEVRON_PX}px`,
  '--nav-fade': `${FADE_PX}px`
}

const route = useRoute()
const strip = ref(null)
const gap = ref(BASE_GAP_PX)
const moreLeft = ref(false)
const moreRight = ref(false)

const syncEdges = () => {
  const el = strip.value
  if (!el) return
  const { scrollLeft } = el
  const max = el.scrollWidth - el.clientWidth
  moreLeft.value = scrollLeft > EDGE_SLOP_PX
  moreRight.value = max > EDGE_SLOP_PX && scrollLeft < max - EDGE_SLOP_PX
}

// Keep the current page's link on screen (clear of the faded edges) without
// scrollIntoView, which could also scroll the page itself.
const revealActive = () => {
  const el = strip.value
  const active = el?.querySelector('[aria-current="page"]')
  if (!active) return
  const left = active.offsetLeft - FADE_PX
  const right = active.offsetLeft + active.offsetWidth + FADE_PX
  if (left < el.scrollLeft) el.scrollLeft = Math.max(0, left)
  else if (right > el.scrollLeft + el.clientWidth) {
    // Leaving the start switches the left fade on over the first link, so
    // stay there while the active link at least clears the chevron; only
    // past that does it get the full fade-width margin.
    const clearsChevron = active.offsetLeft + active.offsetWidth + CHEVRON_PX <= el.clientWidth
    el.scrollLeft = clearsChevron ? 0 : right - el.clientWidth
  }
}

const layout = async () => {
  const el = strip.value
  if (!el) return
  gap.value = computePeekGap({
    itemWidths: Array.from(el.children, (link) => link.offsetWidth),
    viewportWidth: el.clientWidth,
    edgeInset: CHEVRON_PX,
    paddingStart: STRIP_PADDING_START_PX,
    paddingEnd: STRIP_PADDING_END_PX,
    itemPadding: LINK_PADDING_PX,
    baseGap: BASE_GAP_PX
  })
  await nextTick()
  revealActive()
  syncEdges()
}

const scrollByPage = (direction) => {
  const el = strip.value
  el.scrollBy({ left: direction * el.clientWidth * 0.6, behavior: 'smooth' })
}

let resizeObserver = null

onMounted(() => {
  // observe() delivers a first callback once layout is clean, so the explicit
  // call is only for environments without ResizeObserver.
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(layout)
    resizeObserver.observe(strip.value)
  } else {
    layout()
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})

// Keep the current page's link in view as the route changes. The active style
// doesn't change a link's width, so the gap needs no recomputing.
watch(() => route.path, () => {
  revealActive()
  syncEdges()
}, { flush: 'post' })
</script>

<style scoped>
/* Everything in this block is the phone row (Tailwind's max-sm); from sm up
   the links are left as plain as the template's classes make them. */
@media not all and (min-width: theme('screens.sm')) {
  /* Fade only the side that has more behind it (no mask at all when the row
     fits). The outer 40% of a fade is fully clear so a clipped label never
     shows through the chevron sitting on it. */
  .nav-strip {
    --fade-left: 0px;
    --fade-right: 0px;
    gap: var(--nav-gap);
  }
  .nav-strip.more-left {
    --fade-left: var(--nav-fade);
  }
  .nav-strip.more-right {
    --fade-right: var(--nav-fade);
  }
  .nav-strip.more-left,
  .nav-strip.more-right {
    mask-image: linear-gradient(
      90deg,
      transparent calc(var(--fade-left) * 0.4),
      #000 var(--fade-left),
      #000 calc(100% - var(--fade-right)),
      transparent calc(100% - var(--fade-right) * 0.4)
    );
  }
  /* style.css hides scrollbars globally by zeroing their width, which doesn't
     cover a horizontal bar's height. */
  .nav-strip::-webkit-scrollbar {
    display: none;
  }
  .nav-link {
    padding-inline: var(--nav-link-pad);
  }
  /* Current page: white label over a soft underline the width of the label
     (the link's padding is tap area, not part of the mark). */
  .nav-link-active {
    color: #fff;
  }
  .nav-link-active::after {
    content: '';
    position: absolute;
    left: var(--nav-link-pad);
    right: var(--nav-link-pad);
    bottom: 0;
    height: 2px;
    border-radius: 1px;
    background: rgb(255 255 255 / 0.5);
  }
}
.nav-chevron {
  position: absolute;
  top: 0;
  bottom: 0;
  width: var(--nav-chevron);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
</style>
