# BirdNET-PiPy Frontend Test Suite

This directory contains all tests for the BirdNET-PiPy Vue.js frontend, organized by functionality.

## Test Structure

```
tests/
├── App.test.js                           # Root App component tests (2 tests)
├── components/                           # Reusable component tests (7 files)
│   ├── AddNotificationModal.test.js      # Notification modal (36 tests)
│   ├── AlertBanner.test.js               # Alert banner component (11 tests)
│   ├── DetectionInfoModal.test.js        # Detection info modal (25 tests)
│   ├── LoginModal.test.js                # Authentication modal (22 tests)
│   ├── SetupWizard.test.js               # Setup wizard flow (17 tests)
│   ├── SpeciesFilterModal.test.js        # Species filter modal (3 tests)
│   └── UpdateManager.test.js             # System update component (5 tests)
├── composables/                          # Vue composition function tests (12 files)
│   ├── useAudioPlayer.test.js            # Audio playback (23 tests)
│   ├── useAuth.test.js                   # Authentication composable (35 tests)
│   ├── useBirdCharts.test.js             # Chart.js integration (24 tests)
│   ├── useChartColors.test.js            # Color palette (8 tests)
│   ├── useChartHelpers.test.js           # Chart utility functions (23 tests)
│   ├── useDateNavigation.test.js         # Date navigation (39 tests)
│   ├── useFetchBirdData.test.js          # API data fetching (27 tests)
│   ├── useLogger.test.js                 # Logging utility (18 tests)
│   ├── useServiceRestart.test.js         # Service restart polling (7 tests)
│   ├── useSmartCrop.test.js              # Smart image cropping (16 tests)
│   ├── useSystemUpdate.test.js           # System update composable (19 tests)
│   └── useTableData.test.js             # Table data management (31 tests)
├── router/                               # Vue Router tests (1 file)
│   └── router.test.js                    # Route configuration and resolution (24 tests)
└── views/                                # View component tests (10 files)
    ├── BirdDetails.test.js               # Bird details page (15 tests)
    ├── BirdDetectionList.test.js         # Detection list component (3 tests)
    ├── BirdGallery.test.js               # Bird gallery page (8 tests)
    ├── Charts.test.js                    # Charts page (14 tests)
    ├── Dashboard.test.js                 # Dashboard page (21 tests)
    ├── Detections.test.js                # Detections page (1 test)
    ├── LiveFeed.test.js                  # Live audio stream page (15 tests)
    ├── Settings.test.js                  # Settings page (58 tests)
    ├── Spectrogram.test.js               # Spectrogram component (2 tests)
    └── Table.test.js                     # Detection table (17 tests)
```

## Running Tests

### Quick Start

```bash
# Navigate to frontend directory
cd frontend/

# Run all tests once
npm run test

# Run tests in watch mode (re-run on file changes)
npm run test:watch

# Run tests with coverage report
npm run test:coverage
```

### Using npm scripts

| Command | Description |
|---------|-------------|
| `npm run test` | Run all tests once and exit |
| `npm run test:watch` | Run tests in interactive watch mode |
| `npm run test:coverage` | Run tests with code coverage report |

### Direct Vitest Commands

```bash
# Run a specific test file
npx vitest run tests/composables/useAuth.test.js

# Run tests matching a pattern
npx vitest run -t "useAuth"

# Run tests for a specific category
npx vitest run tests/composables/
npx vitest run tests/views/
npx vitest run tests/components/

# Run with verbose output
npx vitest run --reporter=verbose

# Run in UI mode (opens browser interface)
npx vitest --ui
```

## Test Configuration

Tests are configured in `vitest.config.js`:

```javascript
{
  test: {
    environment: 'happy-dom',     // DOM simulation
    globals: true,                // Global test functions (describe, it, expect)
    include: ['tests/**/*.{test,spec}.{js,ts}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{js,vue}'],
      exclude: ['src/main.js']
    }
  }
}
```

## Test Categories

### App Tests (`App.test.js`)
Tests for the root `App.vue` component.

| Tests | Description |
|-------|-------------|
| 2 | Navigation rendering, logging on mount |

### Component Tests (`components/`)
Tests for reusable Vue components.

| File | Tests | Description |
|------|-------|-------------|
| `AddNotificationModal.test.js` | 36 | Notification service picker, URL building, test and save |
| `AlertBanner.test.js` | 11 | Alert display, dismiss, auto-hide |
| `DetectionInfoModal.test.js` | 25 | Detection details display, audio playback, actions |
| `LoginModal.test.js` | 22 | Login forms, setup flows, password validation, error handling |
| `SetupWizard.test.js` | 17 | Location and audio source setup flow |
| `SpeciesFilterModal.test.js` | 3 | Species filter selection |
| `UpdateManager.test.js` | 5 | Version display, update detection, update application |

### Composable Tests (`composables/`)
Tests for Vue composition functions (reusable logic).

| File | Tests | Description |
|------|-------|-------------|
| `useAudioPlayer.test.js` | 23 | Audio playback, controls, state management |
| `useAuth.test.js` | 35 | Authentication state, login/logout/setup flows, error handling |
| `useBirdCharts.test.js` | 24 | Chart creation, data transformation, Chart.js integration |
| `useChartColors.test.js` | 8 | Color palette structure and values |
| `useChartHelpers.test.js` | 23 | Hour labels, row stats, matrix data, date formatting |
| `useDateNavigation.test.js` | 39 | View switching, date navigation, boundary checks |
| `useFetchBirdData.test.js` | 27 | API calls, error handling, reactive updates |
| `useLogger.test.js` | 18 | Log levels, API logging, performance timing |
| `useServiceRestart.test.js` | 7 | Polling behavior, auto-reload, state management |
| `useSmartCrop.test.js` | 16 | Smart image cropping logic |
| `useSystemUpdate.test.js` | 19 | Version loading, update checks, update triggers |
| `useTableData.test.js` | 31 | Table sorting, filtering, pagination |

