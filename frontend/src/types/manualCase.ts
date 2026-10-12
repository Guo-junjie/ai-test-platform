export type ManualCaseType = 'functional' | 'positive' | 'negative' | 'boundary' | 'exception'

export interface CreateManualCasePayload {
  project_id: string
  title: string
  description: string
  folder: string
  preconditions: string
  steps: string[]
  expected_result: string
  priority: 'P0' | 'P1' | 'P2' | 'P3'
  case_type: ManualCaseType
  tags: string[]
  requirement_doc_id: string | null
  requirement_ref: string
  allow_duplicate?: boolean
}

export interface ManualCaseOptions {
  folders: string[]
  tags: string[]
  requirements: Array<{ id: string; filename: string }>
}

export const MANUAL_CASE_TYPES: Array<{ value: ManualCaseType; label: string }> = [
  { value: 'functional', label: '需求 / 功能' },
  { value: 'positive', label: '正向' },
  { value: 'negative', label: '反向' },
  { value: 'boundary', label: '边界' },
  { value: 'exception', label: '异常' },
]
