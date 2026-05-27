import { createRouter, createWebHashHistory } from 'vue-router'
import { Login } from '@/store/login'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/login'
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/login/index.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/pages/login/index.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/app',
      component: () => import('@/pages/layout/AuthLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'documents',
          component: () => import('@/pages/documents/index.vue')
        },
        {
          path: 'upload',
          name: 'upload',
          component: () => import('@/pages/upload/index.vue')
        },
        {
          path: 'chat',
          name: 'document-chat',
          component: () => import('@/pages/chat/index.vue')
        },
        {
          path: 'dashboard',
          name: 'smart-dashboard',
          component: () => import('@/pages/dashboard/SmartDashboard.vue')
        },
        {
          // Project-centric dashboard route (Insight Board)
          path: 'dashboard/:projectId',
          name: 'smart-dashboard-project',
          component: () => import('@/pages/dashboard/SmartDashboard.vue')
        },
        {
          // Board-centric dashboard route (standalone Insight Board)
          path: 'board/:boardId',
          name: 'insight-board',
          component: () => import('@/pages/dashboard/SmartDashboard.vue')
        },
        {
          path: 'etl',
          name: 'etl-pipeline',
          component: () => import('@/pages/etl/index.vue')
        },
        {
          path: 'workspaces',
          name: 'workspaces',
          component: () => import('@/pages/workspaces/index.vue')
        },
        {
          path: 'workspaces/:workspaceId',
          name: 'workspace-catalog',
          component: () => import('@/pages/workspaces/catalog/index.vue')
        },
        {
          path: 'workspaces/:workspaceId/chat',
          name: 'workspace-chat',
          component: () => import('@/pages/workspaces/chat/index.vue')
        },
        {
          path: 'workspaces/:workspaceId/dashboard',
          name: 'workspace-dashboard',
          component: () => import('@/pages/workspaces/dashboard/index.vue')
        },
        {
          path: 'workspaces/:workspaceId/report',
          name: 'workspace-report',
          component: () => import('@/pages/workspaces/report/index.vue')
        }
      ]
    },
    {
      path: '/:catchAll(.*)*',
      name: 'NotFound',
      component: () => import('@/pages/catchAll.vue')
    },
    {
      path: '/share/:token',
      name: 'shared-dashboard',
      component: () => import('@/pages/dashboard/SmartDashboard.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/shared/workspace/:token',
      name: 'shared-workspace-dashboard',
      component: () => import('@/pages/workspaces/shared/SharedWorkspaceDashboard.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/shared/workspace/:token/chat',
      name: 'shared-workspace-chat',
      component: () => import('@/pages/workspaces/shared/SharedWorkspaceChat.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/shared/workspace/:token/report',
      name: 'shared-workspace-report',
      component: () => import('@/pages/workspaces/shared/SharedWorkspaceReport.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/shared/report/:token',
      name: 'shared-report-view',
      component: () => import('@/pages/workspaces/shared/SharedReportView.vue'),
      meta: { requiresAuth: false }
    }
  ]
})

// Navigation guard for protected routes
router.beforeEach((to, from, next) => {
  const loginStore = Login()
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const isAuthenticated = loginStore.isAuthenticated

  if (to.path === '/') {
    next('/login')
  } else if (requiresAuth && !isAuthenticated) {
    next('/login')
  } else {
    next()
  }
})

export default router
