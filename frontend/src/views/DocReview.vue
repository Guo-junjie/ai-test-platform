<template>
  <div class="doc-review">
    <el-card shadow="hover">
      <template #header>评审对象</template>
      <el-form label-width="90px" :inline="true">
        <el-form-item label="项目" required>
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 200px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档">
          <el-select
            v-model="docId"
            placeholder="选择文档（已解析）"
            filterable
            clearable
            style="width: 280px"
            @change="onDocChange"
          >
            <el-option v-for="d in docs" :key="d.doc_id" :label="`${d.filename} (${d.status})`" :value="d.doc_id" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-radio-group v-model="scope" style="margin-bottom: 12px">
        <el-radio label="all">全量评审</el-radio>
        <el-radio label="specified">指定接口</el-radio>
      </el-radio-group>

      <el-select
        v-if="scope === 'specified'"
        v-model="selectedEndpointIds"
        multiple
        filterable
        placeholder="选择要评审的接口资产"
        style="width: 100%; margin-bottom: 12px"
      >
        <el-option
          v-for="e in endpointAssets"
          :key="e.id"
          :label="`${e.method} ${e.path}`"
          :value="e.id"
        />
      </el-select>

      <div v-if="scope === 'all' && previewEndpoints.length" class="preview">
        <span class="muted">待评审接口预览（共 {{ previewEndpoints.length }} 个）：</span>
        <ApiSpecTable :endpoints="previewEndpoints" :hide-toolbar="true" :max-height="260" />
      </div>

      <el-button
        type="primary"
        :loading="reviewing"
        :disabled="!canReview"
        @click="startReview"
      >
        开始评审
      </el-button>
    </el-card>

    <!-- 评审结论 -->
    <el-card v-if="result" shadow="hover" style="margin-top: 16px" v-loading="reviewing">
      <template #header>
        评审结论
        <el-tag size="small" :type="result.review_engine === 'ai' ? 'success' : 'info'" style="margin-left: 8px">
          {{ result.review_engine === 'ai' ? 'AI 评审' : '规则评审（未配置 AI 模型）' }}
        </el-tag>
      </template>

      <el-row :gutter="16">
        <el-col :xs="24" :md="8">
          <div class="score-card">
            <div class="score-num">{{ result.overall_score }}<span class="score-max">/5</span></div>
            <el-rate :model-value="result.overall_score / 5" allow-half disabled />
            <div class="score-level">{{ scoreLevel(result.overall_score) }}</div>
          </div>
        </el-col>
        <el-col :xs="24" :md="16">
          <ReviewRadar :scores="result.dimension_scores" :height="240" />
        </el-col>
      </el-row>

      <el-alert v-if="result.summary" :title="result.summary" type="info" :closable="false" style="margin: 12px 0" />

      <el-descriptions title="四维评分" :column="2" border style="margin-top: 12px">
        <el-descriptions-item v-for="d in result.dimensions" :key="d.dimension" :label="dimLabel(d.dimension)">
          {{ d.score }} 分 — {{ d.comment }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 问题清单 -->
    <el-card v-if="result" shadow="hover" style="margin-top: 16px">
      <template #header>问题清单</template>
      <div class="filters">
        <el-select v-model="filterDim" placeholder="维度" clearable style="width: 180px">
          <el-option v-for="k in dimKeys" :key="k" :label="dimLabel(k)" :value="k" />
        </el-select>
        <el-select v-model="filterSev" placeholder="严重度" clearable style="width: 140px">
          <el-option label="high" value="high" />
          <el-option label="medium" value="medium" />
          <el-option label="low" value="low" />
        </el-select>
      </div>
      <el-table :data="filteredIssues" border style="margin-top: 12px">
        <el-table-column prop="dimension" label="维度" width="120">
          <template #default="{ row }">{{ dimLabel(row.dimension) }}</template>
        </el-table-column>
        <el-table-column prop="target" label="目标接口" width="200" show-overflow-tooltip />
        <el-table-column label="严重度" width="90">
          <template #default="{ row }">
            <el-tag :type="sevType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="issue" label="问题" show-overflow-tooltip />
        <el-table-column prop="root_cause" label="归因" show-overflow-tooltip />
        <el-table-column prop="suggestion" label="建议" show-overflow-tooltip />
        <el-table-column type="expand" label="详情" width="70">
          <template #default="{ row }">
            <div class="issue-detail">
              <p><b>建议：</b>{{ row.suggestion }}</p>
              <pre v-if="row.example" class="json-box">{{ row.example }}</pre>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 历史评审 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header>
        历史评审
        <el-button size="small" style="float: right" @click="loadHistory">刷新</el-button>
      </template>
      <el-table :data="history" v-loading="historyLoading" size="small" border>
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column label="总分" width="80" align="center">
          <template #default="{ row }">{{ row.overall_score }}</template>
        </el-table-column>
        <el-table-column prop="review_engine" label="引擎" width="100">
          <template #default="{ row }">
            <el-tag :type="row.review_engine === 'ai' ? 'success' : 'info'" size="small">
              {{ row.review_engine === 'ai' ? 'AI' : '规则' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="issue_count" label="问题数" width="80" align="center" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="viewHistory(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { docApi, projectApi } from '@/api'
import ApiSpecTable from '@/components/ApiSpecTable.vue'
import ReviewRadar from '@/components/ReviewRadar.vue'

const route = useRoute()

const projects = ref<any[]>([])
const projectId = ref<string>('')
const docs = ref<any[]>([])
const docId = ref<string>('')
const scope = ref<'all' | 'specified'>('all')
const selectedEndpointIds = ref<string[]>([])
const endpointAssets = ref<any[]>([])
const previewEndpoints = ref<any[]>([])

const reviewing = ref(false)
const result = ref<any>(null)

const filterDim = ref<string>('')
const filterSev = ref<string>('')
const history = ref<any[]>([])
const historyLoading = ref(false)

const DIM_LABELS: Record<string, string> = {
  basic_info: '基本信息',
  request_params: '请求参数',
  response_definition: '响应定义',
  security_auth: '安全认证',
}
const dimKeys = Object.keys(DIM_LABELS)

const canReview = computed(() => !!projectId.value && !!docId.value && !reviewing.value)

function dimLabel(k: string): string {
  return DIM_LABELS[k] || k
}

function scoreLevel(s: number): string {
  if (s >= 4.5) return '优秀'
  if (s >= 3.5) return '良好'
  if (s >= 2.5) return '一般'
  return '较差'
}

function sevType(sev: string): any {
  if (sev === 'high') return 'danger'
  if (sev === 'medium') return 'warning'
  return 'info'
}

const filteredIssues = computed(() => {
  if (!result.value?.issues) return []
  return result.value.issues.filter((it: any) => {
    if (filterDim.value && it.dimension !== filterDim.value) return false
    if (filterSev.value && it.severity !== filterSev.value) return false
    return true
  })
})

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    projects.value = []
  }
}

async function onProjectChange() {
  docId.value = ''
  previewEndpoints.value = []
  endpointAssets.value = []
  selectedEndpointIds.value = []
  await loadDocs()
}

async function loadDocs() {
  if (!projectId.value) {
    docs.value = []
    return
  }
  try {
    const res: any = await docApi.list({ project_id: projectId.value, page: 1, page_size: 100 })
    docs.value = res?.data?.items || []
  } catch {
    docs.value = []
  }
}

async function onDocChange() {
  result.value = null
  previewEndpoints.value = []
  endpointAssets.value = []
  selectedEndpointIds.value = []
  if (!docId.value) return
  try {
    const res: any = await docApi.get(docId.value)
    previewEndpoints.value = res?.data?.api_spec?.endpoints || []
  } catch {
    /* ignore */
  }
  await loadEndpointAssets()
  await loadHistory()
}

async function loadEndpointAssets() {
  if (!projectId.value) return
  try {
    const res: any = await docApi.listEndpoints({
      project_id: projectId.value,
      doc_id: docId.value || undefined,
      page: 1,
      page_size: 200,
    })
    endpointAssets.value = res?.data?.items || []
  } catch {
    endpointAssets.value = []
  }
}

async function startReview() {
  if (!projectId.value || !docId.value) return
  reviewing.value = true
  result.value = null
  try {
    const payload: any = {
      doc_id: docId.value,
      project_id: projectId.value,
      use_ai: true,
    }
    if (scope.value === 'specified' && selectedEndpointIds.value.length) {
      payload.endpoint_ids = selectedEndpointIds.value
    }
    const res: any = await docApi.review(payload)
    result.value = res?.data || {}
    await loadHistory()
    ElMessage.success('评审完成')
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    reviewing.value = false
  }
}

async function loadHistory() {
  if (!docId.value) {
    history.value = []
    return
  }
  historyLoading.value = true
  try {
    const res: any = await docApi.listReviews({ doc_id: docId.value, page: 1, page_size: 50 })
    history.value = res?.data?.items || []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

async function viewHistory(row: any) {
  try {
    const res: any = await docApi.getReview(row.review_id)
    result.value = res?.data || {}
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
  await loadProjects()
  const qid = route.query.doc_id as string | undefined
  if (qid) {
    try {
      const res: any = await docApi.get(qid)
      const pid = res?.data?.project_id
      if (pid) {
        projectId.value = pid
        await loadDocs()
        docId.value = qid
        await onDocChange()
      }
    } catch {
      /* ignore */
    }
  }
})
</script>

<style scoped>
.preview {
  margin-bottom: 12px;
}
.muted {
  color: #909399;
  font-size: 13px;
}
.score-card {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 8px;
}
.score-num {
  font-size: 48px;
  font-weight: 700;
  color: #409eff;
  line-height: 1;
}
.score-max {
  font-size: 18px;
  color: #909399;
  margin-left: 4px;
}
.score-level {
  margin-top: 8px;
  font-size: 15px;
  color: #606266;
}
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}
.issue-detail {
  padding: 8px 16px;
}
.json-box {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
