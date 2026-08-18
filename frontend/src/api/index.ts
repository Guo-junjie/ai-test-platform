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
  /** 管理员新建用户（可能进入审核流，返回 data.status === 'pending'） */
  register: (data: any) => api.post('/auth/users', data),
  me: () => api.get('/auth/me'),
  listUsers: (params?: any) => api.get('/auth/users', { params }),
  updateRole: (userId: string, role: string) => api.put(`/auth/users/${userId}/role`, { role }),
  /** 删除用户（可能进入审核流，返回 data.status === 'pending'） */
  deleteUser: (userId: string) => api.delete(`/auth/users/${userId}`),
  updateStatus: (userId: string, isActive: boolean) =>
    api.put(`/auth/users/${userId}/status`, { is_active: isActive }),
  /** 更新当前登录用户的个人信息（邮箱 / 用户名） */
  updateProfile: (data: { email?: string; username?: string }) => api.put('/auth/me', data),
  /** 修改当前登录用户密码 */
  changePassword: (data: { old_password: string; new_password: string }) =>
    api.put('/auth/me/password', data),
  logout: () => api.post('/auth/logout'),
}

// ============ 变更审核（审核中心） ============
export const changeRequestApi = {
  /** 变更申请列表，常用 params: { status: 'pending' } */
  list: (params?: any) => api.get('/change-requests', { params }),
  /** 审核通过 */
  approve: (id: string) => api.post(`/change-requests/${id}/approve`),
  /** 审核驳回，data: { note: '驳回理由' } */
  reject: (id: string, data: { note: string }) => api.post(`/change-requests/${id}/reject`, data),
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

// ============ 接口文档资产（能力1：解析导入 / 能力2：评审） ============
export const docApi = {
  upload: (file: File, projectId: string, docType?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('project_id', projectId)
    if (docType) fd.append('doc_type', docType)
    return api.post('/docs/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  parse: (docId: string, data?: any) =>
    api.post(`/docs/${docId}/parse`, data ?? {}, { timeout: 300000 }),
  list: (params: any) => api.get('/docs', { params }),
  get: (docId: string) => api.get(`/docs/${docId}`),
  remove: (docId: string) => api.delete(`/docs/${docId}`),
  import: (docId: string, data: any) =>
    api.post(`/docs/${docId}/import`, data, { timeout: 120000 }),
  listEndpoints: (params: any) => api.get('/docs/endpoints', { params }),
  getEndpoint: (id: string) => api.get(`/docs/endpoints/${id}`),
  review: (data: any) => api.post('/docs/reviews', data, { timeout: 300000 }),
  listReviews: (params: any) => api.get('/docs/reviews', { params }),
  getReview: (reviewId: string) => api.get(`/docs/reviews/${reviewId}`),
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

// ============ 用例库（能力3：AI 生成单接口用例·接纳闭环） ============
export const caseApi = {
  /** 生成并落库（DRAFT）。data: { project_id, endpoint_ids?, endpoint_id? } */
  generate: (data: any) =>
    api.post('/cases/generate', data, { timeout: 300000 }),
  /** 列表：params { project_id, endpoint_id?, case_type?, status?, keyword?, page, page_size } */
  list: (params: any) => api.get('/cases', { params }),
  /** 详情 */
  get: (id: string) => api.get(`/cases/${id}`),
  /** 编辑（标题/描述/请求/预期/优先级/类型） */
  update: (id: string, data: any) => api.put(`/cases/${id}`, data),
  /** 删除 */
  remove: (id: string) => api.delete(`/cases/${id}`),
  /** 单条接纳 */
  adopt: (id: string) => api.post(`/cases/${id}/adopt`),
  /** 单条废弃 */
  deprecate: (id: string) => api.post(`/cases/${id}/deprecate`),
  /** 批量接纳：data { ids: string[] } */
  adoptBatch: (ids: string[]) => api.post('/cases/adopt-batch', { ids }),
}

// ============ 场景编排（能力4：AI 编排测试场景） ============
export const scenarioApi = {
  /** 创建并 AI 编排：data { project_id, nl_input, name?, endpoint_ids? } */
  create: (data: any) =>
    api.post('/scenarios', data, { timeout: 300000 }),
  /** 列表：params { project_id, status?, keyword?, page, page_size } */
  list: (params: any) => api.get('/scenarios', { params }),
  /** 详情（含 steps） */
  get: (id: string) => api.get(`/scenarios/${id}`),
  /** 编辑步骤/名称：data { name?, description?, nl_input?, steps? } */
  update: (id: string, data: any) => api.put(`/scenarios/${id}`, data),
  /** 接纳 */
  adopt: (id: string) => api.post(`/scenarios/${id}/adopt`),
  /** 预览（不落库、不接真实 HTTP）：data { project_id, nl_input, endpoint_ids? } */
  dryRun: (data: any) =>
    api.post('/scenarios/dry-run', data, { timeout: 300000 }),
}

export default api
