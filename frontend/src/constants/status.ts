export const RUN_STATUS: Record<string, { label: string; type: '' | 'success' | 'warning' | 'danger' | 'info' }> = {
  pending: { label: '等待中', type: 'info' }, pulling: { label: '拉取代码', type: 'warning' },
  analyzing: { label: '解析代码', type: 'warning' }, generating: { label: '生成用例', type: 'warning' },
  executing: { label: '运行中', type: 'warning' }, analyzing_defects: { label: '分析缺陷', type: 'warning' },
  reporting: { label: '生成报告', type: 'warning' }, completed: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' }, cancelled: { label: '已取消', type: 'info' },
}
export const REVIEW_STATUS: Record<string, { label: string; type: '' | 'success' | 'warning' | 'danger' | 'info' }> = {
  draft: { label: '草稿', type: 'info' }, pending: { label: '待评审', type: 'warning' },
  approved: { label: '已通过', type: 'success' }, changes_requested: { label: '需修改', type: 'danger' },
  deprecated: { label: '已归档', type: 'info' },
}
export const TRIGGER_LABELS: Record<string, string> = { manual: '手动', schedule: '定时任务', webhook: 'CI / Webhook', retry: '重试' }
export const DEFECT_SEVERITY: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  P0: { label: '致命', type: 'danger' }, P1: { label: '严重', type: 'warning' }, P2: { label: '一般', type: 'info' }, P3: { label: '轻微', type: 'info' },
}
