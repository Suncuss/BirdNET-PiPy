import { describe, it, expect, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import ActivityOverviewCharts from '@/components/ActivityOverviewCharts.vue'

// destroyChart looks a canvas's chart up through Chart.getChart
const ChartMock = vi.hoisted(() => ({ getChart: vi.fn() }))
vi.mock('chart.js/auto', () => ({ default: ChartMock }))

const emptySpeciesLayout = { ticks: [], axisLeft: 0, axisWidth: 0, rowHeight: 0 }
const emptyTimeLayout = { ticks: [], axisTop: 0, axisHeight: 0, colWidth: 0, date: null }

const mountCharts = (props = {}) => mount(ActivityOverviewCharts, {
  props: {
    speciesAxisLayout: emptySpeciesLayout,
    timeAxisLayout: emptyTimeLayout,
    ...props
  },
  global: { stubs: { 'router-link': RouterLinkStub } }
})

describe('ActivityOverviewCharts', () => {
  it('exposes both canvases for the parent to draw on', () => {
    const wrapper = mountCharts()
    const canvases = wrapper.findAll('canvas').map((c) => c.element)
    expect(canvases).toHaveLength(2)
    expect(wrapper.vm.barCanvas).toBe(canvases[0])
    expect(wrapper.vm.heatmapCanvas).toBe(canvases[1])
  })

  it('renders the species names from the emitted axis layout', () => {
    const wrapper = mountCharts({
      speciesAxisLayout: {
        ticks: [{ y: 20, label: 'Blue Jay', commonName: 'Blue Jay' }],
        axisLeft: 0,
        axisWidth: 120,
        rowHeight: 18
      }
    })
    expect(wrapper.text()).toContain('Blue Jay')
  })

  it('destroys the charts drawn on its canvases when it goes away', () => {
    const wrapper = mountCharts()
    const canvases = wrapper.findAll('canvas').map((c) => c.element)
    const charts = new Map(canvases.map((canvas) => [canvas, { destroy: vi.fn() }]))
    ChartMock.getChart.mockImplementation((canvas) => charts.get(canvas))

    wrapper.unmount()

    for (const chart of charts.values()) expect(chart.destroy).toHaveBeenCalledTimes(1)
    ChartMock.getChart.mockReset()
  })
})
