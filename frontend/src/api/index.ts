import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

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
    // 模型未配置：弹出引导，提示用户先去「AI 模型配置」页面添加并启用模型
    if (
      error.response?.status === 409 &&
      error.response?.data?.code === 'MODEL_NOT_CONFIGURED'
    ) {
      const detail =
        error.response?.data?.detail ||
        '尚未配置 AI 模型，请先在「AI 模型配置」页面添加并启用至少一个模型后再使用此功能。'
      // 读取当前用户角色，决定是引导去配置还是提示联系管理员
      let currentRole = ''
      try {
        const u = JSON.parse(localStorage.getItem('user') || '{}')
        currentRole = u.role || ''
      } catch {
        currentRole = ''
      }
      const canConfigure = currentRole === 'admin' || currentRole === 'super_admin'
      if (canConfigure) {
        ElMessageBox.confirm(detail, '需要配置 AI 模型', {
          confirmButtonText: '去配置模型',
          cancelButtonText: '暂不',
          type: 'warning',
          showClose: false,
        })
          .then(() => {
            window.location.href = '/settings/models'
          })
          .catch(() => {
            /* 用户取消，停留在当前页面 */
          })
      } else {
        ElMessageBox.alert(
          detail + '（请联系系统管理员配置 AI 模型）',
          '需要配置 AI 模型',
          { type: 'warning', showClose: false }
        )
      }
      return Promise.reject(error)
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
  /** 就地编辑数据源（name/config）；后端 merge 逻辑，Token 留空 = 保持不变 */
  update: (id: string, data: any) => api.put(`/source/${id}`, data),
  disconnect: (id: string) => api.delete(`/source/${id}`),
  // 单设 120s timeout：后端有 60s git 超时 + 10min wait_for 兜底，
  // 120s 给后端留够时间返回 504/清晰错误，避免前端 axios 默认 30s timeout
  // 先触发让用户只看到 "timeout of 30000ms exceeded" 而看不到后端真实原因。
  fetch: (data: any) => api.post('/source/fetch', data, { timeout: 120000 }),
}

// ============ 文件上传 ============
export const uploadApi = {
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
}

// ============ 测试任务 ============
export const testRunApi = {
  list: () => api.get('/test-runs'),
  getList: (params?: any) => api.get('/test-runs', { params }),
  create: (data: any) => api.post('/test-runs', data),
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
  getSettings: () => api.get('/settings'),
  updateSettings: (data: any) => api.put('/settings', data),
  getQualityGateConfig: () => api.get('/settings/quality-gate'),
  updateQualityGateConfig: (data: any) => api.put('/settings/quality-gate', data),
  testQualityGate: (data: any) => api.post('/settings/quality-gate/test', data),
  getNotificationConfig: () => api.get('/settings/notification'),
  updateNotificationConfig: (data: any) => api.put('/settings/notification', data),
}

// ============ 审计日志 ============
export const auditApi = {
  list: (params?: any) => api.get('/audit', { params }),
  getStatistics: (days?: number) => api.get('/audit/statistics', { params: { days } }),
}

// ============ 代码解析 ============
export const analysisApi = {
  run: (data: { local_path: string; test_run_id?: string }) =>
    api.post('/analysis/run', data, { timeout: 300000 }),
  upload: (formData: FormData) =>
    api.post('/analysis/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),
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

// ============ 需求文档解析（能力10） ============
export const requirementApi = {
  // 上传并解析需求文档（docx/pdf/txt）
  upload: (file: File, projectId: string, useAi: boolean = true) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('project_id', projectId)
    fd.append('use_ai', String(useAi))
    return api.post('/requirements', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    })
  },
  list: (params: any) => api.get('/requirements', { params }),
  get: (docId: string) => api.get(`/requirements/${docId}`),
  remove: (docId: string) => api.delete(`/requirements/${docId}`),
  // 基于需求一键生成测试用例
  generateCases: (docId: string, data: any) =>
    api.post(`/requirements/${docId}/generate-cases`, data, { timeout: 300000 }),
}

