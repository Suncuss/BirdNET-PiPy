/**
 * Tests for DetectionInfoModal component
 */
import { mount } from '@vue/test-utils'
import { describe, it, expect, beforeEach } from 'vitest'
import DetectionInfoModal from '@/components/DetectionInfoModal.vue'
import { useUnitSettings } from '@/composables/useUnitSettings'

describe('DetectionInfoModal', () => {
  const mountModal = (props = {}) => mount(DetectionInfoModal, {
    props: {
      isVisible: true,
      detection: null,
      ...props
    }
  })

  // Ensure tests start with metric units (the default)
  beforeEach(() => {
    const unitSettings = useUnitSettings()
    unitSettings.resetState()
  })

  describe('Rendering', () => {
    it('renders when isVisible is true', () => {
      const wrapper = mountModal({ detection: { common_name: 'Test Bird', extra: {} } })
      expect(wrapper.text()).toContain('Detection Info')
    })

    it('does not render when isVisible is false', () => {
      const wrapper = mountModal({ isVisible: false })
      expect(wrapper.find('.fixed').exists()).toBe(false)
    })

    it('displays bird common name in header', () => {
      const wrapper = mountModal({
        detection: { common_name: 'American Robin', extra: {} }
      })
      expect(wrapper.text()).toContain('American Robin')
    })

    it('shows close button (X icon)', () => {
      const wrapper = mountModal({ detection: { common_name: 'Test', extra: {} } })
      const closeButton = wrapper.find('button[title="Close"]')
      expect(closeButton.exists()).toBe(true)
    })
  })

  describe('Weather Display', () => {
    it('shows weather section when weather data is present', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: {
            temp: 15.2,
            humidity: 80,
            precip: 0.0,
            wind: 8.5,
            code: 3,
            cloud_cover: 20,
            pressure: 1013
          }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Weather Conditions')
      expect(wrapper.text()).toContain('15.2°C')
      expect(wrapper.text()).toContain('80%')
      expect(wrapper.text()).toContain('8.5 km/h')
      expect(wrapper.text()).toContain('20%')
      expect(wrapper.text()).toContain('0.0 mm')
      expect(wrapper.text()).toContain('1013.0 hPa')
    })

    it('shows clear sky weather description for code 0', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 20, humidity: 50, precip: 0, wind: 5, code: 0, cloud_cover: 10, pressure: 1015 }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Clear sky')
    })

    it('shows overcast weather description for code 3', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 15, humidity: 80, precip: 0, wind: 8, code: 3, cloud_cover: 90, pressure: 1010 }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Overcast')
    })

    it('shows rain description for code 61', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 12, humidity: 95, precip: 2.5, wind: 15, code: 61, cloud_cover: 100, pressure: 1005 }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Slight rain')
    })

    it('shows thunderstorm description for code 95', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 18, humidity: 90, precip: 5.0, wind: 25, code: 95, cloud_cover: 100, pressure: 1000 }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Thunderstorm')
    })

    it('shows unknown for unrecognized weather code', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 15, humidity: 70, precip: 0, wind: 5, code: 999, cloud_cover: 30, pressure: 1012 }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Unknown')
    })

    it('does not show weather section when no weather data', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          ebird_code: 'amerob',
          model: 'birdnet'
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).not.toContain('Weather Conditions')
    })

    it('handles detection with empty extra field', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {}
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).not.toContain('Weather Conditions')
      expect(wrapper.text()).toContain('No additional metadata available')
    })

    it('handles detection with extra as JSON string', () => {
      const detection = {
        common_name: 'American Robin',
        extra: JSON.stringify({
          weather: { temp: 18, humidity: 65, precip: 0, wind: 10, code: 2, cloud_cover: 40, pressure: 1012 }
        })
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Weather Conditions')
      expect(wrapper.text()).toContain('18.0°C')
      expect(wrapper.text()).toContain('Partly cloudy')
    })

    it('handles detection with null extra field', () => {
      const detection = {
        common_name: 'American Robin',
        extra: null
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('No additional metadata available')
    })

    it('handles detection without extra field', () => {
      const detection = {
        common_name: 'American Robin'
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('No additional metadata available')
    })
  })

  describe('Metadata Display', () => {
    it('shows metadata section for non-weather extra data', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          ebird_code: 'amerob',
          model: 'birdnet',
          model_version: '2.4'
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Detection Metadata')
      expect(wrapper.text()).toContain('amerob')
      expect(wrapper.text()).toContain('birdnet')
      expect(wrapper.text()).toContain('2.4')
    })

    it('shows both weather and metadata when both present', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 15, humidity: 70, precip: 0, wind: 5, code: 1, cloud_cover: 20, pressure: 1013 },
          ebird_code: 'amerob',
          model: 'birdnet'
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Weather Conditions')
      expect(wrapper.text()).toContain('Detection Metadata')
      expect(wrapper.text()).toContain('15.0°C')
      expect(wrapper.text()).toContain('amerob')
    })

    it('does not show weather in metadata section (filters it out)', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: { temp: 15, humidity: 70, precip: 0, wind: 5, code: 1, cloud_cover: 20, pressure: 1013 },
          ebird_code: 'amerob'
        }
      }
      const wrapper = mountModal({ detection })

      // Find the metadata section and verify weather is not listed there
      const metadataSection = wrapper.findAll('h4').find(h => h.text() === 'Detection Metadata')
      expect(metadataSection).toBeDefined()

      // The word "weather" as a key should not appear in the metadata list
      const metadataItems = wrapper.findAll('dt')
      const weatherKeyPresent = metadataItems.some(dt => dt.text().toLowerCase().includes('weather'))
      expect(weatherKeyPresent).toBe(false)
    })

    it('formats snake_case keys as Title Case', () => {
      const detection = {
        common_name: 'American Robin',
        extra: {
          ebird_code: 'amerob',
          model_version: '2.4'
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('Ebird code')
      expect(wrapper.text()).toContain('Model version')
    })
  })

  describe('Close Action', () => {
    it('emits close event when close button clicked', async () => {
      const detection = { common_name: 'Test', extra: {} }
      const wrapper = mountModal({ detection })

      await wrapper.find('button[title="Close"]').trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close event when footer close button clicked', async () => {
      const detection = { common_name: 'Test', extra: {} }
      const wrapper = mountModal({ detection })

      // Find and click the footer Close button
      const footerButton = wrapper.findAll('button').find(btn => btn.text() === 'Close')
      await footerButton.trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close event when backdrop clicked', async () => {
      const detection = { common_name: 'Test', extra: {} }
      const wrapper = mountModal({ detection })

      // Click on the backdrop (the outer div with bg-black/50)
      const backdrop = wrapper.find('.bg-black\\/50')
      await backdrop.trigger('click')

      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })

  describe('Imperial Units Display', () => {
    it('shows imperial units when useMetricUnits is false', () => {
      const unitSettings = useUnitSettings()
      unitSettings.setUseMetricUnits(false)

      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: {
            temp: 0,        // 0°C = 32°F
            humidity: 80,
            precip: 25.4,   // 25.4mm = 1 inch
            wind: 16.09,    // ~10 mph
            code: 0,
            cloud_cover: 20,
            pressure: 1013.25  // ~29.92 inHg
          }
        }
      }
      const wrapper = mountModal({ detection })

      // Check temperature is in Fahrenheit
      expect(wrapper.text()).toContain('32.0°F')
      // Check wind is in mph
      expect(wrapper.text()).toContain('mph')
      // Check precipitation is in inches
      expect(wrapper.text()).toContain('in')
      // Check pressure is in inHg
      expect(wrapper.text()).toContain('inHg')
    })

    it('converts temperature correctly to Fahrenheit', () => {
      const unitSettings = useUnitSettings()
      unitSettings.setUseMetricUnits(false)

      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: {
            temp: 100,      // 100°C = 212°F (boiling point)
            humidity: 50,
            precip: 0,
            wind: 10,
            code: 0,
            cloud_cover: 0,
            pressure: 1013
          }
        }
      }
      const wrapper = mountModal({ detection })

      expect(wrapper.text()).toContain('212.0°F')
    })

    it('switches back to metric when toggled', () => {
      const unitSettings = useUnitSettings()

      // Start with imperial
      unitSettings.setUseMetricUnits(false)

      const detection = {
        common_name: 'American Robin',
        extra: {
          weather: {
            temp: 20,
            humidity: 50,
            precip: 5,
            wind: 10,
            code: 0,
            cloud_cover: 10,
            pressure: 1015
          }
        }
      }

      // Mount with imperial
      let wrapper = mountModal({ detection })
      expect(wrapper.text()).toContain('°F')

      // Switch to metric
      unitSettings.setUseMetricUnits(true)

      // Remount to see changes
      wrapper = mountModal({ detection })
      expect(wrapper.text()).toContain('20.0°C')
      expect(wrapper.text()).toContain('km/h')
    })
  })
})
