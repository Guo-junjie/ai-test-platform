import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘' },
  },
  {
    path: '/test-run',
    name: 'TestRun',
    component: () => import('@/views/TestRun.vue'),
    meta: { title: '测试运行' },
  },
  {
    path: '/report/:id',
    name: 'Report',
    component: () => import('@/views/Report.vue'),
    meta: { title: '测试报告' },
  },
  {
    path: '/sources',
    name: 'SourceManage',
    component: () => import('@/views/SourceManage.vue'),
    meta: { title: '数据源管理' },
  },
  {
    path: '/analysis',
    name: 'Analysis',
    component: () => import('@/views/Analysis.vue'),
    meta: { title: '代码解析' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: '系统配置', requireAdmin: true },
  },
  {
    path: '/settings/models',
    name: 'ModelConfig',
    component: () => import('@/views/ModelConfig.vue'),
    meta: { title: 'AI模型配置', requireAdmin: true },
  },
  {
    path: '/settings/quality-gate',
    name: 'QualityGate',
    component: () => import('@/views/QualityGate.vue'),
    meta: { title: '质量门禁' },
  },
  {
    path: '/settings/audit',
    name: 'AuditLog',
    component: () => import('@/views/AuditLog.vue'),
    meta: { title: '审计日志' },
  },
  {
    path: '/quality-trend',
    name: 'QualityTrend',
    component: () => import('@/views/QualityTrend.vue'),
    meta: { title: '质量趋势' },
  },
  {
    path: '/user-management',
    name: 'UserManagement',
    component: () => import('@/views/UserManagement.vue'),
    meta: { title: '用户管理', requireAdmin: true },
  },
  {
    path: '/approvals',
    name: 'Approvals',
    component: () => import('@/views/Approvals.vue'),
    meta: { title: '审核中心', requireAuditor: true },
  },
  {
    path: '/notifications',
    name: 'Notifications',
    component: () => import('@/views/Notifications.vue'),
    meta: { title: '消息通知' },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/Profile.vue'),
    meta: { title: '个人设置' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} - AI自动化测试平台`
  }

  const authStore = useAuthStore()

  // 公开路由（如登录页）直接放行
  if (to.meta?.public) {
    // 已登录用户访问登录页，重定向到仪表盘
    if (authStore.isAuthenticated && to.name === 'Login') {
      next({ path: '/dashboard' })
      return
    }
    next()
    return
  }

  // 需要认证的路由
  if (!authStore.isAuthenticated) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 需要管理员权限的路由（isAdmin 已包含 super_admin）
  if (to.meta?.requireAdmin && !authStore.isAdmin) {
    next({ path: '/dashboard' })
    return
  }

  // 需要审核权限的路由：审核员或超级管理员可访问
  if (to.meta?.requireAuditor && !(authStore.isAuditor || authStore.isSuperAdmin)) {
    next({ path: '/dashboard' })
    return
  }

  next()
})

export default router
