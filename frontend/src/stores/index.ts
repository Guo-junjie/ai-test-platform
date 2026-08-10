/**
 * Pinia Store — 全局状态管理
 *
 * 提供：
 * - useAppStore: 应用全局状态（环境信息、侧边栏折叠等）
 * - useAuthStore: 用户认证状态（登录/登出/用户信息/token）
 * - 统一响应类型定义
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { authApi } from '@/api'
import { ROLE_LABELS } from '@/utils/roles'

// ==================== 统一响应类型 ====================

/** 后端统一 API 响应格式 */
export interface ApiResponse<T = any> {
  code: number
  data: T
  message: string
}

/** 分页响应数据 */
export interface PageResult<T = any> {
  list: T[]
  total: number
  page: number
  pageSize: number
}

/** 系统角色枚举值（与后端 UserRole 一致，全部小写） */
export type UserRole =
  | 'super_admin'
  | 'admin'
  | 'test_manager'
  | 'tester'
  | 'developer'
  | 'auditor'
  | 'viewer'

/** 用户信息 */
export interface UserInfo {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string | null
}

/**
 * 角色 -> 中文标签（统一取自 @/utils/roles 的 ROLE_LABELS）
 * @param role 角色枚举值
 */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] || role || '未知角色'
}

// ==================== App Store ====================

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref<boolean>(false)
  const globalLoading = ref<boolean>(false)
  const backendHealthy = ref<boolean>(true)
  const environment = ref<string>('development')
  const appVersion = ref<string>('1.0.0')

  const sidebarWidth = computed<string>(() => {
    return sidebarCollapsed.value ? '64px' : '220px'
  })

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setSidebarCollapsed(collapsed: boolean): void {
    sidebarCollapsed.value = collapsed
  }

  function setGlobalLoading(loading: boolean): void {
    globalLoading.value = loading
  }

  async function checkHealth(): Promise<boolean> {
    try {
      const response = await axios.get<ApiResponse<{ status: string; env: string }>>(
        '/api/health'
      )
      if (response.data?.code === 0 || response.data?.data?.status === 'healthy') {
        backendHealthy.value = true
        environment.value = response.data.data.env || 'development'
        return true
      }
      backendHealthy.value = false
      return false
    } catch {
      backendHealthy.value = false
      return false
    }
  }

  return {
    sidebarCollapsed,
    globalLoading,
    backendHealthy,
    environment,
    appVersion,
    sidebarWidth,
    toggleSidebar,
    setSidebarCollapsed,
    setGlobalLoading,
    checkHealth,
  }
})

// ==================== Auth Store ====================

export const useAuthStore = defineStore('auth', () => {
  // ==================== State ====================

  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<UserInfo | null>(
    (() => {
      const stored = localStorage.getItem('user')
      try {
        return stored ? JSON.parse(stored) as UserInfo : null
      } catch {
        return null
      }
    })()
  )

  // ==================== Getters ====================

  const isAuthenticated = computed<boolean>(() => !!token.value)
  const username = computed<string>(() => user.value?.username || '未登录')
  const role = computed<string>(() => user.value?.role || 'viewer')
  /** 超级管理员 */
  const isSuperAdmin = computed<boolean>(() => user.value?.role === 'super_admin')
  /** 管理员（含超级管理员） */
  const isAdmin = computed<boolean>(
    () => user.value?.role === 'admin' || user.value?.role === 'super_admin'
  )
  /** 审核员 */
  const isAuditor = computed<boolean>(() => user.value?.role === 'auditor')
  /** 当前用户角色中文名 */
  const roleName = computed<string>(() => roleLabel(role.value))

  // ==================== Actions ====================

  async function login(username: string, password: string): Promise<boolean> {
    try {
      const res: any = await authApi.login({ username, password })
      if (res.code === 0 && res.data?.token) {
        token.value = res.data.token
        user.value = res.data.user
        localStorage.setItem('token', res.data.token)
        localStorage.setItem('user', JSON.stringify(res.data.user))
        return true
      }
      return false
    } catch {
      return false
    }
  }

  function logout(): void {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  async function fetchCurrentUser(): Promise<void> {
    if (!token.value) return
    try {
      const res: any = await authApi.me()
      if (res.code === 0 && res.data) {
        user.value = res.data
        localStorage.setItem('user', JSON.stringify(res.data))
      }
    } catch {
      logout()
    }
  }

  return {
    token,
    user,
    isAuthenticated,
    username,
    role,
    roleName,
    isSuperAdmin,
    isAdmin,
    isAuditor,
    login,
    logout,
    fetchCurrentUser,
  }
})

// ==================== 导出 ====================

export default {
  useAppStore,
  useAuthStore,
}
