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
        description="对测试报告和测试结果进行 AI 深度分析，包括失败根因分析、报告摘要和两次执行对比。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-form label-width="120px" style="max-width: 800px;">
        <el-form-item label="项目">
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%;">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="分析类型">
          <el-radio-group v-model="analysisType">
            <el-radio-button value="summary">报告摘要</el-radio-button>
            <el-radio-button value="failure">失败分析</el-radio-button>
            <el-radio-button value="compare">执行对比</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="analysisType === 'summary'" label="报告 ID">
          <el-input v-model="reportId" placeholder="输入测试报告 ID" />
        </el-form-item>

        <el-form-item v-else-if="analysisType === 'failure'" label="结果 ID">
          <el-input v-model="resultId" placeholder="输入测试结果 ID" />
        </el-form-item>

        <el-form-item v-else label="结果 ID">
          <el-input v-model="resultId" placeholder="输入测试结果 ID" />
        </el-form-item>

        <el-form-item v-if="analysisType === 'compare'" label="对比 Run ID">
          <el-input v-model="compareRunId" placeholder="输入对比的测试运行 ID" />
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
import { reportAnalysisApi, projectApi } from '@/api'

const projectId = ref('')
const projects = ref<any[]>([])
const analysisType = ref('summary')
const reportId = ref('')
const resultId = ref('')
const compareRunId = ref('')
const analyzing = ref(false)
const analysisResult = ref<Record<string, any> | null>(null)
const viewMode = ref('structured')

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

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    projects.value = []
  }
}

async function handleAnalyze(): Promise<void> {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }

  if (analysisType.value === 'summary' && !reportId.value.trim()) {
    ElMessage.warning('请输入报告 ID')
    return
  }
  if (analysisType.value !== 'summary' && !resultId.value.trim()) {
    ElMessage.warning('请输入结果 ID')
    return
  }
  if (analysisType.value === 'compare' && !compareRunId.value.trim()) {
    ElMessage.warning('请输入对比 Run ID')
    return
  }

  analyzing.value = true
  analysisResult.value = null
  try {
    let res: any
    if (analysisType.value === 'summary') {
      res = await reportAnalysisApi.analyzeReport(reportId.value, { project_id: projectId.value })
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
