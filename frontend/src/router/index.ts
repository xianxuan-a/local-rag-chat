import { createRouter, createWebHistory } from 'vue-router'

import { apiConfig } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    adminOnly?: boolean
  }
}

export function safeInternalRedirect(value: unknown, fallback = '/dashboard'): string {
  if (typeof value !== 'string' || !value.startsWith('/')) {
    return fallback
  }
  if (
    value.includes('\\') ||
    [...value].some((character) => character.charCodeAt(0) < 32)
  ) {
    return fallback
  }
  try {
    const base = new URL('https://nexus-rag.local')
    const parsed = new URL(value, base)
    if (parsed.origin !== base.origin || parsed.pathname === '/login') return fallback
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return fallback
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/dashboard',
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
        },
        {
          path: 'knowledge-bases',
          name: 'knowledge-bases',
          component: () => import('@/views/KnowledgeBasesView.vue'),
        },
        {
          path: 'files',
          name: 'files',
          component: () => import('@/views/FilesView.vue'),
        },
        {
          path: 'sessions',
          name: 'sessions',
          component: () => import('@/views/SessionsView.vue'),
        },
        {
          path: 'retrieval',
          name: 'retrieval',
          component: () => import('@/views/RetrievalView.vue'),
        },
        {
          path: 'indexes',
          name: 'indexes',
          component: () => import('@/views/IndexesView.vue'),
        },
        {
          path: 'evaluation',
          name: 'evaluation',
          component: () => import('@/views/EvaluationView.vue'),
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/views/UsersView.vue'),
          meta: { adminOnly: true },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  if (apiConfig.mode === 'mock') return true

  const authStore = useAuthStore()
  try {
    await authStore.initialize()
  } catch {
    // A stored, unexpired token remains usable while /me is temporarily unreachable.
  }

  if (to.name === 'login') {
    return authStore.isAuthenticated ? safeInternalRedirect(to.query.redirect) : true
  }

  if (
    to.matched.some((record) => record.meta.requiresAuth) &&
    !authStore.isAuthenticated
  ) {
    return {
      path: '/login',
      query: { redirect: safeInternalRedirect(to.fullPath) },
      replace: true,
    }
  }

  if (to.matched.some((record) => record.meta.adminOnly) && !authStore.isAdmin) {
    return { path: '/dashboard', query: { permission: 'denied' }, replace: true }
  }

  return true
})

router.afterEach((to) => {
  const routeTitle =
    typeof to.name === 'string'
      ? to.name
          .split('-')
          .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
          .join(' ')
      : 'Nexus RAG'
  document.title = `${routeTitle} · Nexus RAG`
})

export default router
