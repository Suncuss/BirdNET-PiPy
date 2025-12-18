import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import Detections from '@/views/Detections.vue'

describe('Detections', () => {
  it('renders placeholder content', () => {
    const wrapper = mount(Detections)

    expect(wrapper.text()).toContain('Detections')
    expect(wrapper.text()).toContain('Detection history will appear here')
  })
})
