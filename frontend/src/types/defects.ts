export type DefectState = 'new' | 'unassigned' | 'in_progress' | 'pending_verification' | 'resolved' | 'closed' | 'reopened' | 'rejected'
export type DefectPriority = 'urgent' | 'high' | 'normal' | 'low'
export interface DefectAction {
  action_id: string
  label: string
  to: DefectState
  allowed: boolean
  disabled_reason?: string
  required_fields: string[]
  required_any?: string[][]
}
export interface DefectRecord {
  id: string
  defect_key: string
  project_id: string
  project_name?: string
  title: string
  description: string
  severity: string
  defect_type: string
  priority: DefectPriority
  priority_label: string
  workflow_state: DefectState
  workflow_state_label: string
  row_version: number
  assignee_id?: string | null
  assignee_name?: string
  verifier_id?: string | null
  verifier_name?: string
  reporter_id?: string
  reporter_name?: string
  labels: string[]
  reproduce_steps: string[]
  permissions: { edit: boolean; assign: boolean; delete: boolean; restore: boolean }
  transitions: DefectAction[]
  [key: string]: any
}
export const defectStates: Record<string, string> = { new: '新建', unassigned: '待分配', in_progress: '处理中', pending_verification: '待验证', resolved: '已解决', closed: '已关闭', reopened: '重开', rejected: '拒绝' }
export const defectPriorities: Record<string, string> = { urgent: '紧急', high: '高', normal: '普通', low: '低' }
export const defectTypes: Record<string, string> = { business: '业务缺陷', program: '程序缺陷', performance: '性能缺陷', integration: '集成缺陷', security: '安全缺陷' }
export const severityLabels: Record<string, string> = { P0: '致命', P1: '严重', P2: '一般', P3: '轻微' }
export const defectFieldLabels: Record<string, string> = {
  title: '标题', description: '描述', severity: '严重程度', priority: '优先级', defect_type: '缺陷类型',
  assignee_id: '处理人', verifier_id: '验证人', reporter_id: '报告人', workflow_state: '状态',
  module_id: '所属模块', iteration_id: '迭代', environment_profile_id: '环境', labels: '标签',
  reproduce_steps: '复现步骤', preconditions: '前置条件', expected_result: '预期结果', actual_result: '实际结果',
  fix_build: '修复构建号', verified_build: '验证构建号', resolution: '解决结果', resolution_note: '解决说明',
  due_at: '截止时间', deleted_at: '删除时间', reopened_count: '重开次数', fix_release_id: '修复版本',
  verified_release_id: '验证版本', proposed_resolution: '建议解决结果', reproducibility: '复现概率',
  fix_submitted_at: '修复提交时间', resolved_at: '验证通过时间', closed_at: '关闭时间', started_at: '开始处理时间',
  first_resolved_at: '首次验证通过时间', assigned_at: '指派时间', fix_submitted_by_id: '修复提交人',
  resolved_by_id: '验证通过操作者', closed_by_id: '关闭操作者', duplicate_of_id: '主缺陷',
}
export function defectStateColor(state: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  return ['resolved', 'closed'].includes(state) ? 'success' : state === 'reopened' ? 'danger' : state === 'pending_verification' ? 'warning' : state === 'in_progress' ? 'primary' : 'info'
}
export function defectTime(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}