### Router Tests (`router/`)
Tests for Vue Router configuration.

| File | Tests | Description |
|------|-------|-------------|
| `router.test.js` | 24 | Route definitions, path resolution, parameters, lazy loading |

### View Tests (`views/`)
Tests for page-level Vue components.

| File | Tests | Description |
|------|-------|-------------|
| `BirdDetails.test.js` | 15 | Bird info display, recordings, chart rendering |
| `BirdDetectionList.test.js` | 3 | Detection rendering, highlight styling, navigation |
| `BirdGallery.test.js` | 8 | Tab switching, image loading, empty states |
| `Charts.test.js` | 14 | Date selection, data fetching, navigation |
| `Dashboard.test.js` | 21 | Empty states, data formatting, error display |
| `Detections.test.js` | 1 | Placeholder content |
| `LiveFeed.test.js` | 15 | Stream config, audio controls, WebSocket listeners |
| `Settings.test.js` | 58 | Settings loading, input validation, saving |
| `Spectrogram.test.js` | 2 | Audio fetching, spectrogram generation |
| `Table.test.js` | 17 | Detection table rendering, sorting, actions |

## Testing Patterns

### Mocking Dependencies

Tests mock external dependencies to isolate component behavior:

```javascript
// Mock API service
const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn()
}))

vi.mock('@/services/api', () => ({
  default: mockApi
}))

// Mock composables
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({
    authStatus: ref({ authEnabled: false }),
    login: vi.fn().mockResolvedValue(true),
    // ...
  })
}))
```

### Mounting Components

Use `@vue/test-utils` for component mounting:

```javascript
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'

const mountComponent = () => mount(MyComponent, {
  global: {
    stubs: {
      'router-link': RouterLinkStub,
      'font-awesome-icon': true  // Stub icon components
    }
  },
  props: {
    // Component props
  }
})

it('renders correctly', async () => {
  const wrapper = mountComponent()
  await flushPromises()  // Wait for async operations

  expect(wrapper.text()).toContain('Expected text')
})
```

### Testing Composables

Test composables directly without mounting components:

```javascript
import { useAuth } from '@/composables/useAuth'

it('returns expected properties', () => {
  const auth = useAuth()

  expect(auth).toHaveProperty('authStatus')
  expect(auth).toHaveProperty('login')
  expect(typeof auth.login).toBe('function')
})

it('handles login success', async () => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ success: true })
  })

  const auth = useAuth()
  const result = await auth.login('password')

  expect(result).toBe(true)
})
```

### Mocking Chart.js

Chart.js is commonly mocked to avoid canvas operations:

```javascript
vi.mock('chart.js/auto', () => {
  const ChartMock = function () {
    return { destroy: vi.fn(), update: vi.fn() }
  }
  ChartMock.register = vi.fn()
  ChartMock.getChart = vi.fn()
  return { default: ChartMock }
})
```

### Fake Timers

Use Vitest's fake timers for time-dependent tests:

```javascript
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2024, 5, 15))
})

afterEach(() => {
  vi.useRealTimers()
})

it('auto-clears message after timeout', async () => {
  // trigger action
  await vi.advanceTimersByTimeAsync(10000)
  expect(message.value).toBe('')
})
```

## Writing New Tests

### Naming Convention

- Test files: `*.test.js` (matches Vitest config)
- Place in appropriate subdirectory:
  - Components → `tests/components/`
  - Composables → `tests/composables/`
  - Views → `tests/views/`
  - Router → `tests/router/`

### Test Structure

```javascript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mocks defined at top level
vi.mock(...)

describe('ComponentName', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Setup
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('feature group', () => {
    it('does expected behavior', async () => {
      // Arrange
      // Act
      // Assert
    })
  })
})
```

### Best Practices

1. **Mock external dependencies** - API calls, composables, router
2. **Test behavior, not implementation** - Focus on what users experience
3. **Use descriptive test names** - Clearly describe the expected behavior
4. **Isolate tests** - Each test should be independent
5. **Clean up after tests** - Use `afterEach` to restore mocks

## Coverage Reports

When running with coverage (`npm run test:coverage`):

- **Terminal**: Summary displayed in console
- **HTML**: Detailed report in `coverage/index.html`

Coverage targets `src/**/*.{js,vue}` excluding `src/main.js`.

## Test Counts Summary

| Category | Files | Tests |
|----------|-------|-------|
| App | 1 | 2 |
| Components | 7 | 119 |
| Composables | 12 | 270 |
| Router | 1 | 24 |
| Views | 10 | 154 |
| **Total** | **31** | **569** |

## Common Issues

### Canvas/Chart.js errors
Mock Chart.js to avoid DOM canvas operations in happy-dom:
```javascript
vi.mock('chart.js/auto', () => ({ default: vi.fn() }))
```

### Async operations not completing
Use `flushPromises()` to wait for all pending promises:
```javascript
await flushPromises()
```

### Router-link errors
Stub `router-link` to avoid navigation errors:
```javascript
import { RouterLinkStub } from '@vue/test-utils'
// in mount options:
stubs: { 'router-link': RouterLinkStub }
```

### Global fetch not defined
Mock `fetch` in beforeEach:
```javascript
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: () => Promise.resolve(data)
})
```

## Dependencies

Test dependencies (in `devDependencies`):

| Package | Purpose |
|---------|---------|
| `vitest` | Test runner |
| `@vue/test-utils` | Vue component testing |
| `@vitest/coverage-v8` | Code coverage |
| `happy-dom` | DOM simulation (faster than jsdom) |
