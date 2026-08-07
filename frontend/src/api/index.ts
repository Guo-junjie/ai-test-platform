import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

// ============ 数据源 ============
export const sourceApi = {
  list: () => api.get('/source/configs'),
  connect: (data: any) => api.post('/source/connect', data),
  disconnect: (id: string) => api.delete(`/source/${id}`),
  fetch: (data: any) => api.post('/source/fetch', data),
}

// ============ 文件上传 ============
export const uploadApi = {
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
}

// ============ 测试任务 ============
export const testRunApi = {
  list: () => api.get('/test-runs/'),
  create: (data: any) => api.post('/test-runs/', data),
  get: (id: string) => api.get(`/test-runs/${id}`),
  getProgress: (id: string) => api.get(`/test-runs/${id}/progress`),
  cancel: (id: string) => api.post(`/test-runs/${id}/cancel`),
}

// ============ 报告 ============
export const reportApi = {
  getList: (params?: any) => api.get('/reports/history', { params }),
  get: (runId: string) => api.get(`/reports/${runId}`),
  getHtml: (runId: string) => api.get(`/reports/${runId}/html`, { timeout: 60000 }),
  getPdfUrl: (runId: string) => `/api/reports/${runId}/pdf`,
  getPdf: (runId: string) => api.get(`/reports/${runId}/pdf`, { responseType: 'blob' }),
  share: (runId: string) => api.get(`/reports/${runId}/share`),
  generate: (runId: string) => api.post(`/reports/${runId}/generate`, {}, { timeout: 300000 }),
}

// ============ AI 模型配置 ============
export const modelApi = {
  listConfigs: () => api.get('/models/configs'),
  createConfig: (data: any) => api.post('/models/configs', data),
  updateConfig: (id: string, data: any) => api.put(`/models/configs/${id}`, data),
  deleteConfig: (id: string) => api.delete(`/models/configs/${id}`),
  testConnection: (id: string) => api.post(`/models/configs/${id}/test`),
  getRouting: () => api.get('/models/routing'),
  updateRouting: (data: any) => api.put('/models/routing', data),
}

// ============ 认证 ============
export const authApi = {
  login: (data: { username: string; password: string }) => api.post('/auth/login', data),
  register: (data: any) => api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
  listUsers: (params?: any) => api.get('/auth/users', { params }),
  updateRole: (userId: string, role: string) => api.put(`/auth/users/${userId}/role`, { role }),
  updateStatus: (userId: string, isActive: boolean) =>
    api.put(`/auth/users/${userId}/status`, { is_active: isActive }),
  /** 更新当前登录用户的个人信息（邮箱 / 用户名） */
  updateProfile: (data: { email?: string; username?: string }) => api.put('/auth/me', data),
  /** 修改当前登录用户密码 */
  changePassword: (data: { old_password: string; new_password: string }) =>
    api.put('/auth/me/password', data),
  logout: () => api.post('/auth/logout'),
}

// ============ 项目 ============
export const projectApi = {
  /** 获取项目列表，返回 [{ id, name }]（id 为后端真实 UUID） */
  getList: (params?: any) => api.get('/projects', { params }),
}

// ============ 消息通知 ============
export const notificationApi = {
  list: (params?: any) => api.get('/notifications', { params }),
  markRead: (id: string) => api.post(`/notifications/${id}/read`),
  markAllRead: () => api.post('/notifications/read-all'),
  remove: (id: string) => api.delete(`/notifications/${id}`),
}

// ============ 仪表盘与趋势 ============
export const dashboardApi = {
  getStatistics: (days?: number) => api.get('/dashboard/statistics', { params: { days } }),
  getQualityTrend: (timeRange?: string) => api.get('/dashboard/quality-trend', { params: { time_range: timeRange } }),
  getTestTrend: (timeRange?: string) => api.get('/dashboard/test-trend', { params: { time_range: timeRange } }),
  getDefectTrend: (timeRange?: string) => api.get('/dashboard/defect-trend', { params: { time_range: timeRange } }),
  getRecentRuns: (limit?: number) => api.get('/dashboard/recent-runs', { params: { limit } }),
}

// ============ 系统配置 ============
export const systemApi = {
  health: () => api.get('/health'),
  getSettings: () => api.get('/settings/'),
  updateSettings: (data: any) => api.put('/settings/', data),
  getQualityGateConfig: () => api.get('/settings/quality-gate'),
  updateQualityGateConfig: (data: any) => api.put('/settings/quality-gate', data),
  testQualityGate: (data: any) => api.post('/settings/quality-gate/test', data),
  getNotificationConfig: () => api.get('/settings/notification'),
  updateNotificationConfig: (data: any) => api.put('/settings/notification', data),
}

// ============ 审计日志 ============
export const auditApi = {
  list: (params?: any) => api.get('/audit/', { params }),
  getStatistics: (days?: number) => api.get('/audit/statistics', { params: { days } }),
}

// ============ 代码解析 ============
export const analysisApi = {
  run: (data: { local_path: string; test_run_id?: string }) =>
    api.post('/analysis/run', data, { timeout: 300000 }),
  get: (id: string) => api.get(`/analysis/${id}`),
}

// ============ 质量门禁 ============
export const qualityGateApi = {
  getConfig: (projectId: string) => api.get(`/quality-gate/config/${projectId}`),
  updateConfig: (projectId: string, data: any) => api.put(`/quality-gate/config/${projectId}`, data),
  evaluate: (runId: string) => api.post(`/quality-gate/evaluate/${runId}`, {}, { timeout: 60000 }),
  getHistory: (projectId: string, params?: any) => api.get(`/quality-gate/history/${projectId}`, { params }),
}

// ============ 质量趋势 ============
export const trendApi = {
  getQuality: (params?: any) => api.get('/trend/quality', { params }),
  getPassRate: (params?: any) => api.get('/trend/pass-rate', { params }),
  getDefect: (params?: any) => api.get('/trend/defect', { params }),
  getSummary: (params?: any) => api.get('/trend/summary', { params }),
}

export default api
