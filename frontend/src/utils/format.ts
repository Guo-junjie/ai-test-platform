export const TEST_STATUS_LABELS: Record<string, string> = {
  pending: '等待执行', pulling: '拉取代码', analyzing: '分析中', generating: '生成用例',
  executing: '执行中', analyzing_defects: '缺陷分析', reporting: '生成报告',
  completed: '已完成', failed: '失败', cancelled: '已取消', running: '运行中',
}

export function normalizeStatus(status?: string | null): string {
  return String(status || 'pending').toLowerCase()
}

export function testStatusLabel(status?: string | null): string {
  const value = normalizeStatus(status)
  return TEST_STATUS_LABELS[value] || status || '未知'
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}
