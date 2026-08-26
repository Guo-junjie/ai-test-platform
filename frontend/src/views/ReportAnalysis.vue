<template>
  <div class="report-analysis-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>报告 AI 分析</span>
        </div>
      </template>

      <el-alert
        title="AI 智能分析"
        description="对测试报告和测试结果进行 AI 深度分析，包括失败根因分析、报告摘要和两次执行对比。选择项目后，下方会列出该项目已有的报告 / 结果 / 测试任务，直接下拉选择即可，无需手动粘贴 ID。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-form label-width="120px" style="max-width: 820px;">
        <el-form-item label="项目">
          <el-select
            v-model="projectId"
            filterable
            placeholder="选择项目"
            style="width: 100%;"
            @change="onProjectChange"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-button
            link
            type="primary"
            :loading="loadingOpts"
            style="margin-left: 8px"
            @click="loadOptions"
          >
            刷新列表
          </el-button>
        </el-form-item>

        <el-form-item label="分析类型">
          <el-radio-group v-model="analysisType" @change="onAnalysisTypeChange">
            <el-radio-button value="summary">报告摘要</el-radio-button>
            <el-radio-button value="failure">失败分析</el-radio-button>
            <el-radio-button value="compare">执行对比</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="输入方式">
          <el-switch v-model="manualEntry" active-text="手动输入 ID" inactive-text="下拉选择" />
          <span class="hint">默认下拉选择已有数据；找不到时再切换手动输入</span>
        </el-form-item>

        <!-- 报告摘要：选择已有报告 -->
        <template v-if="analysisType === 'summary'">
          <el-form-item label="测试报告">
            <el-select
              v-if="!manualEntry"
              v-model="reportId"
              filterable
              clearable
              placeholder="选择测试报告"
              :loading="loadingOpts"
              style="width: 100%;"
            >
              <el-option
                v-for="r in reportOptions"
                :key="r.id"
                :label="reportLabel(r)"
                :value="r.id"
              />
            </el-select>
            <el-input v-else v-model="reportId" placeholder="输入测试报告 ID" />
          </el-form-item>
          <el-alert
            v-if="!manualEntry && !loadingOpts && reportOptions.length === 0"
            type="warning"
            :closable="false"
            title="该项目暂无测试报告"
            description="请先完成一次测试运行并生成报告后，再来此做 AI 分析。"
            style="margin: -8px 0 16px 120px; max-width: 640px;"
          />
        </template>

        <!-- 失败分析 / 执行对比：选择已有结果 -->
        <template v-else>
          <el-form-item :label="analysisType === 'compare' ? '当前结果' : '测试结果'">
            <el-select
              v-if="!manualEntry"
              v-model="resultId"
              filterable
              clearable
              placeholder="选择测试结果"
              :loading="loadingOpts"
              style="width: 100%;"
            >
              <el-option
                v-for="r in resultOptions"
                :key="r.id"
                :label="resultLabel(r)"
                :value="r.id"
              />
            </el-select>
            <el-input v-else v-model="resultId" placeholder="输入测试结果 ID" />
          </el-form-item>
          <el-alert
            v-if="!manualEntry && !loadingOpts && resultOptions.length === 0"
            type="warning"
            :closable="false"
            title="该项目暂无测试结果"
            description="请先执行测试产生结果后，再来此做 AI 分析。"
            style="margin: -8px 0 16px 120px; max-width: 640px;"
          />
        </template>

        <!-- 执行对比：选择对比 Run -->
        <el-form-item v-if="analysisType === 'compare'" label="对比 Run">
          <el-select
            v-if="!manualEntry"
            v-model="compareRunId"
            filterable
            clearable
            placeholder="选择对比的测试任务"
            :loading="loadingOpts"
            style="width: 100%;"
          >
            <el-option
              v-for="r in runOptions"
              :key="r.id"
              :label="runLabel(r)"
              :value="r.id"
            />
          </el-select>
          <el-input v-else v-model="compareRunId" placeholder="输入对比的测试运行 ID" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="analyzing" @click="handleAnalyze">
            <el-icon style="margin-right: 4px;"><MagicStick /></el-icon>
            开始分析
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="analysisResult" shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>分析结果</span>
          <el-button size="small" @click="copyResult">复制 JSON</el-button>
        </div>
      </template>

      <el-tabs v-model="viewMode">
        <el-tab-pane label="结构化视图" name="structured">
          <el-descriptions :column="2" border>
            <el-descriptions-item
              v-for="(value, key) in analysisResult"
              :key="key"
              :label="formatKey(key)"
            >
              <template v-if="Array.isArray(value)">
                <el-tag v-for="(item, idx) in value" :key="idx" size="small" style="margin-right: 4px; margin-bottom: 4px;">
                  {{ item }}
                </el-tag>
              </template>
              <template v-else-if="typeof value === 'boolean'">
                <el-tag :type="value ? 'success' : 'danger'">{{ value ? '是' : '否' }}</el-tag>
              </template>
              <template v-else>
                {{ value }}
              </template>
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="JSON 视图" name="json">
          <pre class="code-block"><code>{{ jsonPreview }}</code></pre>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { reportAnalysisApi, projectApi, reportApi, testRunApi } from '@/api'

