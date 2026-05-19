export const MODEL_TYPES = {
  V2: 'birdnet',
  V3: 'birdnet_v3'
}

export const FILTER_DEFAULTS = {
  [MODEL_TYPES.V2]: 0.03,
  [MODEL_TYPES.V3]: 0.15
}

export const modelTypeOptions = [
  {
    value: MODEL_TYPES.V2,
    title: 'BirdNET v2.4',
    description: 'Stable release, 6K species. Recommended.',
    label: 'BirdNET v2.4 (6K species)'
  },
  {
    value: MODEL_TYPES.V3,
    title: 'BirdNET v3.0',
    description: '11K species. Preview — needs more RAM.',
    label: 'BirdNET v3.0 (11K species, preview)'
  }
]
