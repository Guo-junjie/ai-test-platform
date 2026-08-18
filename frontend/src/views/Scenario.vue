<template>
  <div class="scenario-page">
    <!-- 编排输入区 -->
    <el-card shadow="hover">
      <template #header>AI 编排测试场景</template>
      <el-form label-width="80px">
        <el-form-item label="项目" required>
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 260px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="接口">
          <el-select
            v-model="selectedEndpointIds"
            multiple
            filterable
            collapse-tags
            placeholder="不选则按自然语言自动检索"
            style="width: 420px"
            @visible-change="onEndpointVisible"
          >
            <el-option v-for="e in endpoints" :key="e.id" :label="`${e.method} ${e.path}`" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景描述" required>
          <el-input
            v-model="nlInput"
            type="textarea"
            :rows="4"
            placeholder="用自然语言描述测试场景，例如：用户先登录获取 token，然后创建订单，再用 token 查询订单详情"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="orchestrating" :disabled="!canOrchestrate" @click="orchestrate">AI 编排</el-button>
          <el-button :loading="dryRunning" :disabled="!canOrchestrate" @click="dryRun">预览（dry-run）</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 编排结果 -->
    <el-card v-if="scenario" shadow="hover" style="margin-top: 16px" v-loading="saving || adopting">
      <template #header>
        编排结果
        <el-tag size="small" style="margin-left: 8px">{{ scenario.name }}</el-tag>
        <el-tag size="small" :type="statusType(scenario.status)" style="margin-left: 8px">
          {{ statusLabel(scenario.status) }}
        </el-tag>
        <el-tag v-if="scenario.engine" size="small" :type="scenario.engine === 'ai' ? 'success' : 'info'" style="margin-left: 8px">
          {{ scenario.engine === 'ai' ? 'AI 编排' : '规则兜底' }}
        </el-tag>
        <span class="muted" style="margin-left: 8px">（共 {{ scenario.steps?.length || 0 }} 步）</span>
      </template>

      <!-- 步骤依赖链 -->
      <el-steps :active="(scenario.steps?.length || 0)" align-center finish-status="success" style="margin-bottom: 16px">
        <el-step
          v-for="(step, idx) in scenario.steps"
          :key="idx"
          :title="`步骤 ${step.step_order}`"
          :description="`${step.method} ${step.url}`"
        />
      </el-steps>

      <!-- 步骤明细 -->
      <el-collapse v-model="activeSteps">
        <el-collapse-item v-for="(step, idx) in scenario.steps" :key="idx" :name="idx">
          <template #title>
            <span class="step-title">
              <b>#{{ step.step_order }}</b>
              <span class="method-tag">{{ step.method }}</span>
              <span class="url-text">{{ step.url }}</span>
              <span class="action-desc">{{ step.action_desc }}</span>
            </span>
          </template>
          <div class="step-detail">
            <div><b>动作：</b>{{ step.action_desc || '-' }}</div>
            <div v-if="step.depend_on_step">
              <b>依赖前驱步骤：</b><el-tag size="small" type="warning">#{{ step.depend_on_step }}</el-tag>
            </div>
            <div v-if="step.extract && Object.keys(step.extract).length">
              <b>提取变量：</b>
              <el-tag v-for="(path, key) in step.extract" :key="key" size="small" type="success" style="margin-right: 6px">
                {{ key }} → {{ path }}
              </el-tag>
            </div>
            <div v-if="step.inject && Object.keys(step.inject).length">
              <b>变量去向：</b>
              <el-tag v-for="(target, key) in step.inject" :key="key" size="small" style="margin-right: 6px">
                {{ key }} → {{ target }}
              </el-tag>
            </div>
            <div>
              <b>请求：</b>
              <pre class="json-box">{{ JSON.stringify(step.request || {}, null, 2) }}</pre>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div style="margin-top: 16px">
        <el-button type="primary" :loading="saving" @click="save">保存步骤</el-button>
        <el-button type="success" :loading="adopting" :disabled="scenario.status === 'adopted'" @click="adopt">采纳</el-button>
        <el-button @click="editSteps">编辑步骤 JSON</el-button>
      </div>
    </el-card>

    <!-- dry-run 预览 -->
    <el-dialog v-model="previewVisible" title="场景预览（dry-run，未接真实 HTTP）" width="760px">
      <el-alert
        :title="`底层引擎：${previewData.source_engine === 'ai' ? 'AI 编排' : '规则兜底'} · ${previewData.note || ''}`"
        type="info"
        :closable="false"
        style="margin-bottom: 12px"
      />
      <el-timeline>
        <el-timeline-item
          v-for="(req, idx) in previewData.preview_requests || []"
          :key="idx"
          :timestamp="`步骤 ${req.step_order} · ${req.method} ${req.url}`"
          placement="top"
        >
          <pre class="json-box">{{ JSON.stringify(req.request, null, 2) }}</pre>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!(previewData.preview_requests || []).length" description="未生成任何请求步骤" />
    </el-dialog>

    <!-- 编辑步骤 JSON 对话框 -->
    <el-dialog v-model="editVisible" title="编辑步骤 JSON" width="720px" destroy-on-close>
      <el-input v-model="editStepsJson" type="textarea" :rows="16" placeholder="JSON 数组" />
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditedSteps">保存</el-button>
      </template>
    </el-dialog>

    <!-- 历史场景 -->
    <el-card shadow="hover" style="margin-top: 16px" v-loading="historyLoading">
      <template #header>
        历史场景
        <el-button size="small" style="float: right" @click="loadHistory">刷新</el-button>
      </template>
      <el-table :data="history" size="small" border>
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="nl_input" label="场景描述" min-width="240" show-overflow-tooltip />
        <el-table-column label="步数" width="70" align="center">
          <template #default="{ row }">{{ (row.steps || []).length }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="loadOne(row)">查看</el-button>
            <el-button size="small" text type="success" :disabled="row.status === 'adopted'" @click="adoptById(row)">采纳</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { scenarioApi, docApi, projectApi } from '@/api'