// ============ 代码覆盖率（能力11） ============
export const coverageApi = {
  // 上传覆盖率报告 XML（coverage.py / jacoco / istanbul / cobertura）
  upload: (file: File, payload: { project_id: string; tool: string; language?: string; test_run_id?: string }) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('project_id', payload.project_id)
    fd.append('tool', payload.tool)
    if (payload.language) fd.append('language', payload.language)
    if (payload.test_run_id) fd.append('test_run_id', payload.test_run_id)
    return api.post('/coverage', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  list: (params: any) => api.get('/coverage', { params }),
  get: (reportId: string) => api.get(`/coverage/${reportId}`),
  remove: (reportId: string) => api.delete(`/coverage/${reportId}`),
  // P1 看板
  dashboard: (projectId: string) => api.get(`/coverage/dashboard/${projectId}`),
  trend: (projectId: string, days = 30) =>
    api.get(`/coverage/trend/${projectId}`, { params: { days } }),
  files: (reportId: string, params: any) =>
    api.get(`/coverage/files/${reportId}`, { params }),
  source: (reportId: string, filePath: string) =>
    api.get(`/coverage/source/${reportId}`, { params: { file: filePath } }),
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

// ============ 脚本生成（能力5/6/7：AI 生成前置/后置/SQL 脚本） ============
export const scriptsApi = {
  /** 生成脚本：data { project_id, script_type, nl_input, context?, case_id? } */
  generateScript: (data: any) =>
    api.post('/scripts/generate', data, { timeout: 300000 }),
  /** 预览（仅语法校验，不执行）：data { script, script_type } */
  previewScript: (data: any) => api.post('/scripts/preview', data),
  /** 绑定脚本到用例：data { pre_script?, post_script?, sql_script? } */
  bindScriptToCase: (caseId: string, data: any) =>
    api.put(`/cases/${caseId}/scripts`, data),
}

// ============ 数据库连接管理（能力7：AI 生成 SQL 脚本的前置） ============
export const databaseApi = {
  listDatabases: (projectId?: string) =>
    api.get('/databases', { params: projectId ? { project_id: projectId } : {} }),
  createDatabase: (data: any) => api.post('/databases', data),
  getDatabase: (id: string) => api.get(`/databases/${id}`),
  updateDatabase: (id: string, data: any) => api.put(`/databases/${id}`, data),
  deleteDatabase: (id: string) => api.delete(`/databases/${id}`),
  getSchema: (id: string) => api.get(`/databases/${id}/schema`),
}

// ============ 定时任务（能力8：AI 生成定时任务） ============
export const scheduledTaskApi = {
  listTasks: (projectId?: string) =>
    api.get('/scheduled-tasks', { params: projectId ? { project_id: projectId } : {} }),
  createTask: (data: any) => api.post('/scheduled-tasks', data),
  getTask: (id: string) => api.get(`/scheduled-tasks/${id}`),
  updateTask: (id: string, data: any) => api.put(`/scheduled-tasks/${id}`, data),
  deleteTask: (id: string) => api.delete(`/scheduled-tasks/${id}`),
  toggleTask: (id: string) => api.post(`/scheduled-tasks/${id}/toggle`),
  getHistory: (id: string, params?: any) =>
    api.get(`/scheduled-tasks/${id}/history`, { params }),
  parseCron: (data: { nl_schedule: string }) =>
    api.post('/scheduled-tasks/parse-cron', data),
}

// ============ 报告分析（能力9：AI 分析测试报告） ============
export const reportAnalysisApi = {
  analyzeReport: (reportId: string, data?: any) =>
    api.post(`/reports/${reportId}/ai-analysis`, data, { timeout: 300000 }),
  analyzeResult: (resultId: string, data?: any) =>
    api.post(`/results/${resultId}/ai-analysis`, data, { timeout: 300000 }),
  compareResults: (resultId: string, data: any) =>
    api.post(`/results/${resultId}/compare`, data, { timeout: 300000 }),
  /** 列出测试结果（供下拉框选择已有结果），支持 project_id / test_run_id 过滤 */
  listResults: (params?: any) => api.get('/results', { params }),
}

// ============ 知识库 RAG（能力12：状态概览 / 术语表维护 / 检索预览） ============
export type KbType = 'defect' | 'case' | 'doc' | 'term'

export const knowledgeApi = {
  /** 知识库概览：enabled / 切片数 / 术语数 / 嵌入模型 / 上次重建时间 / 卡死判定 */
  getStatus: () => api.get('/knowledge'),
  /** 一键重建：省略 kbType 表示全部重建；forceFull=true 清空该知识库全部切片后全量重建（默认增量） */
  rebuild: (kbType?: KbType, forceFull = false) =>
    api.post('/knowledge/rebuild', { kb_type: kbType, force_full: forceFull }),
  /** 强制重置重建状态机（admin）：用于状态卡死无法自愈时 */
  reset: () => api.post('/knowledge/reset'),
  /** 运行时切换 KB_RAG_ENABLED 开关（admin），无需重启 backend */
  updateConfig: (data: { kb_rag_enabled: boolean }) =>
    api.put('/knowledge/config', data),
  /** 术语列表（分页 + 关键词搜索 q） */
  listTerms: (params: { page?: number; size?: number; q?: string }) =>
    api.get('/knowledge/terms', { params }),
  /** 新建术语 */
  createTerm: (data: {
    term: string
    technical_meaning: string
    aliases?: string[]
    domain?: string
    meta?: Record<string, unknown>
  }) => api.post('/knowledge/terms', data),
  /** 术语详情 */
  getTerm: (id: string) => api.get(`/knowledge/terms/${id}`),
  /** 更新术语（字段全可选） */
  updateTerm: (
    id: string,
    data: {
      term?: string
      technical_meaning?: string
      aliases?: string[]
      domain?: string
      meta?: Record<string, unknown>
    }
  ) => api.put(`/knowledge/terms/${id}`, data),
  /** 删除术语 */
  removeTerm: (id: string) => api.delete(`/knowledge/terms/${id}`),
  /** 检索预览 */
  search: (data: { query: string; kb_type: string; top_k?: number }) =>
    api.post('/knowledge/search', data),
}

export default api
