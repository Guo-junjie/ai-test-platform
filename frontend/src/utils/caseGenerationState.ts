import { safeGetSessionItem, safeRemoveSessionItem, safeSetSessionItem } from '@/utils/safeStorage'

export type CaseGenerationSource = 'requirement' | 'interface'

export interface CaseGenerationContext {
  projectId: string
  source: CaseGenerationSource
}

export interface CaseGenerationSnapshot {
  activeDocId?: string
  activeTaskId?: string
  selectedKeys?: string[]
  docType?: string
  overwrite?: boolean
  assetTab?: 'docs' | 'endpoints'
  taskDetailVisible?: boolean
  generationPreview?: any
  previewVisible?: boolean
  useAi?: boolean
  genUseAi?: boolean
  generationResult?: any
}

const VERSION = 'v1'

function parse<T>(raw: string | null): T | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function contextKey(userId: string) {
  return `case-generation:${VERSION}:${userId}:context`
}

function snapshotKey(userId: string, source: CaseGenerationSource, projectId: string) {
  return `case-generation:${VERSION}:${userId}:${source}:${projectId}`
}

export function loadCaseGenerationContext(userId: string): CaseGenerationContext | null {
  return parse<CaseGenerationContext>(safeGetSessionItem(contextKey(userId)))
}

export function saveCaseGenerationContext(userId: string, context: CaseGenerationContext): void {
  safeSetSessionItem(contextKey(userId), JSON.stringify(context))
}

export function loadCaseGenerationSnapshot(
  userId: string,
  source: CaseGenerationSource,
  projectId: string,
): CaseGenerationSnapshot {
  return parse<CaseGenerationSnapshot>(
    safeGetSessionItem(snapshotKey(userId, source, projectId)),
  ) || {}
}

export function saveCaseGenerationSnapshot(
  userId: string,
  source: CaseGenerationSource,
  projectId: string,
  snapshot: CaseGenerationSnapshot,
): void {
  if (!projectId) return
  safeSetSessionItem(snapshotKey(userId, source, projectId), JSON.stringify(snapshot))
}

export function clearCaseGenerationSnapshot(
  userId: string,
  source: CaseGenerationSource,
  projectId: string,
): void {
  if (!projectId) return
  safeRemoveSessionItem(snapshotKey(userId, source, projectId))
}
