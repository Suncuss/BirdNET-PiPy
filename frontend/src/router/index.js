import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/gallery',
    name: 'BirdGallery',
    component: () => import('../views/BirdGallery.vue')
  },
  {
    path: '/live',
    name: 'LiveFeed',
    component: () => import('../views/LiveFeed.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue')
  },
  {
    path: '/charts',
    name: 'Charts',
    component: () => import('../views/Charts.vue')
  },
  { path: '/bird/:name', 
    name: 'BirdDetails', 
    component: () => import('../views/BirdDetails.vue') 

  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router