const projects = ref<any[]>([])
const projectId = ref<string>('')
const endpoints = ref<any[]>([])
const selectedEndpointIds = ref<string[]>([])
const nlInput = ref<string>('')

const orchestrating = ref(false)
const dryRunning = ref(false)
const saving = ref(false)
const adopting = ref(false)
const historyLoading = ref(false)

const scenario = ref<any>(null)
const activeSteps = ref<number[]>([])
const history = ref<any[]>([])

const previewVisible = ref(false)
const previewData = ref<any>({})

const editVisible = ref(false)
const editStepsJson = ref<string>('')

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  orchestrated: '已编排',
  adopted: '已采纳',
}
const STATUS_TYPES: Record<string, any> = {
  draft: 'info',
  orchestrated: 'warning',
  adopted: 'success',
}

function statusLabel(s: string): string {
  return STATUS_LABELS[s] || s || '-'
}
function statusType(s: string): any {
  return STATUS_TYPES[s] || 'info'
}

const canOrchestrate = computed(() => !!projectId.value && !!nlInput.value.trim() && !orchestrating.value)

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
  selectedEndpointIds.value = []
  endpoints.value = []
  scenario.value = null
  await loadEndpoints()
  await loadHistory()
}

async function onEndpointVisible(visible: boolean) {
  if (visible) await loadEndpoints()
}

async function loadEndpoints() {
  if (!projectId.value) {
    endpoints.value = []
    return
  }
  try {
    const res: any = await docApi.listEndpoints({
      project_id: projectId.value,
      page: 1,
      page_size: 200,
    })
    endpoints.value = res?.data?.items || []
  } catch {
    endpoints.value = []
  }
}

async function orchestrate() {
  if (!canOrchestrate.value) return
  orchestrating.value = true
  try {
    const payload: any = {
      project_id: projectId.value,
      nl_input: nlInput.value,
    }
    if (selectedEndpointIds.value.length) payload.endpoint_ids = selectedEndpointIds.value
    const res: any = await scenarioApi.create(payload)
    scenario.value = res?.data || {}
    activeSteps.value = (scenario.value.steps || []).map((_: any, i: number) => i)
    ElMessage.success('场景编排完成')
    await loadHistory()
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    orchestrating.value = false
  }
}

async function dryRun() {
  if (!canOrchestrate.value) return
  dryRunning.value = true
  try {
    const payload: any = {
      project_id: projectId.value,
      nl_input: nlInput.value,
    }
    if (selectedEndpointIds.value.length) payload.endpoint_ids = selectedEndpointIds.value
    const res: any = await scenarioApi.dryRun(payload)
    previewData.value = res?.data || {}
    previewVisible.value = true
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    dryRunning.value = false
  }
}

async function save() {
  if (!scenario.value?.id) return
  saving.value = true
  try {
    const payload: any = {
      name: scenario.value.name,
      description: scenario.value.description,
      nl_input: scenario.value.nl_input,
      steps: scenario.value.steps,
    }
    const res: any = await scenarioApi.update(scenario.value.id, payload)
    scenario.value = res?.data || scenario.value
    ElMessage.success('已保存')
  } catch {
    /* ignore */
  } finally {
    saving.value = false
  }
}

async function adopt() {
  if (!scenario.value?.id) return
  adopting.value = true
  try {
    const res: any = await scenarioApi.adopt(scenario.value.id)
    scenario.value = res?.data || scenario.value
    ElMessage.success('场景已采纳')
    await loadHistory()
  } catch {
    /* ignore */
  } finally {
    adopting.value = false
  }
}

async function adoptById(row: any) {
  try {
    await scenarioApi.adopt(row.id)
    ElMessage.success('场景已采纳')
    await loadHistory()
  } catch {
    /* ignore */
  }
}

function editSteps() {
  if (!scenario.value?.steps) return
  editStepsJson.value = JSON.stringify(scenario.value.steps, null, 2)
  editVisible.value = true
}

function saveEditedSteps() {
  try {
    const parsed = JSON.parse(editStepsJson.value)
    if (!Array.isArray(parsed)) throw new Error('steps 必须为数组')
    scenario.value.steps = parsed
    editVisible.value = false
    ElMessage.success('步骤已更新，请点「保存步骤」落库')
  } catch (e: any) {
    ElMessage.error('JSON 解析失败：' + (e?.message || '格式错误'))
  }
}

async function loadHistory() {
  if (!projectId.value) {
    history.value = []
    return
  }
  historyLoading.value = true
  try {
    const res: any = await scenarioApi.list({ project_id: projectId.value, page: 1, page_size: 50 })
    history.value = res?.data?.items || []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

async function loadOne(row: any) {
  try {
    const res: any = await scenarioApi.get(row.id)
    scenario.value = res?.data || row
    activeSteps.value = (scenario.value.steps || []).map((_: any, i: number) => i)
  } catch {
    /* ignore */
  }
}

// 一旦切换项目重置当前场景
watch(projectId, () => {
  scenario.value = null
})

onMounted(async () => {
  await loadProjects()
})
</script>

<style scoped>
.muted {
  color: #909399;
  font-size: 13px;
  font-weight: normal;
}
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.method-tag {
  font-weight: 600;
  color: #409eff;
}
.url-text {
  font-family: monospace;
  font-size: 12px;
  color: #606266;
}
.action-desc {
  color: #909399;
  font-size: 12px;
}
.step-detail {
  font-size: 13px;
  line-height: 1.9;
}
.json-box {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