const projectId = ref('')
const projects = ref<any[]>([])
const analysisType = ref('summary')
const manualEntry = ref(false)
const reportId = ref('')
const resultId = ref('')
const compareRunId = ref('')
const loadingOpts = ref(false)
const analyzing = ref(false)
const analysisResult = ref<Record<string, any> | null>(null)
const viewMode = ref('structured')

const reportOptions = ref<any[]>([])
const resultOptions = ref<any[]>([])
const runOptions = ref<any[]>([])

const jsonPreview = computed(() => {
  return analysisResult.value ? JSON.stringify(analysisResult.value, null, 2) : ''
})

const keyLabels: Record<string, string> = {
  root_cause: '根因分析',
  category: '失败类别',
  severity: '严重程度',
  fix_suggestion: '修复建议',
  confidence: '置信度',
  summary: '摘要',
  quality_assessment: '质量评估',
  key_findings: '关键发现',
  recommendations: '改进建议',
  risk_level: '风险等级',
  comparison: '对比结论',
  regression: '是否回归',
  improvement: '是否有改进',
  response_time_diff: '响应时间差异',
  status_diff: '状态差异',
  details: '详细说明',
}

function formatKey(key: string): string {
  return keyLabels[key] || key
}

function shortId(id?: string): string {
  return id ? id.slice(0, 8) : '—'
}

function formatDate(s?: string): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

function reportLabel(r: any): string {
  return `报告 ${shortId(r.test_run_id)} · 质量分 ${r.quality_score ?? '—'} · ${formatDate(r.created_at)}`
}

function resultLabel(r: any): string {
  const status = r.is_passed ? '✓通过' : '✗失败'
  return `用例 ${r.case_name || 'unknown'} · ${status} · ${r.status_code ?? '—'} · ${formatDate(r.executed_at)}`
}

function runLabel(r: any): string {
  return `Run ${shortId(r.id)} · ${r.status || '—'} · ${formatDate(r.created_at)}`
}

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    projects.value = []
  }
}

async function loadOptions(): Promise<void> {
  if (!projectId.value) {
    reportOptions.value = []
    resultOptions.value = []
    runOptions.value = []
    return
  }
  loadingOpts.value = true
  try {
    const [repRes, resRes, runRes] = await Promise.all([
      reportApi.getList({ project_id: projectId.value }),
      reportAnalysisApi.listResults({ project_id: projectId.value }),
      testRunApi.list(),
    ])
    const repData = repRes?.data
    reportOptions.value = Array.isArray(repData) ? repData : (repData?.list || [])
    const resData = resRes?.data
    resultOptions.value = Array.isArray(resData) ? resData : (resData?.list || [])
    const runData = runRes?.data
    const allRuns = Array.isArray(runData) ? runData : (runData?.list || [])
    runOptions.value = allRuns.filter((r: any) => r.project_id === projectId.value)
  } catch (e: any) {
    ElMessage.error('加载选项失败: ' + (e?.message || e))
  } finally {
    loadingOpts.value = false
  }
}

function onProjectChange(): void {
  // 切换项目后清空已选值并重新拉取可选项
  reportId.value = ''
  resultId.value = ''
  compareRunId.value = ''
  loadOptions()
}

function onAnalysisTypeChange(): void {
  // 切换分析类型时清空与目标无关的选择
  reportId.value = ''
  resultId.value = ''
  compareRunId.value = ''
}

async function handleAnalyze(): Promise<void> {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }

  if (analysisType.value === 'summary' && !reportId.value.trim()) {
    ElMessage.warning(manualEntry.value ? '请输入报告 ID' : '请选择测试报告')
    return
  }
  if (analysisType.value !== 'summary' && !resultId.value.trim()) {
    ElMessage.warning(manualEntry.value ? '请输入结果 ID' : '请选择测试结果')
    return
  }
  if (analysisType.value === 'compare' && !compareRunId.value.trim()) {
    ElMessage.warning(manualEntry.value ? '请输入对比 Run ID' : '请选择对比的测试任务')
    return
  }

  analyzing.value = true
  analysisResult.value = null
  try {
    let res: any
    if (analysisType.value === 'summary') {
      res = await reportAnalysisApi.analyzeReport(reportId.value, { project_id: projectId.value, analysis_type: 'summary' })
    } else if (analysisType.value === 'failure') {
      res = await reportAnalysisApi.analyzeResult(resultId.value, { project_id: projectId.value })
    } else {
      res = await reportAnalysisApi.compareResults(resultId.value, {
        project_id: projectId.value,
        compare_run_id: compareRunId.value,
      })
    }
    analysisResult.value = res?.data ?? res
    ElMessage.success('分析完成')
  } catch (e: any) {
    ElMessage.error(e?.message || '分析失败')
  } finally {
    analyzing.value = false
  }
}

async function copyResult(): Promise<void> {
  try {
    await navigator.clipboard.writeText(jsonPreview.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.hint {
  color: #909399;
  font-size: 12px;
  margin-left: 12px;
}

.code-block {
  background-color: #282c34;
  color: #abb2bf;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  max-height: 500px;
  overflow-y: auto;
  margin: 0;
}
</style>
