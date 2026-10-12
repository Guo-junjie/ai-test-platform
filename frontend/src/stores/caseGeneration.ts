import { reactive } from 'vue'
import { defineStore } from 'pinia'

export interface RequirementGenerationRuntime {
  status: 'running' | 'completed' | 'failed'
  result?: any
  error?: string
}

export const useCaseGenerationRuntimeStore = defineStore('case-generation-runtime', () => {
  const requirementJobs = reactive<Record<string, RequirementGenerationRuntime>>({})
  const requests = new Map<string, Promise<any>>()

  async function runRequirementJob(key: string, runner: () => Promise<any>): Promise<any> {
    const existing = requests.get(key)
    if (existing) return existing
    requirementJobs[key] = { status: 'running' }
    const request = runner()
      .then((result) => {
        requirementJobs[key] = { status: 'completed', result }
        return result
      })
      .catch((error) => {
        const message = error?.response?.data?.detail || error?.message || '用例生成失败'
        requirementJobs[key] = { status: 'failed', error: String(message) }
        throw error
      })
      .finally(() => requests.delete(key))
    requests.set(key, request)
    return request
  }

  return { requirementJobs, runRequirementJob }
})
