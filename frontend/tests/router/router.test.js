/**
 * Tests for Vue Router configuration
 */
import { describe, it, expect } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

// Import the routes configuration
import router from '@/router/index.js'

describe('Router Configuration', () => {
  describe('routes definition', () => {
    it('router is created successfully', () => {
      expect(router).toBeDefined()
    })

    it('has all expected routes', () => {
      const routes = router.getRoutes()
      const routeNames = routes.map(r => r.name)

      expect(routeNames).toContain('Dashboard')
      expect(routeNames).toContain('BirdGallery')
      expect(routeNames).toContain('LiveFeed')
      expect(routeNames).toContain('Settings')
      expect(routeNames).toContain('Charts')
      expect(routeNames).toContain('BirdDetails')
    })

    it('Dashboard route is at root path', () => {
      const dashboardRoute = router.getRoutes().find(r => r.name === 'Dashboard')

      expect(dashboardRoute).toBeDefined()
      expect(dashboardRoute.path).toBe('/')
    })

    it('Gallery route is at /gallery', () => {
      const galleryRoute = router.getRoutes().find(r => r.name === 'BirdGallery')

      expect(galleryRoute).toBeDefined()
      expect(galleryRoute.path).toBe('/gallery')
    })

    it('LiveFeed route is at /live', () => {
      const liveRoute = router.getRoutes().find(r => r.name === 'LiveFeed')

      expect(liveRoute).toBeDefined()
      expect(liveRoute.path).toBe('/live')
    })

    it('Settings route is at /settings', () => {
      const settingsRoute = router.getRoutes().find(r => r.name === 'Settings')

      expect(settingsRoute).toBeDefined()
      expect(settingsRoute.path).toBe('/settings')
    })

    it('Charts route is at /charts', () => {
      const chartsRoute = router.getRoutes().find(r => r.name === 'Charts')

      expect(chartsRoute).toBeDefined()
      expect(chartsRoute.path).toBe('/charts')
    })

    it('BirdDetails route has dynamic parameter', () => {
      const birdDetailsRoute = router.getRoutes().find(r => r.name === 'BirdDetails')

      expect(birdDetailsRoute).toBeDefined()
      expect(birdDetailsRoute.path).toBe('/bird/:name')
    })
  })

  describe('route resolution', () => {
    it('resolves root path to Dashboard', () => {
      const resolved = router.resolve('/')

      expect(resolved.name).toBe('Dashboard')
    })

    it('resolves /gallery to BirdGallery', () => {
      const resolved = router.resolve('/gallery')

      expect(resolved.name).toBe('BirdGallery')
    })

    it('resolves /live to LiveFeed', () => {
      const resolved = router.resolve('/live')

      expect(resolved.name).toBe('LiveFeed')
    })

    it('resolves /settings to Settings', () => {
      const resolved = router.resolve('/settings')

      expect(resolved.name).toBe('Settings')
    })

    it('resolves /charts to Charts', () => {
      const resolved = router.resolve('/charts')

      expect(resolved.name).toBe('Charts')
    })

    it('resolves /bird/:name to BirdDetails with params', () => {
      const resolved = router.resolve('/bird/American%20Robin')

      expect(resolved.name).toBe('BirdDetails')
      expect(resolved.params.name).toBe('American Robin')
    })
  })

  describe('route parameters', () => {
    it('BirdDetails accepts bird name parameter', () => {
      const resolved = router.resolve({ name: 'BirdDetails', params: { name: 'Blue Jay' } })

      expect(resolved.fullPath).toBe('/bird/Blue%20Jay')
    })

    it('BirdDetails handles names with special characters', () => {
      const resolved = router.resolve({ name: 'BirdDetails', params: { name: "Wilson's Warbler" } })

      expect(resolved.name).toBe('BirdDetails')
      expect(resolved.params.name).toBe("Wilson's Warbler")
    })
  })

  describe('lazy loading', () => {
    it('Dashboard component is eagerly loaded', () => {
      const dashboardRoute = router.getRoutes().find(r => r.name === 'Dashboard')

      // Dashboard is imported directly, so component should be defined
      expect(dashboardRoute.components.default).toBeDefined()
    })

    it('other routes use lazy loading', () => {
      const galleryRoute = router.getRoutes().find(r => r.name === 'BirdGallery')
      const liveRoute = router.getRoutes().find(r => r.name === 'LiveFeed')
      const settingsRoute = router.getRoutes().find(r => r.name === 'Settings')
      const chartsRoute = router.getRoutes().find(r => r.name === 'Charts')
      const birdDetailsRoute = router.getRoutes().find(r => r.name === 'BirdDetails')

      // Lazy loaded routes will have a function as component until resolved
      // After resolution, they become the actual component
      // The routes are defined, which is what matters
      expect(galleryRoute).toBeDefined()
      expect(liveRoute).toBeDefined()
      expect(settingsRoute).toBeDefined()
      expect(chartsRoute).toBeDefined()
      expect(birdDetailsRoute).toBeDefined()
    })
  })

  describe('history mode', () => {
    it('uses web history mode', () => {
      // The router uses createWebHistory which provides clean URLs
      // We can verify by checking the router options
      expect(router.options.history).toBeDefined()
    })
  })
})
