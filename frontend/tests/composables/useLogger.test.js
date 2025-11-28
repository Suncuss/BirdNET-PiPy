/**
 * Tests for useLogger composable
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useLogger } from '@/composables/useLogger'

describe('useLogger', () => {
  let consoleSpy

  beforeEach(() => {
    // Mock console methods
    consoleSpy = {
      log: vi.spyOn(console, 'log').mockImplementation(() => {}),
      warn: vi.spyOn(console, 'warn').mockImplementation(() => {}),
      error: vi.spyOn(console, 'error').mockImplementation(() => {}),
      time: vi.spyOn(console, 'time').mockImplementation(() => {}),
      timeEnd: vi.spyOn(console, 'timeEnd').mockImplementation(() => {}),
      group: vi.spyOn(console, 'group').mockImplementation(() => {}),
      groupEnd: vi.spyOn(console, 'groupEnd').mockImplementation(() => {})
    }
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('initialization', () => {
    it('returns logger object with all expected methods', () => {
      const logger = useLogger('TestComponent')

      expect(logger).toHaveProperty('debug')
      expect(logger).toHaveProperty('info')
      expect(logger).toHaveProperty('warn')
      expect(logger).toHaveProperty('error')
      expect(logger).toHaveProperty('api')
      expect(logger).toHaveProperty('time')
      expect(logger).toHaveProperty('timeEnd')
      expect(logger).toHaveProperty('group')
      expect(logger).toHaveProperty('groupEnd')
    })

    it('all methods are functions', () => {
      const logger = useLogger('TestComponent')

      expect(typeof logger.debug).toBe('function')
      expect(typeof logger.info).toBe('function')
      expect(typeof logger.warn).toBe('function')
      expect(typeof logger.error).toBe('function')
      expect(typeof logger.api).toBe('function')
      expect(typeof logger.time).toBe('function')
      expect(typeof logger.timeEnd).toBe('function')
      expect(typeof logger.group).toBe('function')
      expect(typeof logger.groupEnd).toBe('function')
    })
  })

  describe('log level methods', () => {
    it('debug method calls console.log', () => {
      const logger = useLogger('TestComponent')
      logger.debug('test message')

      // In dev mode, debug should be called
      expect(consoleSpy.log).toHaveBeenCalled()
    })

    it('info method calls console.log', () => {
      const logger = useLogger('TestComponent')
      logger.info('test info message')

      expect(consoleSpy.log).toHaveBeenCalled()
    })

    it('warn method calls console.warn', () => {
      const logger = useLogger('TestComponent')
      logger.warn('test warning')

      expect(consoleSpy.warn).toHaveBeenCalled()
    })

    it('error method calls console.error', () => {
      const logger = useLogger('TestComponent')
      logger.error('test error')

      expect(consoleSpy.error).toHaveBeenCalled()
    })

    it('includes component name in log output', () => {
      const logger = useLogger('MyCustomComponent')
      logger.info('test message')

      // Check that the component name appears in the call
      const callArgs = consoleSpy.log.mock.calls[0]
      expect(callArgs[0]).toContain('MyCustomComponent')
    })

    it('supports additional arguments', () => {
      const logger = useLogger('TestComponent')
      const extraData = { key: 'value' }
      logger.info('test message', extraData)

      const callArgs = consoleSpy.log.mock.calls[0]
      expect(callArgs).toContain(extraData)
    })
  })

  describe('api method', () => {
    it('logs API calls with method and url', () => {
      const logger = useLogger('ApiComponent')
      logger.api('GET', '/api/test')

      expect(consoleSpy.log).toHaveBeenCalled()
      const callArgs = consoleSpy.log.mock.calls[0]
      expect(callArgs[0]).toContain('API GET')
    })

    it('logs API calls with response status', () => {
      const logger = useLogger('ApiComponent')
      const mockResponse = { status: 200, data: {} }
      logger.api('POST', '/api/test', { data: 'value' }, mockResponse)

      expect(consoleSpy.log).toHaveBeenCalled()
      const callArgs = consoleSpy.log.mock.calls[0]
      expect(callArgs.some(arg => typeof arg === 'string' && arg.includes('[200]'))).toBe(true)
    })

    it('handles pending response (no status)', () => {
      const logger = useLogger('ApiComponent')
      logger.api('GET', '/api/test', null, null)

      expect(consoleSpy.log).toHaveBeenCalled()
    })
  })

  describe('performance methods', () => {
    it('time method calls console.time', () => {
      const logger = useLogger('PerfComponent')
      logger.time('operation')

      expect(consoleSpy.time).toHaveBeenCalled()
    })

    it('timeEnd method calls console.timeEnd', () => {
      const logger = useLogger('PerfComponent')
      logger.timeEnd('operation')

      expect(consoleSpy.timeEnd).toHaveBeenCalled()
    })

    it('time includes component name in label', () => {
      const logger = useLogger('PerfComponent')
      logger.time('myOperation')

      const callArgs = consoleSpy.time.mock.calls[0]
      expect(callArgs[0]).toContain('PerfComponent')
      expect(callArgs[0]).toContain('myOperation')
    })
  })

  describe('grouping methods', () => {
    it('group method calls console.group', () => {
      const logger = useLogger('GroupComponent')
      logger.group('test group')

      expect(consoleSpy.group).toHaveBeenCalled()
    })

    it('groupEnd method calls console.groupEnd', () => {
      const logger = useLogger('GroupComponent')
      logger.groupEnd()

      expect(consoleSpy.groupEnd).toHaveBeenCalled()
    })

    it('group includes component name in label', () => {
      const logger = useLogger('GroupComponent')
      logger.group('myGroup')

      const callArgs = consoleSpy.group.mock.calls[0]
      expect(callArgs[0]).toContain('GroupComponent')
      expect(callArgs[0]).toContain('myGroup')
    })
  })

  describe('multiple loggers', () => {
    it('different components have independent loggers', () => {
      const logger1 = useLogger('Component1')
      const logger2 = useLogger('Component2')

      logger1.info('message from 1')
      logger2.info('message from 2')

      expect(consoleSpy.log).toHaveBeenCalledTimes(2)

      const call1 = consoleSpy.log.mock.calls[0]
      const call2 = consoleSpy.log.mock.calls[1]

      expect(call1[0]).toContain('Component1')
      expect(call2[0]).toContain('Component2')
    })
  })
})
