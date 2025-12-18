import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import BirdDetectionList from '@/views/BirdDetectionList.vue'

const pushSpy = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushSpy })
}))

describe('BirdDetectionList', () => {
  beforeEach(() => {
    pushSpy.mockClear()
    vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('10:15:00')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountList = (detections) => mount(BirdDetectionList, {
    props: { detections }
  })

  const sampleDetections = [
    {
      common_name: 'Blue Jay',
      scientific_name: 'Cyanocitta cristata',
      confidence: 0.87,
      timestamp: '2024-01-01T10:15:00Z',
      justUpdated: true
    },
    {
      common_name: 'Cardinal',
      scientific_name: 'Cardinalis cardinalis',
      confidence: 0.93,
      timestamp: '2024-01-01T11:20:00Z',
      justUpdated: false
    }
  ]

  it('renders detections with names, confidence, and timestamp', () => {
    const wrapper = mountList(sampleDetections)

    expect(wrapper.text()).toContain('Blue Jay')
    expect(wrapper.text()).toContain('Cyanocitta cristata')
    expect(wrapper.text()).toContain('87%')
    expect(wrapper.text()).toContain('10:15:00')
  })

  it('applies highlight styling when detection was just updated', () => {
    const wrapper = mountList(sampleDetections)
    const firstItem = wrapper.findAll('li')[0]

    // When justUpdated is true, the item gets highlight styling via Tailwind classes
    expect(firstItem.classes()).toContain('!bg-green-100')
    expect(firstItem.classes()).toContain('scale-[1.02]')
  })

  it('navigates to bird details on click', async () => {
    const wrapper = mountList(sampleDetections)
    const firstItem = wrapper.findAll('li')[0]

    await firstItem.trigger('click')

    expect(pushSpy).toHaveBeenCalledWith({
      name: 'BirdDetails',
      params: { name: 'Blue Jay' }
    })
  })
})
